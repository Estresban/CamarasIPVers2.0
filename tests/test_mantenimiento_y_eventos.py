from datetime import datetime as real_datetime
import os
import time
from unittest.mock import MagicMock, patch
import numpy as np
import json
import pytest

import mantenimiento
from mantenimiento import GestorMantenimiento
from grabacion_eventos import GrabadorEventos

import json



def test_mantenimiento_iniciar_cerrar_y_leer_reglas(tmp_path):
    cfg_file = tmp_path / "config.json"

    with patch("mantenimiento.RUTA_CONFIG_JSON", str(cfg_file)):
        gm = GestorMantenimiento([])
        assert gm._mtime_config == 0.0

        # JSON corrupto -> devuelve valores por defecto sin fallar
        cfg_file.write_text("{corrupto", encoding="utf-8")
        reglas_def = gm._leer_reglas()
        assert reglas_def["max_gb"] == 50.0
        assert reglas_def["horario_activo"] is False

        # JSON válido
        cfg_file.write_text(
            json.dumps({
                "mantenimiento": {
                    "max_gb": 10.5,
                    "horario_activo": True,
                    "hora_inicio": "22:00",
                    "hora_fin": "06:30",
                }
            }),
            encoding="utf-8",
        )
        assert gm._obtener_mtime_config() > 0.0
        reglas = gm._leer_reglas()
        assert reglas["max_gb"] == 10.5
        assert reglas["horario_activo"] is True
        assert reglas["hora_inicio"] == "22:00"

    with patch("mantenimiento.threading.Thread") as mock_th:
        gm.iniciar()
        assert mock_th.called
    gm.cerrar()
    assert gm._evento_detener.is_set()


def test_mantenimiento_limpieza_disco_circular(tmp_path):
    dir_grab = tmp_path / "grabaciones"
    dir_cap = tmp_path / "capturas"
    dir_grab.mkdir()
    dir_cap.mkdir()

    ahora = time.time()

    # Archivo 1: muy antiguo (hace 2 horas), 600 bytes -> debe borrarse primero
    f_viejo = dir_grab / "viejo.mp4"
    f_viejo.write_bytes(b"0" * 600)
    os.utime(f_viejo, (ahora - 7200, ahora - 7200))

    # Archivo 2: antiguo (hace 1 hora), 600 bytes -> debe borrarse hasta bajar del 90%
    f_medio = dir_cap / "medio.jpg"
    f_medio.write_bytes(b"0" * 600)
    os.utime(f_medio, (ahora - 3600, ahora - 3600))

    # Archivo 3: recién creado (< 120 seg), 600 bytes -> NO debe borrarse aunque exceda límite
    f_reciente = dir_grab / "grabando_ahora.mp4"
    f_reciente.write_bytes(b"0" * 600)

    # Archivo 4: extensión ignorada (.txt) -> NO debe borrarse
    f_txt = dir_grab / "notas.txt"
    f_txt.write_bytes(b"0" * 1000)
    os.utime(f_txt, (ahora - 9000, ahora - 9000))

    gm = GestorMantenimiento([])
    # Límite de 1000 bytes (en GB): total multimedia = 1800 bytes > 1000 bytes
    limite_gb = 1000 / (1024 ** 3)

    with patch("mantenimiento.CARPETA_GRABACIONES", str(dir_grab)), \
         patch("mantenimiento.CARPETA_CAPTURAS", str(dir_cap)), \
         patch("mantenimiento.CARPETA_FOTOGRAMAS", str(tmp_path / "no_existe")):
        gm._limpiar_disco_si_excede(0)  # No hace nada si <= 0
        gm._limpiar_disco_si_excede(limite_gb)

    assert not f_viejo.exists()
    assert not f_medio.exists()
    assert f_reciente.exists()
    assert f_txt.exists()


def test_mantenimiento_horarios_y_armado():
    cam = MagicMock()
    cam.deteccion_activa = False
    cam.grabador_eventos.activa = False
    gm = GestorMantenimiento([cam])

    # Formato de hora inválido
    assert gm._esta_en_horario("invalido", "07:00") is False

    # Franja diurna (08:00 - 20:00) y nocturna cruzando medianoche (23:30 - 07:00)
    class FakeDateTime:
        hora_actual = None

        @classmethod
        def now(cls):
            m = MagicMock()
            m.time.return_value = cls.hora_actual
            return m

        @staticmethod
        def strptime(s, fmt):
            from datetime import datetime as dt_real
            return dt_real.strptime(s, fmt)

    from datetime import time as dt_time

    with patch("mantenimiento.datetime", FakeDateTime):
        FakeDateTime.hora_actual = dt_time(14, 0)
        assert gm._esta_en_horario("08:00", "20:00") is True
        assert gm._esta_en_horario("23:30", "07:00") is False

        FakeDateTime.hora_actual = dt_time(2, 0)
        assert gm._esta_en_horario("23:30", "07:00") is True

        # Etiqueta visual activa
        with patch.object(gm, "_leer_reglas", return_value={
            "horario_activo": True, "hora_inicio": "23:30", "hora_fin": "07:00"
        }):
            assert "ARMADO" in gm.obtener_estado_visual()

    # Armar y desarmar sistema
    with patch("mantenimiento.threading.Thread") as mock_th, \
         patch("mantenimiento.notificaciones.enviar_mensaje_telegram") as mock_tg:
        mock_th.side_effect = lambda target, args=(), daemon=True: MagicMock(start=lambda: target(*args))
        gm._aplicar_estado_armado(True)
        assert cam.alternar_deteccion.called
        assert cam.alternar_grab_movimiento.called
        assert mock_tg.called

        cam.deteccion_activa = True
        cam.grabador_eventos.activa = True
        gm._aplicar_estado_armado(False)
        assert cam.alternar_deteccion.call_count == 2
        assert cam.alternar_grab_movimiento.call_count == 2


def test_mantenimiento_bucle_principal():
    cam = MagicMock()
    cam.deteccion_activa = False
    cam.grabador_eventos.activa = False
    gm = GestorMantenimiento([cam])
    gm._mtime_config = 100.0
    gm._ultimo_chequeo_disco = 0.0

    llamadas_wait = {"n": 0}

    def simular_wait(timeout=None):
        llamadas_wait["n"] += 1
        if llamadas_wait["n"] >= 3:
            gm.cerrar()
            return True
        return False

    reglas_iter = [
        {"max_gb": 50.0, "horario_activo": True, "hora_inicio": "00:00", "hora_fin": "23:59"},
        {"max_gb": 50.0, "horario_activo": False, "hora_inicio": "00:00", "hora_fin": "23:59"},
    ]

    with patch.object(gm._evento_detener, "wait", side_effect=simular_wait), \
         patch.object(gm, "_obtener_mtime_config", return_value=200.0), \
         patch("mantenimiento.config.recargar_configuracion", return_value=True) as mock_recarga, \
         patch.object(gm, "_leer_reglas", side_effect=reglas_iter), \
         patch.object(gm, "_esta_en_horario", return_value=True), \
         patch.object(gm, "_aplicar_estado_armado") as mock_armar, \
         patch.object(gm, "_limpiar_disco_si_excede") as mock_limpiar:
        gm._bucle_mantenimiento()

    assert mock_recarga.called
    assert mock_armar.called
    assert mock_limpiar.called



#######################################################
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
