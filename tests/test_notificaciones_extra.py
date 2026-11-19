import json
from unittest.mock import MagicMock, patch
import numpy as np
import pytest
import notificaciones
from unittest.mock import MagicMock
import notificaciones

@pytest.fixture
def camara_mock():
    cam = MagicMock()
    cam.nombre = "Jardín"
    cam.frame = np.zeros((100, 100, 3), dtype=np.uint8)
    cam.grabando = False
    cam.deteccion_activa = True
    cam.modo_luz_actual = "AUTO"
    cam.zoom_digital = 1.2
    cam.grabador_eventos.activa = False
    return cam


def test_envio_http_telegram_exito_y_error():
    mock_conn = MagicMock()
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"ok": true}'
    mock_conn.getresponse.return_value = mock_resp

    with patch("notificaciones._obtener_credenciales", return_value=("TOKEN", "12345")), \
         patch("notificaciones.http.client.HTTPSConnection", return_value=mock_conn):
        notificaciones.enviar_mensaje_telegram("Hola mundo", incluir_teclado=True)
        assert mock_conn.request.called

        # Multipart foto
        img = np.zeros((50, 50, 3), dtype=np.uint8)
        notificaciones._enviar_foto_telegram(img, "Alerta foto")
        assert mock_conn.request.call_count == 2

    # Error de red controlado
    with patch("notificaciones._obtener_credenciales", return_value=("TOKEN", "12345")), \
         patch("notificaciones.http.client.HTTPSConnection", side_effect=OSError("Sin red")):
        notificaciones.enviar_mensaje_telegram("Fallo")
        assert notificaciones._enviar_multipart_telegram("sendPhoto", "photo", "a.jpg", "image/jpeg", b"123", "cap") is False


def test_procesar_todos_los_comandos_bot(camara_mock, tmp_path):
    camaras = [camara_mock]
    notificaciones.camara_telegram_idx = 0
    notificaciones.alertas_activas = True

    hist_file = tmp_path / "historial.txt"
    hist_file.write_text("• 10/10/2026 — Jardín\n", encoding="utf-8")
    log_file = tmp_path / "sistema.log"
    log_file.write_text("INFO: Todo ok\n", encoding="utf-8")

    with patch("notificaciones.enviar_mensaje_telegram") as mock_msg, \
         patch("notificaciones._enviar_foto_telegram") as mock_foto, \
         patch("notificaciones.ARCHIVO_HISTORIAL", str(hist_file)), \
         patch("notificaciones.RUTA_LOG", str(log_file)), \
         patch("notificaciones.time.sleep"):

        # Sin cámaras
        notificaciones._procesar_comando("/start", [])
        assert "No hay cámaras" in mock_msg.call_args[0][0]

        # Comandos principales
        for cmd in [
            "/start", "/sel1", "/sel9", "/ptz_arriba", "/zoom_mas",
            "/foto_actual", "/luz_actual", "/grabar_actual", "/estado",
            "/alertas", "/email", "/historial", "/logs", "/foto1",
            "/grabar1", "/deteccion1", "/prebuffer1", "/luz1",
            "/preset1", "/setpreset2", "/comando_inventado"
        ]:
            notificaciones._procesar_comando(cmd, camaras)

    assert camara_mock.mover_ptz.called
    assert camara_mock.cambiar_zoom.called
    assert camara_mock.alternar_grabacion.called
    assert camara_mock.alternar_deteccion.called
    assert camara_mock.alternar_grab_movimiento.called
    assert camara_mock.cambiar_luz_led.called
    assert camara_mock.ir_a_preset.called
    assert camara_mock.guardar_preset.called
    assert mock_foto.called


def test_iniciar_bot_comandos_bucle(camara_mock):
    payload = json.dumps({
        "ok": True,
        "result": [{"update_id": 10, "message": {"chat": {"id": "999"}, "text": "/estado"}}],
    }).encode("utf-8")

    mock_conn = MagicMock()
    mock_resp = MagicMock()
    mock_resp.read.return_value = payload
    mock_conn.getresponse.return_value = mock_resp

    def detener_tras_procesar(_texto, _cams):
        notificaciones.detener_bot()

    with patch("notificaciones._obtener_credenciales", return_value=("TOKEN", "999")), \
         patch("notificaciones.http.client.HTTPSConnection", return_value=mock_conn), \
         patch("notificaciones._procesar_comando", side_effect=detener_tras_procesar) as mock_proc, \
         patch("notificaciones.threading.Thread") as mock_th:
        mock_th.side_effect = lambda target, daemon=True: MagicMock(start=target)
        notificaciones.iniciar_bot_comandos([camara_mock])

    mock_proc.assert_called_once_with("/estado", [camara_mock])

