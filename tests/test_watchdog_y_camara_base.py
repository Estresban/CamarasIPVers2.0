import time
from unittest.mock import MagicMock, patch
import cv2
import numpy as np

import config
from camara_base import CamaraBase
from watchdog import WatchdogCamaras


def _cfg_camara_prueba():
    return {
        "nombre": "Camara Prueba",
        "ip": "127.0.0.1",
        "usuario": "admin",
        "password": "123",
        "puerto_netip": 34567,
    }


def test_hash_xmeye_consistente():
    h1 = config.hash_xmeye("admin123")
    h2 = config.hash_xmeye("admin123")
    assert len(h1) == 8
    assert h1 == h2
    assert h1 != config.hash_xmeye("otra_clave")


def test_camara_base_zoom_digital():
    cam = CamaraBase(_cfg_camara_prueba(), indice=0)
    frame = np.zeros((360, 640, 3), dtype=np.uint8)

    # Sin zoom (1.0x) devuelve el mismo tamaño
    sin_zoom = cam._aplicar_zoom_digital(frame)
    assert sin_zoom.shape == (360, 640, 3)

    # Con zoom 2.0x mantiene las dimensiones de celda y limita el máximo a 4.0x
    cam.cambiar_zoom(1.0)
    assert cam.zoom_digital == 2.0
    con_zoom = cam._aplicar_zoom_digital(frame)
    assert con_zoom.shape == (360, 640, 3)

    cam.cambiar_zoom(10.0)
    assert cam.zoom_digital == 4.0
    cam.cerrar_base()


def test_camara_base_deteccion_movimiento(tmp_path, monkeypatch):
    monkeypatch.setattr("camara_base.CARPETA_CAPTURAS", str(tmp_path))
    monkeypatch.setattr("camara_base.enviar_alerta_movimiento", MagicMock())
    monkeypatch.setattr("camara_base.enviar_alerta_correo_rtsp", MagicMock())

    cam = CamaraBase(_cfg_camara_prueba(), indice=0)
    cam.alternar_deteccion()
    assert cam.deteccion_activa is True

    # Primer frame: inicializa el fondo gris, no debe disparar alerta
    fondo = np.zeros((360, 640, 3), dtype=np.uint8)
    assert cam._detectar_movimiento(fondo) is False

    # Segundo frame idéntico: sin movimiento
    assert cam._detectar_movimiento(fondo.copy()) is False

    # Tercer frame con un rectángulo blanco grande: debe detectar movimiento
    frame_mov = fondo.copy()
    cv2.rectangle(frame_mov, (100, 100), (350, 300), (255, 255, 255), -1)
    assert cam._detectar_movimiento(frame_mov) is True
    cam.cerrar_base()


def test_watchdog_detecta_congelacion_y_reconecta():
    cam = MagicMock()
    cam.nombre = "Camara Congelada"
    cam.detener = False
    cam.frame = np.full((360, 640, 3), 120, dtype=np.uint8)

    wd = WatchdogCamaras([cam], timeout_seg=0.1, intervalo_revision=0.05, umbral_alerta_seg=60.0)
    firma = wd._firma_rapida(cam.frame)

    # Simulamos que la cámara lleva 1 segundo con la misma firma (congelada)
    wd._estado[0] = {
        "firma": firma,
        "ultimo_cambio": time.time() - 1.0,
        "reiniciando": False,
        "inicio_caida": time.time() - 1.0,
        "alerta_enviada": False,
    }

    # Ejecutamos una iteración controlada del bucle de vigilancia
    wd._evento_detener = MagicMock()
    wd._evento_detener.wait.side_effect = [False, True]  # Salta espera inicial y corta tras 1 ciclo
    wd._evento_detener.is_set.side_effect = [False, True]

    wd._bucle_vigilancia()
    time.sleep(0.05)  # Damos margen al hilo daemon de forzar_reconexion
    cam.forzar_reconexion.assert_called_once()
    



def test_watchdog_firma_rapida():
    wd = WatchdogCamaras([])
    assert wd._firma_rapida(None) is None
    frame = np.ones((64, 64, 3), dtype=np.uint8) * 10
    assert wd._firma_rapida(frame) == 120  # 2x2x3 * 10


def test_watchdog_ciclo_completo_caida_alerta_y_recuperacion():
    cam_activa = MagicMock()
    cam_activa.nombre = "Cam1"
    cam_activa.detener = False
    frame_a = np.zeros((64, 64, 3), dtype=np.uint8)
    frame_b = np.ones((64, 64, 3), dtype=np.uint8) * 255
    cam_activa.frame = frame_a

    cam_detenida = MagicMock()
    cam_detenida.detener = True

    wd = WatchdogCamaras(
        [cam_activa, cam_detenida],
        timeout_seg=5.0,
        intervalo_revision=1.0,
        umbral_alerta_seg=60.0,
    )

    tiempos = [100.0, 106.0, 170.0, 230.0]

    def simular_tiempo():
        if len(tiempos) == 1:
            cam_activa.frame = frame_b
        return tiempos.pop(0) if tiempos else 235.0

    llamadas_wait = {"n": 0}

    def simular_wait(timeout=None):
        llamadas_wait["n"] += 1
        if llamadas_wait["n"] >= 5:
            wd.cerrar()  # Activa el evento real para romper el while
            return True
        return False

    with patch("watchdog.time.time", side_effect=simular_tiempo), \
         patch.object(wd._evento_detener, "wait", side_effect=simular_wait), \
         patch("watchdog.notificaciones.alertas_activas", True), \
         patch("watchdog.notificaciones.enviar_mensaje_telegram") as mock_tg, \
         patch("watchdog.threading.Thread") as mock_thread:

        mock_thread.side_effect = lambda target, args=(), daemon=True: MagicMock(
            start=lambda: target(*args)
        )
        wd._bucle_vigilancia()

    assert cam_activa.forzar_reconexion.called
    assert mock_tg.call_count == 2
    assert "FALLO DE SALUD" in mock_tg.call_args_list[0][0][0]
    assert "CÁMARA RECUPERADA" in mock_tg.call_args_list[1][0][0]



def test_watchdog_iniciar_y_cerrar():
    wd = WatchdogCamaras([])
    with patch("watchdog.threading.Thread") as mock_th:
        wd.iniciar()
        assert mock_th.called
    wd.cerrar()
    assert wd._evento_detener.is_set()

