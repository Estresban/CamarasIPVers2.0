import json
from unittest.mock import MagicMock, patch
import numpy as np
import correo_alertas
import time
import config
import correo_alertas
from escritor_video import EscritorVideoH264
import main


def test_correo_config_json_y_errores_smtp(tmp_path):
    cfg_file = tmp_path / "config.json"

    # 1. JSON corrupto -> maneja excepción sin romper (49-50)
    cfg_file.write_text("{json_invalido", encoding="utf-8")
    with patch("correo_alertas.RUTA_CONFIG_JSON", str(cfg_file)):
        cfg = correo_alertas._obtener_config_email()
        assert isinstance(cfg, dict)

    # 2. JSON válido -> descifra secreto
    cfg_file.write_text(
        json.dumps({"email": {"remitente": "a@b.com", "password": "ENC:123"}}),
        encoding="utf-8",
    )
    with patch("correo_alertas.RUTA_CONFIG_JSON", str(cfg_file)), \
         patch("correo_alertas.descifrar_secreto", return_value="secreto_plano"):
        cfg = correo_alertas._obtener_config_email()
        assert cfg["password"] == "secreto_plano"

    # 3. Credenciales incompletas o por defecto -> retorna False (81)
    with patch("correo_alertas._obtener_config_email", return_value={
        "remitente": "", "password": "", "destinatario": ""
    }):
        assert correo_alertas._despachar_mensaje_smtp("Asunto", "Cuerpo") is False

    # 4. Excepción en SMTP_SSL -> retorna False controlado (107-109)
    with patch("correo_alertas._obtener_config_email", return_value={
        "remitente": "a@b.com",
        "password": "clave",
        "destinatario": "c@d.com",
        "smtp_servidor": "://test.com",
        "smtp_puerto": 465,
    }), patch("correo_alertas.smtplib.SMTP_SSL", side_effect=OSError("Timeout SMTP")):
        assert correo_alertas._despachar_mensaje_smtp("Asunto", "Cuerpo") is False


def test_correo_eventos_dvrip_rtsp_y_cooldown():
    cam = MagicMock()
    cam.nombre = "Garaje"
    cam.frame = np.zeros((40, 40, 3), dtype=np.uint8)

    # Con alertas desactivadas retorna inmediatamente (115, 159)
    correo_alertas.email_alertas_activas = False
    assert correo_alertas.enviar_correo_evento(cam, "Test") is False
    correo_alertas.procesar_evento_correo(cam, {"tipo": "mov"}, 1)

    # Activamos alertas y limpiamos historial de envíos
    correo_alertas.email_alertas_activas = True
    correo_alertas._ultimos_envios.clear()

    # Objeto no serializable a JSON para cubrir el except de json.dumps (167-168)
    class NoSerializable:
        def __str__(self):
            return "EventoCustom"

    cb = correo_alertas.crear_callback_correo(cam)

    with patch("correo_alertas._obtener_config_email", return_value={
        "adjuntar_foto": True, "intervalo_alertas": 60
    }), patch("correo_alertas.threading.Thread") as mock_th, \
         patch("correo_alertas.enviar_correo_evento") as mock_enviar:
        mock_th.side_effect = lambda target, args=(), daemon=True: MagicMock(start=lambda: target(*args))

        # Primer disparo pasa y lanza hilo
        cb(NoSerializable(), 1)
        assert mock_enviar.called

        # Segundo disparo inmediato bloqueado por intervalo_alertas (163)
        cb({"tipo": "mov"}, 2)
        assert mock_enviar.call_count == 1

        # Alerta RTSP en cámara distinta (193-200)
        img = np.zeros((30, 30, 3), dtype=np.uint8)
        correo_alertas.enviar_alerta_correo_rtsp("Puerta", img)
        assert mock_enviar.call_count == 2


def test_correo_envio_video_evento(tmp_path):
    # Desactivado -> no hace nada (232-234)
    correo_alertas.email_alertas_activas = False
    correo_alertas.enviar_video_correo("no_importa.mp4", "Patio")

    # Activado: prueba archivo inexistente (212-214) y archivo válido
    correo_alertas.email_alertas_activas = True
    video_ok = tmp_path / "clip.mp4"
    video_ok.write_bytes(b"MP4_BYTES")

    with patch("correo_alertas._despachar_mensaje_smtp", return_value=True) as mock_smtp, \
         patch("correo_alertas.threading.Thread") as mock_th:
        mock_th.side_effect = lambda target, args=(), daemon=True: MagicMock(start=lambda: target(*args))

        correo_alertas.enviar_video_correo(str(tmp_path / "inexistente.mp4"), "Patio")
        assert not mock_smtp.called

        correo_alertas.enviar_video_correo(str(video_ok), "Patio")
        assert mock_smtp.called


################################################




def test_escritor_video_h264_crea_mp4_valido(tmp_path):
    ruta_mp4 = tmp_path / "prueba_salida.mp4"
    writer = EscritorVideoH264(str(ruta_mp4), fps=10.0, ancho=320, alto=180, con_audio=False)

    frame = np.zeros((180, 320, 3), dtype=np.uint8)
    for _ in range(10):
        writer.write(frame)
    writer.release()

    assert ruta_mp4.exists()
    assert ruta_mp4.stat().st_size > 500  # El contenedor MP4 debe tener cabecera y datos


def test_correo_intervalo_antispam(monkeypatch):
    monkeypatch.setattr(
        correo_alertas,
        "_obtener_config_email",
        lambda: {"intervalo_alertas": 60},
    )
    correo_alertas._ultimos_envios.clear()

    # El primer envío para "Patio" debe permitirse
    assert correo_alertas._puede_enviar_alerta("Patio") is True
    # El segundo inmediato debe bloquearse por anti-spam
    assert correo_alertas._puede_enviar_alerta("Patio") is False
    # Otra cámara independiente sí debe poder enviar
    assert correo_alertas._puede_enviar_alerta("Garaje") is True


def test_geometria_mosaico_main(monkeypatch):
    monkeypatch.setattr(main, "vista_ampliada", False)

    monkeypatch.setattr(config, "MODO_MOSAICO", 4)
    assert main.obtener_geometria_mosaico() == (2, 2, config.ANCHO_CELDA, config.ALTO_CELDA)

    monkeypatch.setattr(config, "MODO_MOSAICO", 2)
    assert main.obtener_geometria_mosaico() == (2, 1, config.ANCHO_TOTAL_BASE // 2, config.ALTO_TOTAL_BASE)

    monkeypatch.setattr(main, "vista_ampliada", True)
    assert main.obtener_geometria_mosaico() == (1, 1, config.ANCHO_TOTAL_BASE, config.ALTO_TOTAL_BASE)
