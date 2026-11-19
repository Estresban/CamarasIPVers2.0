import struct
from unittest.mock import MagicMock, patch
import numpy as np
from camara_base import CamaraBase


CFG_BASE = {
    "nombre": "Camara Base",
    "ip": "192.168.1.99",
    "usuario": "admin",
    "password": "123",
    "puerto_netip": 34567,
}


def test_camara_base_imagenes_grabacion_audio_y_controles():
    cam = CamaraBase(CFG_BASE, 0)
    frame = np.zeros((360, 640, 3), dtype=np.uint8)

    # 1. Excepción en _guardar_imagen_async (98-99) y capturar_fotograma_manual (229)
    with patch("camara_base.threading.Thread") as mock_th, \
         patch("camara_base.cv2.imwrite", side_effect=OSError("Disco lleno")):
        mock_th.side_effect = lambda target, daemon=True: MagicMock(start=target)
        cam.frame = frame
        cam.capturar_fotograma_manual()

    # 2. _gestionar_grabacion: rotación de bloque (148-150) y parada de grabación (140-141)
    writer1 = MagicMock()
    writer2 = MagicMock()
    with patch("camara_base.EscritorVideoH264", side_effect=[writer1, writer2]), \
         patch("camara_base.config.MINUTOS_POR_BLOQUE_VIDEO", 1), \
         patch("camara_base.time.time", side_effect=[100.0, 200.0]):
        cam.grabando = True
        cam._gestionar_grabacion(frame)   # Crea writer1 en t=100
        cam._gestionar_grabacion(frame)   # Rota a writer2 en t=200
        assert writer1.release.called

        # _procesar_nuevo_audio con datos válidos (161, 166)
        cam._procesar_nuevo_audio(np.array([10, 20], dtype=np.int16))
        assert writer2.write_audio.called

        # Al desactivar grabación dentro del pipeline libera writer2 (140-141)
        cam.grabando = False
        cam._gestionar_grabacion(frame)
        assert writer2.release.called

    # 3. Controles de usuario y métodos base (203, 207, 213-226)
    cam.ir_a_preset(1)
    cam.guardar_preset(1)

    cam.deteccion_activa = True
    cam.movimiento_detectado = True
    cam.alternar_deteccion()
    assert cam.movimiento_detectado is False

    cam.grabando = True
    cam.video_writer = MagicMock()
    cam.alternar_grabacion()
    assert cam.video_writer is None

    # Activar grab_movimiento cuando detección está apagada la enciende automáticamente (224-226)
    cam.deteccion_activa = False
    with patch.object(cam.grabador_eventos, "alternar", return_value=True):
        cam.alternar_grab_movimiento()
        assert cam.deteccion_activa is True


def test_camara_base_netip_luz_y_microfono_bidireccional():
    cam = CamaraBase(CFG_BASE, 0)

    # 1. cambiar_luz_led con lock ocupado (262) y con error de socket (284-285)
    with patch("camara_base.threading.Thread") as mock_th:
        mock_th.side_effect = lambda target, daemon=True: MagicMock(start=target)
        cam.lock_red.acquire()
        cam.cambiar_luz_led("BLANCA")
        cam.lock_red.release()

        with patch("camara_base.socket.socket", side_effect=OSError("Red inaccesible")):
            cam.cambiar_luz_led("IR")

    # 2. alternar_hablar_micro encendido y apagado (300, 305-306)
    with patch("camara_base.threading.Thread"):
        cam.alternar_hablar_micro()
        assert cam.hablando_micro is True
        cam.alternar_hablar_micro()
        assert cam.hablando_micro is False

    # 3. _bucle_enviar_voz completo: login NetIP, Claim/Start, envío de paquete audio y Stop (312-383)
    sock_mock = MagicMock()
    # Respuesta de login NetIP con SessionID = 0x12345678
    resp_login = b"\xff\x00\x00\x00" + struct.pack("<I", 0x12345678) + b"\x00" * 16
    sock_mock.recv.side_effect = [resp_login, b"ok_claim", b"ok_start", b"ok_stop"]

    mic_stream = MagicMock()
    pcm_chunk = np.zeros((320, 1), dtype=np.int16)

    def leer_un_paquete_y_parar(_n):
        cam.hablando_micro = False  # Detiene el bucle tras enviar 1 paquete de voz
        return pcm_chunk, False

    mic_stream.__enter__.return_value.read.side_effect = leer_un_paquete_y_parar

    cam.hablando_micro = True
    with patch("camara_base.socket.socket", return_value=sock_mock), \
         patch("camara_base.sd.InputStream", return_value=mic_stream):
        cam._bucle_enviar_voz()

    assert sock_mock.sendall.call_count == 5  # Login + Claim + Start + Audio + Stop
    assert sock_mock.close.called


def test_camara_base_cerrar_con_writer_activo():
    cam = CamaraBase(CFG_BASE, 0)
    writer_mock = MagicMock()
    cam.video_writer = writer_mock

    # Cubre la liberación final en cerrar_base (428)
    cam.cerrar_base()
    assert writer_mock.release.called
    assert cam.video_writer is None
    

def test_camara_base_ultimas_10_lineas():
    cam = CamaraBase(CFG_BASE, 0)

    # 1. _procesar_nuevo_audio con None o vacío (161) y alternar_captura_auto (229)
    cam._procesar_nuevo_audio(None)
    cam._procesar_nuevo_audio(b"")
    assert cam.captura_auto_activa is False
    cam.alternar_captura_auto()
    assert cam.captura_auto_activa is True

    # 2. _bucle_enviar_voz con lock_red ocupado -> cancela hablando_micro (305-306)
    cam.hablando_micro = True
    cam.lock_red.acquire()
    cam._bucle_enviar_voz()
    cam.lock_red.release()
    assert cam.hablando_micro is False

    # 3. _bucle_enviar_voz con error en mic.read() y error al enviar Stop en finally (350-352, 368-369)
    sock_mock = MagicMock()
    resp_login = b"\xff\x00\x00\x00" + struct.pack("<I", 0x11223344) + b"\x00" * 16
    sock_mock.recv.side_effect = [resp_login, b"ok_claim", b"ok_start"]
    # El 4º sendall (el del Stop en el finally) lanza OSError
    sock_mock.sendall.side_effect = [None, None, None, OSError("Socket cerrado")]

    mic_err = MagicMock()
    mic_err.__enter__.return_value.read.side_effect = RuntimeError("Micrófono desconectado")

    cam.hablando_micro = True
    with patch("camara_base.socket.socket", return_value=sock_mock), \
         patch("camara_base.sd.InputStream", return_value=mic_err):
        cam._bucle_enviar_voz()
    assert cam.hablando_micro is False

    # 4. cerrar_base() liberando video_writer activo (428)
    writer = MagicMock()
    cam.video_writer = writer
    cam.cerrar_base()
    writer.release.assert_called_once()

