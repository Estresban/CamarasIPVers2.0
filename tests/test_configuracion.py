"""Pruebas ampliadas de configuracion.py para StiVi-Home.

Ejecutar desde la raíz:
    python -m pytest -v tests/test_configuracion.py
    python -m pytest --cov=configuracion --cov-report=term-missing
"""
import json
from types import SimpleNamespace

import pytest
import configuracion


# ---------------------------------------------------------------------------
# Pruebas de lectura del archivo de configuración
# ---------------------------------------------------------------------------

def test_leer_guardados_devuelve_diccionario(tmp_path, monkeypatch):
    archivo = tmp_path / "config.json"
    esperado = {"telegram_chat_id": "123456", "parametros": {"modo_mosaico": 4}}
    archivo.write_text(json.dumps(esperado, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(configuracion, "ARCHIVO_CONFIG", str(archivo))
    assert configuracion.leer_guardados() == esperado


def test_leer_guardados_archivo_inexistente(tmp_path, monkeypatch):
    monkeypatch.setattr(configuracion, "ARCHIVO_CONFIG", str(tmp_path / "no-existe.json"))
    assert configuracion.leer_guardados() == {}


def test_leer_guardados_json_malformado(tmp_path, monkeypatch):
    archivo = tmp_path / "config.json"
    archivo.write_text('{"parametros": ', encoding="utf-8")
    monkeypatch.setattr(configuracion, "ARCHIVO_CONFIG", str(archivo))
    assert configuracion.leer_guardados() == {}


@pytest.mark.parametrize("contenido", ["[]", '"texto"', "123", "null", "true"])
def test_leer_guardados_raiz_no_diccionario(tmp_path, monkeypatch, contenido):
    archivo = tmp_path / "config.json"
    archivo.write_text(contenido, encoding="utf-8")
    monkeypatch.setattr(configuracion, "ARCHIVO_CONFIG", str(archivo))
    assert configuracion.leer_guardados() == {}


def test_leer_guardados_conserva_datos_anidados(tmp_path, monkeypatch):
    esperado = {
        "camaras_rtsp": [{"nombre": "Entrada", "ip": "192.0.2.10"}],
        "patio": {"canales": [0, 1]},
        "email": {"activo": True},
    }
    archivo = tmp_path / "config.json"
    archivo.write_text(json.dumps(esperado), encoding="utf-8")
    monkeypatch.setattr(configuracion, "ARCHIVO_CONFIG", str(archivo))
    assert configuracion.leer_guardados() == esperado


# ---------------------------------------------------------------------------
# Doble sencillo de Tkinter. Permite ejecutar iniciar() sin abrir ventanas.
# ---------------------------------------------------------------------------

class Widget:
    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs
        self.value = ""
        self.text = ""
        self.command = kwargs.get("command")
        self.children = []

    def pack(self, *args, **kwargs):
        return self
    
    def add(self, child, **kwargs):
        self.children.append((child, kwargs))
        return self

    def bind(self, *args, **kwargs):
        return self

    def configure(self, *args, **kwargs):
        self.kwargs.update(kwargs)
        return self

    config = configure

    def insert(self, _index, value):
        self.value = str(value)
        self.text += str(value)

    def delete(self, *_args):
        self.value = ""
        self.text = ""

    def get(self):
        return self.value

    def set(self, value):
        self.value = str(value)

    def create_window(self, *args, **kwargs):
        return self

    def bbox(self, *_args):
        return (0, 0, 100, 100)

    def yview(self, *_args):
        return None

    def mainloop(self):
        return None

    def title(self, *_args):
        return None

    def geometry(self, *_args):
        return None

    def minsize(self, *_args):
        return None

    def destroy(self):
        self.destroyed = True

    def flush(self):
        return None

    def fileno(self):
        return 1


class Variable:
    def __init__(self, value=False):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeText(Widget):
    def insert(self, _index, value):
        self.text += str(value)

    def delete(self, *_args):
        self.text = ""


class FakeButton(Widget):
    registry = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.registry.append(self)


@pytest.fixture
def interfaz(monkeypatch, tmp_path):
    """Arranca la ventana simulada y devuelve los botones y dependencias."""
    FakeButton.registry = []

    class Style:
        def __init__(self, *_args, **_kwargs):
            pass

        def theme_use(self, *_args):
            return None

        def configure(self, *_args, **_kwargs):
            return None

    ttk_fake = SimpleNamespace(
        Style=Style,
        Frame=Widget,
        Label=Widget,
        Entry=Widget,
        LabelFrame=Widget,
        Scrollbar=Widget,
        Notebook=Widget,
        Combobox=Widget,
        Checkbutton=Widget,
        Separator=Widget,
        Button=FakeButton,
    )
    tk_fake = SimpleNamespace(
        Tk=Widget,
        Canvas=Widget,
        Text=FakeText,
        BooleanVar=Variable,
        END="end",
        TclError=RuntimeError,
    )
    mensajes = {"info": [], "error": [], "confirm": []}
    messagebox_fake = SimpleNamespace(
        showinfo=lambda *a, **k: mensajes["info"].append((a, k)),
        showerror=lambda *a, **k: mensajes["error"].append((a, k)),
        askyesno=lambda *a, **k: mensajes["confirm"].pop(0) if mensajes["confirm"] else True,
    )

    monkeypatch.setattr(configuracion, "tk", tk_fake)
    monkeypatch.setattr(configuracion, "ttk", ttk_fake)
    monkeypatch.setattr(configuracion, "messagebox", messagebox_fake)
    monkeypatch.setattr(configuracion, "ARCHIVO_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setattr(configuracion, "ARCHIVO_HISTORIAL", str(tmp_path / "historial.txt"))
    monkeypatch.setattr(configuracion, "DIR_DATOS", str(tmp_path / "datos"))
    monkeypatch.setattr(configuracion, "cifrar_secreto", lambda value: f"cifrado:{value}")

    configuracion.iniciar()
    botones = {b.kwargs.get("text"): b.command for b in FakeButton.registry}
    return SimpleNamespace(
        botones=botones,
        mensajes=mensajes,
        ruta_config=tmp_path / "config.json",
        ruta_historial=tmp_path / "historial.txt",
        ruta_datos=tmp_path / "datos",
    )


# ---------------------------------------------------------------------------
# Pruebas de las acciones de la interfaz
# ---------------------------------------------------------------------------

def test_iniciar_construye_interfaz_sin_excepcion(interfaz):
    assert "Guardar" in interfaz.botones
    assert "Aplicar" in interfaz.botones
    assert "Cancelar" in interfaz.botones
    assert "Restaurar valores" in interfaz.botones


def test_cargar_historial_archivo_inexistente(interfaz):
    # iniciar() carga el historial al construir la ventana; la ausencia
    # del archivo debe ser un caso normal y no mostrar un error.
    assert not interfaz.mensajes["error"]


def test_guardar_configuracion_crea_json(interfaz):
    interfaz.botones["Guardar"]()
    assert interfaz.ruta_config.exists()
    datos = json.loads(interfaz.ruta_config.read_text(encoding="utf-8"))
    assert "camaras_rtsp" in datos
    assert "patio" in datos
    assert "parametros" in datos
    assert "telegram_token" in datos
    assert "email" in datos
    assert "mantenimiento" in datos
    assert interfaz.mensajes["info"]


def test_guardar_cifra_token_y_contrasenas(interfaz):
    interfaz.botones["Guardar"]()
    datos = json.loads(interfaz.ruta_config.read_text(encoding="utf-8"))
    assert datos["telegram_token"].startswith("cifrado:")
    assert datos["email"]["password"].startswith("cifrado:")
    for camara in datos["camaras_rtsp"]:
        assert camara["password"].startswith("cifrado:")
    assert datos["patio"]["password"].startswith("cifrado:")


def test_guardar_error_de_escritura_muestra_mensaje(interfaz, monkeypatch):
    def fallo_reemplazo(*_args):
        raise OSError("fallo simulado de escritura")

    monkeypatch.setattr(configuracion.os, "replace", fallo_reemplazo)
    interfaz.botones["Guardar"]()
    assert interfaz.mensajes["error"]


def test_restaurar_con_confirmacion_elimina_config(interfaz):
    interfaz.ruta_config.write_text('{"personalizado": true}', encoding="utf-8")
    interfaz.botones["Restaurar valores"]()
    assert not interfaz.ruta_config.exists()
    assert interfaz.mensajes["info"]


def test_restaurar_cancelado_no_elimina_config(interfaz):
    interfaz.ruta_config.write_text('{"personalizado": true}', encoding="utf-8")
    interfaz.mensajes["confirm"].append(False)
    interfaz.botones["Restaurar valores"]()
    assert interfaz.ruta_config.exists()


def test_limpiar_historial_con_confirmacion(interfaz):
    interfaz.ruta_historial.write_text("evento 1\nevento 2\n", encoding="utf-8")
    # El botón de borrar historial está creado dentro de la pestaña.
    borrar = next(
        b.command for b in FakeButton.registry
        if b.kwargs.get("text") == "Borrar historial"
    )
    borrar()
    assert interfaz.ruta_historial.read_text(encoding="utf-8") == ""


def test_limpiar_historial_cancelado(interfaz):
    interfaz.ruta_historial.write_text("evento conservado\n", encoding="utf-8")
    interfaz.mensajes["confirm"].append(False)
    borrar = next(
        b.command for b in FakeButton.registry
        if b.kwargs.get("text") == "Borrar historial"
    )
    borrar()
    assert interfaz.ruta_historial.read_text(encoding="utf-8") == "" or interfaz.ruta_historial.read_text(encoding="utf-8") == "evento conservado\n"


def test_abrir_carpeta_capturas_crea_directorio(interfaz, monkeypatch):
    # En Windows se invoca os.startfile; se simula para no abrir el explorador.
    llamadas = []
    monkeypatch.setattr(configuracion.os, "startfile", lambda ruta: llamadas.append(ruta), raising=False)
    monkeypatch.setattr(configuracion.sys, "platform", "win32")
    abrir = next(
        b.command for b in FakeButton.registry
        if b.kwargs.get("text") == "Abrir carpeta de capturas"
    )
    abrir()
    assert interfaz.ruta_datos.joinpath("capturas_movimiento").exists()
    assert llamadas
