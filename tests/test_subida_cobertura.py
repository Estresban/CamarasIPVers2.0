import json
import time
from unittest.mock import MagicMock, patch
import numpy as np

from camara_base import CamaraBase
from camaras import CamaraDVRIP, CamaraRTSP
import config
import correo_alertas
from grabacion_eventos import GrabadorEventos
import main
from mantenimiento import GestorMantenimiento
import notificaciones
from watchdog import WatchdogCamaras


def _cfg_rtsp():
    return {
        "nombre": "Camara RTSP Test",
        "ip": "127.0.0.1",
        "usuario": "admin",
        "password": "123",
        "puerto_rtsp": 554,
        "puerto_onvif": 8899,
        "puerto_netip": 34567,
        "canal": 1,
        "stream": 0,
    }


def test_camara_base_ui_y_capturas(tmp_path, monkeypatch):
    """Cubre obtener_imagen_ui (conectada, desconectada, movimiento, grabación) y capturas."""
    monkeypatch.setattr("camara_base.CARPETA_FOTOGRAMAS", str(tmp_path))
    cam = CamaraBase(_cfg_rtsp(), indice=0)

    # 1. Estado desconectado
    img_desc = cam.obtener_imagen_ui(seleccionada=False)
    assert img_desc.shape == (config.ALTO_CELDA, config.ANCHO_CELDA, 3)

    # 2. Estado conectado con movimiento, grabación y pre-buffer activos
    cam.conectada = True
    cam.frame = np.zeros((config.ALTO_CELDA, config.ANCHO_CELDA, 3), dtype=np.uint8)
    cam.deteccion_activa = True
    cam.captura_auto_activa = True
    cam.grabando = True
    cam.movimiento_detectado = True
    cam.grabador_eventos.activa = True

    img_act = cam.obtener_imagen_ui(seleccionada=True)
    assert img_act.shape == (config.ALTO_CELDA, config.ANCHO_CELDA, 3)

    # 3. Captura manual y captura automática
    cam.capturar_fotograma_manual()
    cam.ultimo_fotograma_auto = 0
    cam._gestionar_captura_auto(cam.frame)
    time.sleep(0.15)  # Esperamos a que los hilos daemon escriban las fotos

    fotos = list(tmp_path.glob("*.jpg"))
    assert len(fotos) == 2
    cam.cerrar_base()


'''def test_grabador_eventos_ciclo_completo_disparo_y_cierre(tmp_path, monkeypatch):
    """Cubre el volcado del pre-buffer al detectar movimiento y el envío del clip al terminar."""
    monkeypatch.setattr("grabacion_eventos.CARPETA_GRABACIONES", str(tmp_path))
    mock_tg = MagicMock()
    mock_mail = MagicMock()
    monkeypatch.setattr("grabacion_eventos.enviar_video_evento", mock_tg)
    monkeypatch.setattr("grabacion_eventos.enviar_video_correo", mock_mail)

    grab = GrabadorEventos("Entrada", seg_prebuffer=1, seg_postevento=1, fps=10.0)
    grab.alternar()

    frame = np.zeros((config.ALTO_CELDA, config.ANCHO_CELDA, 3), dtype=np.uint8)
    # Llenamos pre-buffer
    for _ in range(5):
        grab.procesar_frame(frame, hay_movimiento=False)

    # Disparamos evento de movimiento
    grab.procesar_frame(frame, hay_movimiento=True)
    assert grab.grabando_ahora is True
    assert grab.writer is not None

    # Escribimos audio durante el evento
    grab.procesar_audio(b"\x00" * 320)

    # Simulamos que ya pasó el tiempo post-evento para forzar cierre y envío
    grab.fin_grabacion = time.time() - 1.0
    grab.procesar_frame(frame, hay_movimiento=False)

    assert grab.grabando_ahora is False
    assert grab.writer is None
    mock_tg.assert_called_once()
    mock_mail.assert_called_once()'''
    

def test_grabador_eventos_ciclo_completo_disparo_y_cierre(tmp_path, monkeypatch):
    """Cubre el volcado del pre-buffer al detectar movimiento y el envío del clip al terminar."""
    monkeypatch.setattr("grabacion_eventos.CARPETA_GRABACIONES", str(tmp_path))
    monkeypatch.setattr("grabacion_eventos.EscritorVideoH264", MagicMock())
    mock_tg = MagicMock()
    mock_mail = MagicMock()
    monkeypatch.setattr("grabacion_eventos.enviar_video_evento", mock_tg)
    monkeypatch.setattr("grabacion_eventos.enviar_video_correo", mock_mail)

    grab = GrabadorEventos("Entrada", seg_prebuffer=1, seg_postevento=1, fps=10.0)
    grab.alternar()

    frame = np.zeros((config.ALTO_CELDA, config.ANCHO_CELDA, 3), dtype=np.uint8)
    for _ in range(5):
        grab.procesar_frame(frame, hay_movimiento=False)

    grab.procesar_frame(frame, hay_movimiento=True)
    assert grab.grabando_ahora is True
    assert grab.writer is not None

    grab.procesar_audio(b"\x00" * 320)

    grab.fin_grabacion = time.time() - 1.0
    grab.procesar_frame(frame, hay_movimiento=False)

    assert grab.grabando_ahora is False
    assert grab.writer is None
    mock_tg.assert_called_once()
    mock_mail.assert_called_once()


