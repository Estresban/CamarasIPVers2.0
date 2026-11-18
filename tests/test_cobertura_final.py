import json
import socket
import struct
import subprocess
import threading
import time
from unittest.mock import MagicMock
import cv2
import numpy as np

from camara_base import CamaraBase
from camaras import CamaraDVRIP
import config
from escritor_video import EscritorVideoH264
import main
import notificaciones


def test_audio_bidireccional_netip_optalk(monkeypatch):
    """Simula micrófono PC -> Cámara y verifica la secuencia Claim -> Start -> Audio ALAW -> Stop."""
    codigos_recibidos = []
    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    servidor.bind(("127.0.0.1", 0))
    puerto = servidor.getsockname()[1]
    servidor.listen(1)

    cfg = {
        "nombre": "Camara Voz",
        "ip": "127.0.0.1",
        "usuario": "admin",
        "password": "123",
        "puerto_netip": puerto,
    }
    cam = CamaraBase(cfg, indice=0)

    class FakeMic:
        def __init__(self, **_kwargs):
            self.lecturas = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, chunk_size):
            self.lecturas += 1
            if self.lecturas >= 2:
                cam.hablando_micro = False  # Detiene el bucle tras enviar 2 paquetes de voz
            return np.zeros((chunk_size, 1), dtype=np.int16), False

    def _simular_camara_audio():
        conn, _ = servidor.accept()
        with conn:
            resp_ok = struct.pack("<BB2xII2xHI", 0xFF, 0x00, 0xABCDEF01, 0, 1001, 2) + b"\x0a\x00"
            # Esperamos: 1 Login + 1 Claim + 1 Start + 2 Audio + 1 Stop = 6 mensajes
            for _ in range(6):
                cab = conn.recv(20)
                if len(cab) < 20:
                    break
                _, _, _, _, cmd, longitud = struct.unpack("<BB2xII2xHI", cab)
                if longitud > 0:
                    conn.recv(longitud)
                codigos_recibidos.append(cmd)
                if cmd != 1432:  # Los paquetes de audio (1432) no esperan respuesta ACK
                    conn.sendall(resp_ok)

    monkeypatch.setattr("camara_base.sd.InputStream", FakeMic)
    hilo = threading.Thread(target=_simular_camara_audio, daemon=True)
    hilo.start()

    cam.alternar_hablar_micro()
    hilo.join(timeout=2.0)
    servidor.close()
    cam.cerrar_base()

    # Secuencia esperada: Login (1000), Claim (1434), Start (1430), Audio (1432 x2), Stop (1430)
    assert 1000 in codigos_recibidos
    assert 1434 in codigos_recibidos
    assert 1432 in codigos_recibidos
    assert codigos_recibidos[-1] == 1430


def test_camara_dvrip_fusion_doble_lente(monkeypatch):
    """Comprueba que _leer_ffmpeg une verticalmente las lentes 1 (arriba) y 0 (abajo)."""
    monkeypatch.setattr(CamaraDVRIP, "_iniciar_dvrip", lambda self: None)
    cfg = {
        "nombre": "Patio Dual",
        "ip": "127.0.0.1",
        "usuario": "admin",
        "password": "123",
        "puerto_netip": 34567,
        "canales": (0, 1),
    }
    cam = CamaraDVRIP(cfg, indice=0)

    # Simulamos que ya llegó un frame de la lente superior (canal 1) con valor 200
    lente_sup = np.full((config.ALTO_LENTE_DVRIP, config.ANCHO_CELDA, 3), 200, dtype=np.uint8)
    cam.ultima_lente[1] = lente_sup

    # Simulamos stdout de FFmpeg entregando 1 frame completo de la lente inferior (canal 0) con valor 50
    lente_inf_bytes = np.full((config.ALTO_LENTE_DVRIP, config.ANCHO_CELDA, 3), 50, dtype=np.uint8).tobytes()
    fake_proc = MagicMock()
    fake_proc.poll.side_effect = [None, 0]  # 1 iteración viva y luego termina
    fake_proc.stdout.read.side_effect = [lente_inf_bytes, b""]
    cam.procesos[0] = fake_proc

    cam._leer_ffmpeg(0)

    assert cam.frame is not None
    assert cam.frame.shape == (config.ALTO_CELDA, config.ANCHO_CELDA, 3)
    # Mitad superior debe valer 200 y mitad inferior 50
    assert int(cam.frame[0, 0, 0]) == 200
    assert int(cam.frame[config.ALTO_LENTE_DVRIP + 5, 0, 0]) == 50
    cam.cerrar()


