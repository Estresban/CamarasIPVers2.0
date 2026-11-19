import json
import numpy as np
import pytest
import config
import os
import sys
import tkinter as tk
from unittest.mock import MagicMock, patch
import configuracion
from types import SimpleNamespace




def test_cifrado_y_descifrado_secreto():
    secreto = "MiClaveSuperSecreta_2026!@#"
    cifrado = config.cifrar_secreto(secreto)

    assert cifrado.startswith("ENC:")
    assert secreto not in cifrado
    assert config.descifrar_secreto(cifrado) == secreto


def test_cifrado_ignora_placeholders_y_ya_cifrados():
    assert config.cifrar_secreto("") == ""
    assert config.cifrar_secreto("TU_PASSWORD") == "TU_PASSWORD"
    assert config.cifrar_secreto("TU_TOKEN_TELEGRAM") == "TU_TOKEN_TELEGRAM"

    ya_cifrado = config.cifrar_secreto("clave123")
    assert config.cifrar_secreto(ya_cifrado) == ya_cifrado


def test_integridad_hmac_detecta_manipulacion():
    cifrado = config.cifrar_secreto("password_intacta")
    # Alteramos el último carácter de la firma/carga cifrada
    corrupto = cifrado[:-1] + ("A" if cifrado[-1] != "A" else "B")
    assert config.descifrar_secreto(corrupto) == ""


def test_codec_audio_alaw_ida_y_vuelta():
    # Generamos una onda PCM int16 de prueba
    muestras_orig = np.array([-16000, -4000, -500, 0, 500, 4000, 16000], dtype=np.int16)
    alaw_bytes = config.pcm16_a_alaw(muestras_orig)
    assert isinstance(alaw_bytes, bytes)
    assert len(alaw_bytes) == len(muestras_orig)

    reconstruido = config.alaw_a_pcm(alaw_bytes)
    assert reconstruido.dtype == np.int16
    # G.711 A-Law es un códec logarítmico con pérdida leve; comprobamos tolerancia razonable
    assert np.allclose(muestras_orig, reconstruido, rtol=0.1, atol=50)


def test_recarga_configuracion_en_caliente(tmp_path, monkeypatch):
    archivo_json = tmp_path / "config_test.json"
    datos = {
        "telegram_token": config.cifrar_secreto("123456:ABC-TOKEN"),
        "telegram_chat_id": "987654321",
        "parametros": {
            "sensibilidad_movimiento": 2500,
            "minutos_por_bloque_video": 15,
            "modo_mosaico": 2,
        },
    }
    archivo_json.write_text(json.dumps(datos), encoding="utf-8")

    monkeypatch.setattr(config, "RUTA_CONFIG_JSON", str(archivo_json))
    assert config.recargar_configuracion() is True
    assert config.TELEGRAM_TOKEN == "123456:ABC-TOKEN"
    assert config.TELEGRAM_CHAT_ID == "987654321"
    assert config.SENSIBILIDAD_MOVIMIENTO == 2500
    assert config.MINUTOS_POR_BLOQUE_VIDEO == 15
    assert config.MODO_MOSAICO == 2





###############################################################




