import json
import logging
import socket
import struct
import threading
import time
from unittest.mock import MagicMock
import numpy as np

from camara_base import CamaraBase
from camaras import CamaraDVRIP
import config
from escritor_video import EscritorVideoH264
import logger
import main


def test_protocolo_netip_login_y_luz_led():
    """Simula una cámara NetIP real en localhost para validar la cabecera binaria de 20 bytes y el JSON."""
    paquetes_recibidos = []
    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    servidor.bind(("127.0.0.1", 0))
    puerto_libre = servidor.getsockname()[1]
    servidor.listen(1)

    def _simular_camara():
        conn, _ = servidor.accept()
        with conn:
            # 1. Recibimos paquete de Login (código 1000)
            data_login = conn.recv(1024)
            paquetes_recibidos.append(data_login)
            # Respondemos con SessionID = 0x12345678 en bytes 4..8
            resp_login = struct.pack("<BB2xII2xHI", 0xFF, 0x00, 0x12345678, 0, 1001, 2) + b"\x0a\x00"
            conn.sendall(resp_login)

            # 2. Recibimos comando de Luz Blanca (código 1040)
            data_luz = conn.recv(1024)
            paquetes_recibidos.append(data_luz)
            conn.sendall(resp_login)

    hilo_srv = threading.Thread(target=_simular_camara, daemon=True)
    hilo_srv.start()

    cfg = {
        "nombre": "Camara NetIP Test",
        "ip": "127.0.0.1",
        "usuario": "admin",
        "password": "123",
        "puerto_netip": puerto_libre,
    }
    cam = CamaraBase(cfg, indice=0)
    cam.cambiar_luz_led("BLANCA")
    hilo_srv.join(timeout=2.0)
    servidor.close()
    cam.cerrar_base()

    assert len(paquetes_recibidos) == 2

    # Validamos cabecera de Login (código comando = 1000) -> 6 campos en "<BB2xII2xHI"
    _, _, _, _, cmd_login, _ = struct.unpack("<BB2xII2xHI", paquetes_recibidos[0][:20])
    assert cmd_login == 1000

    # Validamos cabecera y carga JSON de Luz Blanca (SessionID = 0x12345678, comando = 1040)
    _, _, sid, _, cmd_luz, _ = struct.unpack("<BB2xII2xHI", paquetes_recibidos[1][:20])
    assert sid == 0x12345678
    assert cmd_luz == 1040
    payload_json = json.loads(paquetes_recibidos[1][20:-2].decode("utf-8"))
    assert payload_json["Camera.WhiteLight"]["WorkMode"] == "KeepOpen"


def test_camara_dvrip_comandos_ptz_y_presets(monkeypatch):
    """Comprueba que CamaraDVRIP traduce correctamente ejes PTZ y presets sin abrir hilos de red."""
    monkeypatch.setattr(CamaraDVRIP, "_iniciar_dvrip", lambda self: None)
    monkeypatch.setattr(time, "sleep", lambda _s: None)

    cfg = {
        "nombre": "Patio DVRIP",
        "ip": "127.0.0.1",
        "usuario": "admin",
        "password": "123",
        "puerto_netip": 34567,
        "canales": (0, 1),
    }
    cam = CamaraDVRIP(cfg, indice=0)
    cam.cam_control = MagicMock()

    # Movimiento hacia arriba (pan=0, tilt=0.5, zoom=0) -> debe enviar DirectionUp con Preset 65535 y luego -1
    cam.mover_ptz(0.0, 0.5, 0.0)
    time.sleep(0.05)
    assert cam.cam_control.set_command.call_count == 2
    primer_llamado = cam.cam_control.set_command.call_args_list[0][0]
    assert primer_llamado[0] == "OPPTZControl"
    assert primer_llamado[1]["Command"] == "DirectionUp"
    assert primer_llamado[1]["Parameter"]["Preset"] == 65535

    # Ir a Preset 2 -> GotoPreset
    cam.cam_control.reset_mock()
    cam.ir_a_preset(2)
    time.sleep(0.05)
    llamado_preset = cam.cam_control.set_command.call_args[0]
    assert llamado_preset[1]["Command"] == "GotoPreset"
    assert llamado_preset[1]["Parameter"]["Preset"] == 2
    cam.cerrar()


