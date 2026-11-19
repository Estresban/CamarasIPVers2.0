"""Pruebas unitarias de configuracion.py para StiVi-Home.


Ejecuta desde la raíz del repositorio:
    python -m pytest -v tests/test_configuracion.py
"""

import json

import pytest

import configuracion


def test_leer_guardados_devuelve_diccionario(tmp_path, monkeypatch):
    """Lee correctamente un config.json válido."""
    archivo = tmp_path / "config.json"
    datos_esperados = {
        "telegram_chat_id": "123456",
        "parametros": {"modo_mosaico": 4},
    }
    archivo.write_text(
        json.dumps(datos_esperados, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(configuracion, "ARCHIVO_CONFIG", str(archivo))

    resultado = configuracion.leer_guardados()

    assert resultado == datos_esperados


def test_leer_guardados_archivo_inexistente_devuelve_diccionario_vacio(
    tmp_path, monkeypatch
):
    """Si config.json no existe, devuelve {} sin lanzar excepción."""
    archivo = tmp_path / "no_existe.json"
    monkeypatch.setattr(configuracion, "ARCHIVO_CONFIG", str(archivo))

    assert configuracion.leer_guardados() == {}


def test_leer_guardados_json_malformado_devuelve_diccionario_vacio(
    tmp_path, monkeypatch
):
    """Un JSON corrupto no debe detener la aplicación."""
    archivo = tmp_path / "config.json"
    archivo.write_text('{"parametros": ', encoding="utf-8")
    monkeypatch.setattr(configuracion, "ARCHIVO_CONFIG", str(archivo))

    assert configuracion.leer_guardados() == {}


@pytest.mark.parametrize("contenido", ["[]", '"texto"', "123", "null", "true"])
def test_leer_guardados_json_que_no_es_diccionario_devuelve_vacio(
    tmp_path, monkeypatch, contenido
):
    """La configuración raíz debe ser un objeto/diccionario JSON."""
    archivo = tmp_path / "config.json"
    archivo.write_text(contenido, encoding="utf-8")
    monkeypatch.setattr(configuracion, "ARCHIVO_CONFIG", str(archivo))

    assert configuracion.leer_guardados() == {}


def test_leer_guardados_conserva_valores_anidados(tmp_path, monkeypatch):
    """No altera listas, tuplas serializadas como listas ni objetos anidados."""
    archivo = tmp_path / "config.json"
    datos = {
        "camaras_rtsp": [{"nombre": "Camara prueba", "ip": "192.168.1.10"}],
        "patio": {"canales": [0, 1]},
        "email": {"activo": False},
    }
    archivo.write_text(json.dumps(datos), encoding="utf-8")
    monkeypatch.setattr(configuracion, "ARCHIVO_CONFIG", str(archivo))

    resultado = configuracion.leer_guardados()

    assert resultado["camaras_rtsp"][0]["ip"] == "192.168.1.10"
    assert resultado["patio"]["canales"] == [0, 1]
    assert resultado["email"]["activo"] is False