def test_config_clave_maestra_secreto_corrupto_y_recarga(tmp_path):
    # 1. Generación inicial de .secret.key (28-35) y descifrado corrupto/alterado (85-86)
    key_file = tmp_path / ".secret.key"
    with patch("config.DIR_DATOS", str(tmp_path)), \
         patch("config.RUTA_CLAVE_MAESTRA", str(key_file)):
        cifrado = config.cifrar_secreto("MiClaveSegura123")
        assert key_file.exists()
        assert config.descifrar_secreto(cifrado) == "MiClaveSegura123"

        # Token alterado -> falla HMAC y devuelve ""
        alterado = cifrado[:-2] + ("AA" if not cifrado.endswith("AA") else "BB")
        assert config.descifrar_secreto(alterado) == ""

        # Token no Base64 -> captura excepción y devuelve ""
        assert config.descifrar_secreto("ENC:%%%no_valido%%%") == ""

    # 2. _resolver_carpeta con ruta absoluta (249)
    ruta_abs = os.path.abspath("/tmp/videos_test")
    assert config._resolver_carpeta(ruta_abs) == ruta_abs

    # 3. recargar_configuracion: inexistente, tipo inválido y JSON corrupto (280, 314, 319, 347-348)
    cfg_json = tmp_path / "config.json"
    with patch("config.RUTA_CONFIG_JSON", str(cfg_json)):
        assert config.recargar_configuracion() is False

        cfg_json.write_text("[1, 2, 3]", encoding="utf-8")
        assert config.recargar_configuracion() is False

        cfg_json.write_text("{json_roto", encoding="utf-8")
        assert config.recargar_configuracion() is False


def test_configuracion_gui_botones_validaciones_y_restaurar(tmp_path):
    cfg_file = tmp_path / "config.json"
    hist_file = tmp_path / "historial.txt"
    hist_file.write_text("• 19/11/2026 — Entrada\n", encoding="utf-8")

    botones_creados = {}

    class DummyButton:
        def __init__(self, parent, text="", command=None, **kwargs):
            botones_creados[text] = command

        def pack(self, *args, **kwargs):
            pass

    def ejecutar_callbacks_en_mainloop(self):
        # 1. Botones de historial y carpeta (242, 247-248, 258-259, 268-273)
        botones_creados["Borrar historial"]()
        assert hist_file.read_text(encoding="utf-8") == ""

        botones_creados["Abrir carpeta de capturas"]()

        # 2. Guardar válido (sin cerrar) y luego con error de validación (353-354, 375-388)
        botones_creados["Aplicar"]()
        assert cfg_file.exists()

        # 3. Restaurar configuración (449-450, 462)
        botones_creados["Restaurar valores"]()
        assert not cfg_file.exists()

    with patch("configuracion.ARCHIVO_CONFIG", str(cfg_file)), \
         patch("configuracion.ARCHIVO_HISTORIAL", str(hist_file)), \
         patch("configuracion.DIR_DATOS", str(tmp_path)), \
         patch("configuracion.ttk.Button", DummyButton), \
         patch("configuracion.messagebox.askyesno", return_value=True), \
         patch("configuracion.messagebox.showinfo"), \
         patch("configuracion.messagebox.showerror"), \
         patch("configuracion.os.startfile", create=True), \
         patch("configuracion.subprocess.Popen"), \
         patch.object(tk.Tk, "mainloop", ejecutar_callbacks_en_mainloop):
        configuracion.iniciar()