def test_notificaciones_casos_limite_historial_logs_y_videos(camara_mock, tmp_path):
    # 1. Sin credenciales válidas -> retorna sin hacer peticiones HTTP (104, 112, 136, 443)
    with patch("notificaciones._obtener_credenciales", return_value=(None, None)), \
         patch("notificaciones.http.client.HTTPSConnection") as mock_http:
        notificaciones.enviar_mensaje_telegram("Test sin token")
        assert notificaciones._enviar_multipart_telegram("sendPhoto", "photo", "a.jpg", "image/jpeg", b"1", "c") is False
        notificaciones.iniciar_bot_comandos([camara_mock])
        assert not mock_http.called

    # 2. Envío de vídeo de evento: archivo válido y archivo inexistente (179-193)
    video_mp4 = tmp_path / "evento.mp4"
    video_mp4.write_bytes(b"FAKE_MP4_DATA")

    notificaciones.alertas_activas = True
    with patch("notificaciones._enviar_multipart_telegram", return_value=True) as mock_multi, \
         patch("notificaciones.threading.Thread") as mock_th:
        mock_th.side_effect = lambda target, args=(), daemon=True: MagicMock(start=lambda: target(*args))
        notificaciones.enviar_video_evento(str(video_mp4), "Patio")
        notificaciones.enviar_video_evento(str(tmp_path / "no_existe.mp4"), "Patio")
    assert mock_multi.called

    # 3. enviar_alerta_movimiento: escribe en historial.txt y lanza hilo de foto (206-213)
    hist_path = tmp_path / "historial.txt"
    img = np.zeros((40, 40, 3), dtype=np.uint8)
    with patch("notificaciones.DIR_DATOS", str(tmp_path)), \
         patch("notificaciones.ARCHIVO_HISTORIAL", str(hist_path)), \
         patch("notificaciones._enviar_foto_telegram") as mock_foto, \
         patch("notificaciones.threading.Thread") as mock_th:
        mock_th.side_effect = lambda target, args=(), daemon=True: MagicMock(start=lambda: target(*args))
        notificaciones.enviar_alerta_movimiento(img, "Entrada")
    assert "Entrada" in hist_path.read_text(encoding="utf-8")
    assert mock_foto.called

    # 4. /historial y /logs: vacíos, inexistentes, truncado (>3800 chars) y OSError (322-354)
    log_path = tmp_path / "sistema.log"
    with patch("notificaciones.enviar_mensaje_telegram") as mock_msg, \
         patch("notificaciones.ARCHIVO_HISTORIAL", str(tmp_path / "sin_hist.txt")), \
         patch("notificaciones.RUTA_LOG", str(tmp_path / "sin_log.log")):
        notificaciones._procesar_comando("/historial", [camara_mock])
        notificaciones._procesar_comando("/logs", [camara_mock])

        # Archivos vacíos
        hist_path.write_text("", encoding="utf-8")
        log_path.write_text("", encoding="utf-8")
        with patch("notificaciones.ARCHIVO_HISTORIAL", str(hist_path)), \
             patch("notificaciones.RUTA_LOG", str(log_path)):
            notificaciones._procesar_comando("/historial", [camara_mock])
            notificaciones._procesar_comando("/logs", [camara_mock])

            # Log largo: 15 líneas de 300 caracteres (> 3800 chars en total) para forzar truncado
            log_path.write_text((("X" * 300 + "\n") * 20), encoding="utf-8")
            notificaciones._procesar_comando("/logs", [camara_mock])
            assert "..." in str(mock_msg.call_args)

        # Cámara fuera de rango en comando individual (365-366)
        notificaciones._procesar_comando("/foto9", [camara_mock])
        assert "no existe" in str(mock_msg.call_args)

    # 5. Error de red dentro del bucle de escucha del bot (466-468)
    def detener_en_sleep(_seg):
        notificaciones.detener_bot()

    with patch("notificaciones._obtener_credenciales", return_value=("TOKEN", "999")), \
         patch("notificaciones.http.client.HTTPSConnection", side_effect=OSError("Timeout polling")), \
         patch("notificaciones.time.sleep", side_effect=detener_en_sleep), \
         patch("notificaciones.threading.Thread") as mock_th:
        mock_th.side_effect = lambda target, daemon=True: MagicMock(start=target)
        notificaciones.iniciar_bot_comandos([camara_mock])


####################################################


def _crear_camara_falsa(nombre):
    cam = MagicMock()
    cam.nombre = nombre
    cam.grabando = False
    cam.deteccion_activa = False
    cam.modo_luz_actual = "Auto"
    cam.zoom_digital = 1.0
    cam.frame = None
    cam.grabador_eventos = MagicMock(activa=False)
    return cam


def test_comandos_telegram_ptz_y_presets(monkeypatch):
    mensajes_enviados = []
    monkeypatch.setattr(
        notificaciones,
        "enviar_mensaje_telegram",
        lambda texto, incluir_teclado=True: mensajes_enviados.append(texto),
    )

    cam1 = _crear_camara_falsa("Entrada")
    cam2 = _crear_camara_falsa("Jardin")
    camaras = [cam1, cam2]

    # Seleccionar cámara 2 usando el texto del botón táctil
    notificaciones._procesar_comando("📹 Cám 2", camaras)
    assert notificaciones.camara_telegram_idx == 1

    # Mover PTZ hacia arriba debe afectar a cam2
    notificaciones._procesar_comando("⬆️ Arriba", camaras)
    cam2.mover_ptz.assert_called_once_with(0.0, 0.5, 0.0)
    cam1.mover_ptz.assert_not_called()

    # Guardar preset 1 en cam2
    notificaciones._procesar_comando("/setpreset1", camaras)
    cam2.guardar_preset.assert_called_once_with(1)


def test_guardar_historial_movimiento(tmp_path, monkeypatch):
    archivo_hist = tmp_path / "historial.txt"
    monkeypatch.setattr(notificaciones, "ARCHIVO_HISTORIAL", str(archivo_hist))
    monkeypatch.setattr(notificaciones, "alertas_activas", False)  # Evita enviar HTTP real

    notificaciones.enviar_alerta_movimiento(None, "Garaje")

    contenido = archivo_hist.read_text(encoding="utf-8")
    assert "Garaje" in contenido
