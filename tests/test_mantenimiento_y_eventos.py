from datetime import datetime as real_datetime
import os
import time
from unittest.mock import MagicMock
import numpy as np
import pytest

import mantenimiento
from mantenimiento import GestorMantenimiento
from grabacion_eventos import GrabadorEventos


def test_horario_franja_normal_y_nocturna(monkeypatch):
    gestor = GestorMantenimiento([])

    def fijar_hora(h, m):
        fake_dt = MagicMock()
        fake_dt.now.return_value = real_datetime(2026, 11, 18, h, m)
        fake_dt.strptime = real_datetime.strptime
        monkeypatch.setattr(mantenimiento, "datetime", fake_dt)

    # Caso 1: Franja nocturna (23:30 a 07:00) a las 02:15 -> Debe estar ARMADO
    fijar_hora(2, 15)
    assert gestor._esta_en_horario("23:30", "07:00") is True

    # Caso 2: Franja nocturna (23:30 a 07:00) a las 14:00 -> Debe estar DESARMADO
    fijar_hora(14, 0)
    assert gestor._esta_en_horario("23:30", "07:00") is False

    # Caso 3: Franja diurna (08:00 a 18:00) a las 12:30 -> Debe estar ARMADO
    fijar_hora(12, 30)
    assert gestor._esta_en_horario("08:00", "18:00") is True


def test_limpieza_circular_disco_borra_mas_antiguos(tmp_path, monkeypatch):
    carpeta_grab = tmp_path / "grabaciones"
    carpeta_grab.mkdir()

    monkeypatch.setattr(mantenimiento, "CARPETA_GRABACIONES", str(carpeta_grab))
    monkeypatch.setattr(mantenimiento, "CARPETA_CAPTURAS", str(tmp_path / "vacia1"))
    monkeypatch.setattr(mantenimiento, "CARPETA_FOTOGRAMAS", str(tmp_path / "vacia2"))

    # Creamos 3 archivos de 1 MB cada uno (total = 3.0 MB)
    f_viejo = carpeta_grab / "cam1_viejo.mp4"
    f_medio = carpeta_grab / "cam1_medio.mp4"
    f_nuevo = carpeta_grab / "cam1_nuevo.mp4"

    for f in (f_viejo, f_medio, f_nuevo):
        f.write_bytes(b"0" * (1024 * 1024))

    ahora = time.time()
    os.utime(f_viejo, (ahora - 3600, ahora - 3600))  # Hace 1 hora
    os.utime(f_medio, (ahora - 1800, ahora - 1800))  # Hace 30 min
    os.utime(f_nuevo, (ahora - 10, ahora - 10))      # Hace 10 seg (protegido < 120s)

    gestor = GestorMantenimiento([])
    # Límite de 0.0025 GB (~2.56 MB; objetivo 90% = ~2.30 MB): basta con borrar el más antiguo
    gestor._limpiar_disco_si_excede(max_gb=0.0025)

    assert not f_viejo.exists()
    assert f_medio.exists()
    assert f_nuevo.exists()


def test_grabador_eventos_prebuffer():
    grabador = GrabadorEventos("Camara Test", seg_prebuffer=2, seg_postevento=5, fps=10.0)
    assert grabador.prebuffer.maxlen == 20

    grabador.alternar()
    assert grabador.activa is True

    frame_negro = np.zeros((360, 640, 3), dtype=np.uint8)
    for _ in range(25):
        grabador.procesar_frame(frame_negro, hay_movimiento=False)

    # El búfer circular nunca debe superar su capacidad máxima de 20 frames
    assert len(grabador.prebuffer) == 20
    grabador.detener_y_limpiar()