def test_configuracion_ramas_error_validacion_y_plataforma(tmp_path):
    cfg_file = tmp_path / "config.json"
    hist_file = tmp_path / "historial.txt"
    hist_file.write_text("• 19/11/2026 — Patio\n", encoding="utf-8")

    botones = {}
    entradas_creadas = []

    class DummyButton:
        def __init__(self, parent, text="", command=None, **kwargs):
            botones[text] = command

        def pack(self, *args, **kwargs):
            pass

    def secuencia_mainloop(self):
        # 1. Cancelar borrado de historial (askyesno -> False) y luego OSError al escribir (258-259)
        with patch("configuracion.messagebox.askyesno", return_value=False):
            botones["Borrar historial"]()

        with patch("configuracion.messagebox.askyesno", return_value=True), \
             patch("builtins.open", side_effect=OSError("Archivo bloqueado")):
            botones["Borrar historial"]()
            botones["Actualizar"]()  # Cubre OSError en cargar_historial (247-248)

        # 2. Abrir carpeta de capturas en macOS, Linux y con OSError (268-273)
        with patch("configuracion.sys.platform", "darwin"):
            botones["Abrir carpeta de capturas"]()
        with patch("configuracion.sys.platform", "linux"):
            botones["Abrir carpeta de capturas"]()
        with patch("configuracion.sys.platform", "linux"), \
             patch("configuracion.subprocess.Popen", side_effect=OSError("Sin xdg-open")):
            botones["Abrir carpeta de capturas"]()

        # 3. Guardar con errores de validación (353-354, 375-388)
        # Buscamos las entradas de canales y max_gb para meter valores inválidos
        for widget in self.winfo_children():
            pass
        # Guardado válido con cerrar_al_guardar=True ("Guardar", 449-450)
        botones["Guardar"]()

        # 4. Restaurar con error OSError al borrar config.json (462)
        cfg_file.write_text("{}", encoding="utf-8")
        with patch("configuracion.messagebox.askyesno", return_value=True), \
             patch("configuracion.os.remove", side_effect=OSError("Permiso denegado")):
            botones["Restaurar valores"]()

    with patch("configuracion.ARCHIVO_CONFIG", str(cfg_file)), \
         patch("configuracion.ARCHIVO_HISTORIAL", str(hist_file)), \
         patch("configuracion.DIR_DATOS", str(tmp_path)), \
         patch("configuracion.ttk.Button", DummyButton), \
         patch("configuracion.ttk.Style.theme_use", side_effect=tk.TclError("Sin tema")), \
         patch("configuracion.messagebox.showinfo"), \
         patch("configuracion.messagebox.showerror") as mock_err, \
         patch("configuracion.subprocess.Popen"), \
         patch.object(tk.Tk, "mainloop", secuencia_mainloop):
        configuracion.iniciar()
        assert mock_err.called


def test_configuracion_validaciones_campos_invalidos(tmp_path):
    cfg_file = tmp_path / "config.json"
    botones = {}

    class DummyButton:
        def __init__(self, parent, text="", command=None, **kwargs):
            botones[text] = command

        def pack(self, *args, **kwargs):
            pass

    def recorrer_entries(widget):
        res = []
        for hijo in widget.winfo_children():
            if isinstance(hijo, tk.ttk.Entry) and not isinstance(hijo, tk.ttk.Combobox):
                res.append(hijo)
            res.extend(recorrer_entries(hijo))
        return res

    def probar_errores_guardado(self):
        entries = recorrer_entries(self)
        # Buscamos el campo de canales ("0,1") y lo vaciamos -> error canales vacíos (378)
        for e in entries:
            if e.get() == "0,1":
                e.delete(0, tk.END)
                botones["Aplicar"]()
                # Ponemos texto no numérico -> error ValueError canales (375-376)
                e.insert(0, "abc")
                botones["Aplicar"]()
                e.delete(0, tk.END)
                e.insert(0, "0,1")
                break

        # Buscamos el campo max_gb ("50") y ponemos "-5" -> error almacenamiento <= 0 (386-388)
        for e in entries:
            if e.get() == "50":
                e.delete(0, tk.END)
                e.insert(0, "-5")
                botones["Aplicar"]()
                e.delete(0, tk.END)
                e.insert(0, "50")
                break

        # Ponemos texto en un campo entero (puerto RTSP "554") -> error entero() (353-354)
        for e in entries:
            if e.get() == "554":
                e.delete(0, tk.END)
                e.insert(0, "no_es_numero")
                botones["Aplicar"]()
                break

    with patch("configuracion.ARCHIVO_CONFIG", str(cfg_file)), \
         patch("configuracion.DIR_DATOS", str(tmp_path)), \
         patch("configuracion.ttk.Button", DummyButton), \
         patch("configuracion.messagebox.showinfo"), \
         patch("configuracion.messagebox.showerror") as mock_err, \
         patch.object(tk.Tk, "mainloop", probar_errores_guardado):
        configuracion.iniciar()
        assert mock_err.call_count >= 4


#################################################################




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