def test_escritor_video_h264_con_audio_aac(tmp_path):
    """Comprueba que EscritorVideoH264 multiplexa vídeo BGR + audio PCM en un MP4 válido."""
    ruta_mp4 = tmp_path / "video_con_audio.mp4"
    writer = EscritorVideoH264(str(ruta_mp4), fps=10.0, ancho=320, alto=180, con_audio=True)

    frame = np.zeros((180, 320, 3), dtype=np.uint8)
    # 0.1 segundos de audio PCM int16 a 8000 Hz mono = 800 muestras = 1600 bytes
    muestras_audio = np.zeros(800, dtype=np.int16).tobytes()

    for _ in range(10):
        writer.write(frame)
        writer.write_audio(muestras_audio)

    writer.release()
    assert ruta_mp4.exists()
    assert ruta_mp4.stat().st_size > 1000


def test_logger_captura_print_en_archivo(tmp_path, monkeypatch):
    """Verifica que configurar_logs() redirige print() a sistema.log sin interferir con pytest."""
    ruta_log_test = tmp_path / "sistema_test.log"
    monkeypatch.setattr(logger, "DIR_DATOS", str(tmp_path))
    monkeypatch.setattr(logger, "RUTA_LOG", str(ruta_log_test))

    log_inst = logging.getLogger("StiViHome")
    for h in list(log_inst.handlers):
        h.close()
        log_inst.removeHandler(h)

    stdout_pytest = logger.sys.stdout
    stderr_pytest = logger.sys.stderr
    try:
        logger.configurar_logs()
        logger.sys.stdout.write("Mensaje de prueba unitaria StiViHome\n")
        for h in log_inst.handlers:
            h.flush()
    finally:
        logger.sys.stdout = stdout_pytest
        logger.sys.stderr = stderr_pytest

    assert ruta_log_test.exists()
    contenido = ruta_log_test.read_text(encoding="utf-8")
    assert "Mensaje de prueba unitaria StiViHome" in contenido



def test_ui_dibujar_interfaz_y_panel():
    """Comprueba que el renderizado del mosaico y del panel lateral genera las dimensiones exactas."""
    cam = MagicMock()
    cam.obtener_imagen_ui.return_value = np.zeros((config.ALTO_CELDA, config.ANCHO_CELDA, 3), dtype=np.uint8)
    cam.modo_luz_actual = "Auto"
    cam.deteccion_activa = True
    cam.grabando = False
    cam.captura_auto_activa = False
    cam.escuchando_audio = False
    cam.hablando_micro = False
    cam.grabador_eventos = MagicMock(activa=False)

    lienzo = main.dibujar_interfaz([cam], indice_activo=0)
    assert lienzo.shape == (config.ALTO_TOTAL_BASE, config.ANCHO_TOTAL_BASE, 3)

    panel = main.dibujar_panel(0, [cam], mantenimiento=None)
    assert panel.shape == (config.ALTO_TOTAL_BASE, main.ANCHO_PANEL, 3)


def test_atajos_teclado_main():
    """Verifica los atajos principales de teclado en controlar_camara()."""
    cam = MagicMock()
    main.controlar_camara(cam, ord("m"))
    cam.alternar_deteccion.assert_called_once()

    main.controlar_camara(cam, ord("r"))
    cam.alternar_grabacion.assert_called_once()

    main.controlar_camara(cam, ord(" "))
    cam.capturar_fotograma_manual.assert_called_once()

    main.controlar_camara(cam, ord("1"))
    cam.cambiar_luz_led.assert_called_with("BLANCA")