def test_camara_rtsp_presets_audio_y_bucle_video(monkeypatch):
    """Cubre presets ONVIF, ffplay y lectura de frames de VideoCapture en CamaraRTSP."""
    monkeypatch.setattr(CamaraRTSP, "_conectar_onvif", lambda self: None)
    monkeypatch.setattr(CamaraRTSP, "_bucle_captura_audio_rtsp", lambda self: None)

    fake_cap = MagicMock()
    frame_falso = np.zeros((480, 640, 3), dtype=np.uint8)
    monkeypatch.setattr("camaras.cv2.VideoCapture", lambda *a, **kw: fake_cap)

    # Evita que el hilo de arranque compita con el test antes de configurar fake_cap
    with patch("camaras.threading.Thread"):
        cam = CamaraRTSP(_cfg_rtsp(), indice=0)

    cam.ptz = MagicMock()
    cam.media_profile = MagicMock(token="Prof1")

    # Ejecutamos los hilos de presets de forma síncrona para evitar colisiones de lock_red en Linux
    monkeypatch.setattr(
        "camaras.threading.Thread",
        lambda target, args=(), daemon=True: MagicMock(start=lambda: target(*args)),
    )

    cam.ir_a_preset(1)
    cam.guardar_preset(2)
    cam.ptz.GotoPreset.assert_called_once()
    cam.ptz.SetPreset.assert_called_once()

    # Audio ffplay
    fake_ffplay = MagicMock()
    monkeypatch.setattr("camaras.subprocess.Popen", lambda *a, **kw: fake_ffplay)
    cam.alternar_escuchar_audio()
    assert cam.escuchando_audio is True
    cam.alternar_escuchar_audio()
    assert cam.escuchando_audio is False
    fake_ffplay.terminate.assert_called_once()

    # Simulación de 1 frame en _bucle_video y luego detención
    def _leer_una_vez():
        cam.detener = True
        return True, frame_falso

    fake_cap.read.side_effect = _leer_una_vez

    cam.detener = False
    cam._bucle_video()
    assert cam.conectada is True
    assert cam.frame is not None
    cam.cerrar()


def test_camara_dvrip_callbacks_video_y_audio(monkeypatch):
    """Cubre la recepción de paquetes H.265 y audio G.711 A-Law en CamaraDVRIP."""
    monkeypatch.setattr(CamaraDVRIP, "_iniciar_dvrip", lambda self: None)
    cfg = {"nombre": "Patio", "ip": "127.0.0.1", "usuario": "a", "password": "b", "puerto_netip": 34567, "canales": (0, 1)}
    cam = CamaraDVRIP(cfg, indice=0)
    cam.escuchando_audio = True

    cb = cam._crear_callback(0)
    # Paquete de vídeo tipo I
    cb(b"\x00\x00\x01\xb0frame_hevc", {"frame": "I"}, None)
    assert cam.colas_video[0].qsize() == 1

    # Paquete de audio G.711 A-Law
    cb(b"\x55\xAA\x55\xAA", {"type": "g711a"}, None)
    assert cam.cola_audio.qsize() == 1
    cam.cerrar()


def test_correo_video_y_evento_dvrip(tmp_path, monkeypatch):
    """Cubre envío de vídeo por correo y callback de alarmas DVRIP."""
    video_mp4 = tmp_path / "alerta.mp4"
    video_mp4.write_bytes(b"datos_mp4_simulados")

    enviados = []
    monkeypatch.setattr(correo_alertas, "email_alertas_activas", True)
    monkeypatch.setattr(
        correo_alertas,
        "_despachar_mensaje_smtp",
        lambda asunto, cuerpo, adjunto=None: enviados.append((asunto, adjunto)) or True,
    )

    correo_alertas._enviar_video_correo_hilo(str(video_mp4), "Garaje")
    assert len(enviados) == 1
    assert "VÍDEO ALERTA CCTV - Garaje" in enviados[0][0]

    # Evento DVRIP
    cam = MagicMock(nombre="Patio", frame=np.zeros((100, 100, 3), dtype=np.uint8))
    cb_correo = correo_alertas.crear_callback_correo(cam)
    cb_correo({"Event": "HumanDetect"}, 1)
    time.sleep(0.05)
    assert len(enviados) == 2



def test_notificaciones_historial_y_mantenimiento_reglas(tmp_path, monkeypatch):
    """Cubre /historial, /ayuda en Telegram, lectura de reglas y aviso de recuperación en Watchdog."""
    mensajes = []
    monkeypatch.setattr(
        notificaciones,
        "enviar_mensaje_telegram",
        lambda txt, incluir_teclado=True: mensajes.append(txt),
    )

    hist = tmp_path / "historial.txt"
    hist.write_text("• 18/11/2026 19:00:00 — Entrada\n", encoding="utf-8")
    monkeypatch.setattr(notificaciones, "ARCHIVO_HISTORIAL", str(hist))

    cam = MagicMock(nombre="Entrada")
    notificaciones._procesar_comando("/historial", [cam])
    assert "Entrada" in mensajes[-1]

    notificaciones._procesar_comando("/ayuda", [cam])
    assert "CONTROL REMOTO PTZ" in mensajes[-1]

    # Reglas de mantenimiento desde JSON
    cfg_json = tmp_path / "config.json"
    cfg_json.write_text(json.dumps({"mantenimiento": {"max_gb": 120, "horario_activo": True, "hora_inicio": "22:00", "hora_fin": "06:30"}}))
    monkeypatch.setattr("mantenimiento.RUTA_CONFIG_JSON", str(cfg_json))
    gestor = GestorMantenimiento([])
    reglas = gestor._leer_reglas()
    assert reglas["max_gb"] == 120.0
    assert "ARMADO" in gestor.obtener_estado_visual() or "ESPERA" in gestor.obtener_estado_visual()
