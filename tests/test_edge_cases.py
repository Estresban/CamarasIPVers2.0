import smtplib
import time
from unittest.mock import MagicMock
import numpy as np
import threading

from camara_base import CamaraBase
from camaras import CamaraRTSP
import config
import correo_alertas
from mantenimiento import GestorMantenimiento
import notificaciones


def test_correo_construye_mime_con_foto_adjunta(monkeypatch):
    """Comprueba que enviar_correo_evento construye el correo MIME con imagen JPEG adjunta."""
    mensajes_smtp = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=25):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def login(self, user, pwd):
            assert user == "origen@test.com"
            assert pwd == "clave_app_123"

        def send_message(self, msg):
            mensajes_smtp.append(msg)

    monkeypatch.setattr(correo_alertas, "email_alertas_activas", True)
    monkeypatch.setattr(
        correo_alertas,
        "_obtener_config_email",
        lambda: {
            "adjuntar_foto": True,
            "remitente": "origen@test.com",
            "password": "clave_app_123",
            "destinatario": "destino@test.com",
            "smtp_servidor": "://test.com",
            "smtp_puerto": 465,
            "intervalo_alertas": 60,
        },
    )
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)

    cam_falsa = type("Cam", (), {"nombre": "Entrada"})()
    imagen = np.zeros((180, 320, 3), dtype=np.uint8)

    assert correo_alertas.enviar_correo_evento(cam_falsa, "Movimiento en puerta", imagen) is True
    assert len(mensajes_smtp) == 1
    msg = mensajes_smtp[0]
    assert msg["Subject"] == "ALERTA CCTV - Entrada"
    adjuntos = list(msg.iter_attachments())
    assert len(adjuntos) == 1
    assert adjuntos[0].get_content_type() == "image/jpeg"


def test_telegram_envio_multipart_foto(monkeypatch):
    """Valida que _enviar_foto_telegram arma correctamente el cuerpo multipart/form-data."""
    peticiones = []

    class FakeHTTPS:
        def __init__(self, host, timeout=30):
            pass

        def request(self, method, path, body=None, headers=None):
            peticiones.append((method, path, body, headers))

        def getresponse(self):
            resp = MagicMock()
            resp.read.return_value = b'{"ok": true}'
            return resp

        def close(self):
            pass

    monkeypatch.setattr(config, "TELEGRAM_TOKEN", "12345:TOKEN_PRUEBA")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "99887766")
    monkeypatch.setattr(notificaciones.http.client, "HTTPSConnection", FakeHTTPS)

    img = np.zeros((180, 320, 3), dtype=np.uint8)
    notificaciones._enviar_foto_telegram(img, "Alerta prueba multipart")

    assert len(peticiones) == 1
    metodo, ruta, cuerpo, cabeceras = peticiones[0]
    assert metodo == "POST"
    assert "/bot12345:TOKEN_PRUEBA/sendPhoto" in ruta
    assert b"99887766" in cuerpo
    assert b"Alerta prueba multipart" in cuerpo
    assert "multipart/form-data" in cabeceras["Content-Type"]



def test_camara_rtsp_ptz_onvif_stop_tras_mover(monkeypatch):
    """Comprueba que CamaraRTSP ejecuta ContinuousMove y detiene el motor con Stop."""
    monkeypatch.setattr(CamaraRTSP, "_conectar_onvif", lambda self: None)
    monkeypatch.setattr(CamaraRTSP, "_bucle_video", lambda self: None)
    monkeypatch.setattr(CamaraRTSP, "_bucle_captura_audio_rtsp", lambda self: None)
    monkeypatch.setattr(time, "sleep", lambda _s: None)

    cfg = {
        "nombre": "RTSP PTZ",
        "ip": "127.0.0.1",
        "usuario": "admin",
        "password": "123",
        "puerto_rtsp": 554,
        "puerto_onvif": 8899,
        "puerto_netip": 34567,
        "canal": 1,
        "stream": 0,
    }

    cam = CamaraRTSP(cfg, indice=0)
    cam.ptz = MagicMock()
    cam.media_profile = MagicMock(token="Perfil_0")

    stop_event = threading.Event()
    cam.ptz.Stop.side_effect = lambda *args, **kwargs: stop_event.set()

    cam.mover_ptz(0.5, 0.0, 0.0)

    assert stop_event.wait(timeout=2), "El hilo PTZ no llegó a ejecutar Stop"

    cam.ptz.ContinuousMove.assert_called_once()
    cam.ptz.Stop.assert_called_once_with({"ProfileToken": "Perfil_0"})

    cam.cerrar()



def test_grabacion_continua_rotacion_de_bloques(tmp_path, monkeypatch):
    """Verifica que _gestionar_grabacion cierra el bloque anterior y abre uno nuevo al vencer el tiempo."""
    writers_creados = []

    class FakeWriter:
        def __init__(self, ruta, fps, w, h, con_audio=False):
            self.ruta = ruta
            self.liberado = False
            self.frames = 0
            writers_creados.append(self)

        def write(self, frame):
            self.frames += 1

        def release(self):
            self.liberado = True

    monkeypatch.setattr("camara_base.CARPETA_GRABACIONES", str(tmp_path))
    monkeypatch.setattr("camara_base.EscritorVideoH264", FakeWriter)
    monkeypatch.setattr(config, "MINUTOS_POR_BLOQUE_VIDEO", 1)

    cfg = {"nombre": "Cam Bloques", "ip": "127.0.0.1", "usuario": "a", "password": "b", "puerto_netip": 34567}
    cam = CamaraBase(cfg, indice=0)
    cam.alternar_grabacion()

    frame = np.zeros((360, 640, 3), dtype=np.uint8)
    cam._gestionar_grabacion(frame)
    assert len(writers_creados) == 1
    assert writers_creados[0].liberado is False

    # Simulamos que ya pasaron 65 segundos desde el inicio del bloque
    cam.inicio_bloque = time.time() - 65
    cam._gestionar_grabacion(frame)

    assert len(writers_creados) == 2
    assert writers_creados[0].liberado is True
    assert writers_creados[1].liberado is False
    cam.cerrar_base()


def test_gestor_mantenimiento_armado_y_desarmado_global(monkeypatch):
    """Comprueba que el armado horario activa/desactiva cámaras y alertas a la vez."""
    monkeypatch.setattr(notificaciones, "enviar_mensaje_telegram", MagicMock())

    cam = MagicMock()
    cam.deteccion_activa = False
    cam.grabador_eventos = MagicMock(activa=False)

    gestor = GestorMantenimiento([cam])

    # Armar sistema
    gestor._aplicar_estado_armado(True)
    cam.alternar_deteccion.assert_called_once()
    cam.alternar_grab_movimiento.assert_called_once()
    assert notificaciones.alertas_activas is True
    assert correo_alertas.email_alertas_activas is True

    # Desarmar sistema
    cam.deteccion_activa = True
    cam.grabador_eventos.activa = True
    gestor._aplicar_estado_armado(False)
    assert cam.alternar_deteccion.call_count == 2
    assert cam.alternar_grab_movimiento.call_count == 2
    assert notificaciones.alertas_activas is False
    assert correo_alertas.email_alertas_activas is False