def test_escritor_video_fallback_opencv_si_falla_ffmpeg(tmp_path, monkeypatch):
    """Verifica que si FFmpeg falla al arrancar, EscritorVideoH264 usa cv2.VideoWriter sin romperse."""
    monkeypatch.setattr(subprocess, "Popen", MagicMock(side_effect=FileNotFoundError("ffmpeg no encontrado")))
    ruta_mp4 = tmp_path / "fallback.mp4"

    writer = EscritorVideoH264(str(ruta_mp4), fps=10.0, ancho=320, alto=180, con_audio=False)
    assert writer.proceso is None
    assert writer.writer_opencv is not None

    frame = np.zeros((180, 320, 3), dtype=np.uint8)
    writer.write(frame)
    writer.release()
    assert ruta_mp4.exists()


def test_telegram_comandos_globales_estado_y_logs(tmp_path, monkeypatch):
    """Prueba comandos globales (/grabar, /luz, /estado, /logs) sobre múltiples cámaras."""
    mensajes = []
    monkeypatch.setattr(
        notificaciones,
        "enviar_mensaje_telegram",
        lambda txt, incluir_teclado=True: mensajes.append(txt),
    )

    ruta_log = tmp_path / "sistema.log"
    ruta_log.write_text("2026-11-18 19:00:00 [INFO] Sistema iniciado correctamente\n", encoding="utf-8")
    monkeypatch.setattr(notificaciones, "RUTA_LOG", str(ruta_log))

    c1 = MagicMock(nombre="Cam 1", grabando=False, deteccion_activa=True, modo_luz_actual="AUTO")
    c2 = MagicMock(nombre="Cam 2", grabando=False, deteccion_activa=False, modo_luz_actual="IR")
    camaras = [c1, c2]

    # /grabar sin número activa grabación en TODAS las cámaras
    notificaciones._procesar_comando("/grabar", camaras)
    c1.alternar_grabacion.assert_called_once()
    c2.alternar_grabacion.assert_called_once()

    # /luz sin número cicla AUTO -> BLANCA en c1 e IR -> AUTO en c2
    notificaciones._procesar_comando("/luz", camaras)
    c1.cambiar_luz_led.assert_called_with("BLANCA")
    c2.cambiar_luz_led.assert_called_with("AUTO")

    # /estado y /logs devuelven texto estructurado
    notificaciones._procesar_comando("/estado", camaras)
    assert "ESTADO DEL SISTEMA" in mensajes[-1]

    notificaciones._procesar_comando("/logs", camaras)
    assert "Sistema iniciado correctamente" in mensajes[-1]


def test_raton_seleccion_y_ampliacion_en_main(monkeypatch):
    """Comprueba que 1 clic selecciona celda y doble clic amplía en mosaico 2x2."""
    monkeypatch.setattr(config, "MODO_MOSAICO", 4)
    monkeypatch.setattr(main, "seleccionada", 0)
    monkeypatch.setattr(main, "vista_ampliada", False)

    camaras_falsas = [MagicMock(), MagicMock(), MagicMock(), MagicMock()]

    # Clic simple en la celda inferior derecha (x=700, y=400 -> índice 3)
    main.al_hacer_clic_camaras(cv2.EVENT_LBUTTONDOWN, 700, 400, camaras_falsas)
    assert main.seleccionada == 3
    assert main.vista_ampliada is False

    # Doble clic en la celda superior derecha (x=700, y=50 -> índice 1)
    main.al_hacer_clic_camaras(cv2.EVENT_LBUTTONDBLCLK, 700, 50, camaras_falsas)
    assert main.seleccionada == 1
    assert main.vista_ampliada is True

    # Segundo doble clic vuelve al mosaico
    main.al_hacer_clic_camaras(cv2.EVENT_LBUTTONDBLCLK, 700, 50, camaras_falsas)
    assert main.vista_ampliada is False
