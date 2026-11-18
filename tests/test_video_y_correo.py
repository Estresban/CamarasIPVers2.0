import time
from unittest.mock import MagicMock
import numpy as np

import config
import correo_alertas
from escritor_video import EscritorVideoH264
import main


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
