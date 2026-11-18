"""
base_datos.py
Módulo de persistencia en MySQL / MariaDB para el historial de detecciones y eventos.
Características:
  - Lee dinámicamente las credenciales vigentes desde config.py (compatibles con recarga en caliente).
  - Crea automáticamente la tabla e índices si aún no existen.
  - Tolerante a fallos: si el servidor MySQL no está disponible, captura la excepción sin detener el vídeo.
  - Soporta consultas filtradas por cámara y fecha para el panel web y limpieza por antigüedad.
"""

import mysql.connector
from mysql.connector import Error
import config


# ==============================================================================
# CONEXIÓN E INICIALIZACIÓN DE TABLAS
# ==============================================================================

def _conectar():
    """Abre y devuelve una nueva conexión a MySQL/MariaDB usando config.py."""
    return mysql.connector.connect(
        host=str(getattr(config, "MYSQL_HOST", "127.0.0.1")).strip(),
        port=int(getattr(config, "MYSQL_PUERTO", 3306)),
        user=str(getattr(config, "MYSQL_USUARIO", "cctv_user")).strip(),
        password=str(getattr(config, "MYSQL_PASSWORD", "")).strip(),
        database=str(getattr(config, "MYSQL_BD", "stivihome_cctv")).strip(),
        connection_timeout=5,
    )


def inicializar_bd():
    """
    Comprueba la conexión con MySQL y crea la tabla 'historial_eventos' si no existe.
    Debe llamarse una vez al arrancar la aplicación en main.py.
    """
    if not getattr(config, "MYSQL_ACTIVO", True):
        print("[MYSQL] Registro en base de datos desactivado en la configuración.")
        return False

    conn = None
    cursor = None
    try:
        conn = _conectar()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS historial_eventos (
                id INT AUTO_INCREMENT PRIMARY KEY,
                fecha_hora DATETIME NOT NULL,
                camara VARCHAR(100) NOT NULL,
                tipo_evento VARCHAR(50) NOT NULL DEFAULT 'Movimiento',
                ruta_captura VARCHAR(255) DEFAULT NULL,
                INDEX idx_fecha (fecha_hora),
                INDEX idx_camara (camara)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
        """)
        conn.commit()
        print("[MYSQL] Base de datos conectada y tabla verificada.")
        return True
    except Error as exc:
        print(f"[MYSQL] No disponible (el sistema seguirá usando historial.txt): {exc}")
        return False
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


# ==============================================================================
# INSERCIÓN Y CONSULTA DE EVENTOS
# ==============================================================================

def registrar_evento_mysql(nombre_camara, tipo="Movimiento", ruta_captura=None):
    """
    Inserta un nuevo evento de detección en MySQL con la marca de tiempo actual.
    Se ejecuta de forma segura sin interrumpir el flujo de vídeo si hay error de red.
    """
    if not getattr(config, "MYSQL_ACTIVO", True):
        return False

    conn = None
    cursor = None
    try:
        conn = _conectar()
        cursor = conn.cursor()
        sql = (
            "INSERT INTO historial_eventos (fecha_hora, camara, tipo_evento, ruta_captura) "
            "VALUES (NOW(), %s, %s, %s)"
        )
        cursor.execute(sql, (str(nombre_camara), str(tipo), ruta_captura))
        conn.commit()
        return True
    except Error as exc:
        print(f"[MYSQL] Error guardando evento en base de datos: {exc}")
        return False
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


def obtener_eventos_filtrados(camara="", fecha="", limite=50):
    """
    Consulta los eventos registrados filtrando opcionalmente por nombre de cámara
    y/o fecha exacta (formato 'YYYY-MM-DD').
    Devuelve una lista de diccionarios lista para serializar a JSON o renderizar en HTML.
    """
    if not getattr(config, "MYSQL_ACTIVO", True):
        return []

    conn = None
    cursor = None
    try:
        conn = _conectar()
        cursor = conn.cursor(dictionary=True)

        condiciones = []
        parametros = []

        if camara:
            condiciones.append("camara = %s")
            parametros.append(str(camara).strip())

        if fecha:
            condiciones.append("DATE(fecha_hora) = %s")
            parametros.append(str(fecha).strip())

        where_sql = ("WHERE " + " AND ".join(condiciones)) if condiciones else ""
        sql = (
            "SELECT id, "
            "DATE_FORMAT(fecha_hora, '%d/%m/%Y %H:%i:%s') AS fecha, "
            "camara, tipo_evento, ruta_captura "
            f"FROM historial_eventos {where_sql} "
            "ORDER BY id DESC LIMIT %s"
        )
        parametros.append(int(limite))

        cursor.execute(sql, tuple(parametros))
        return cursor.fetchall()
    except Error as exc:
        print(f"[MYSQL] Error consultando historial: {exc}")
        return []
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


# ==============================================================================
# MANTENIMIENTO DE BASE DE DATOS
# ==============================================================================

def limpiar_eventos_antiguos(dias_retencion=90):
    """
    Elimina registros con más de 'dias_retencion' días de antigüedad para evitar
    que la tabla crezca indefinidamente tras meses de funcionamiento 24/7.
    """
    if not getattr(config, "MYSQL_ACTIVO", True) or dias_retencion <= 0:
        return 0

    conn = None
    cursor = None
    try:
        conn = _conectar()
        cursor = conn.cursor()
        sql = "DELETE FROM historial_eventos WHERE fecha_hora < DATE_SUB(NOW(), INTERVAL %s DAY)"
        cursor.execute(sql, (int(dias_retencion),))
        eliminados = cursor.rowcount
        conn.commit()
        if eliminados > 0:
            print(f"[MYSQL] Mantenimiento: {eliminados} eventos antiguos eliminados (> {dias_retencion} días).")
        return eliminados
    except Error as exc:
        print(f"[MYSQL] Error limpiando eventos antiguos: {exc}")
        return 0
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()
'''



Recordatorio de conexión en notificaciones.py

Para que cada detección de movimiento se guarde automáticamente en MySQL además de historial.txt, asegúrate de importar registrar_evento_mysql al inicio de notificaciones.py:
python
from base_datos import registrar_evento_mysql


----------------------------------------------------------


Y dentro de enviar_alerta_movimiento(imagen_bgr, nombre_camara) (justo después de escribir en historial.txt), lanza el guardado en segundo plano para no retrasar el envío de la foto a Telegram:
python
    threading.Thread(
        target=registrar_evento_mysql,
        args=(nombre_camara, "Movimiento"),
        daemon=True,
    ).start()
    


#################################################


1. En config.py: Valores por defecto y carga/descifrado de Web y MySQL

Añade estas variables por defecto en config.py (debajo del bloque de correo):
python
WEB_ACTIVO = True
WEB_PUERTO = 8080
WEB_USUARIO = "admin"
WEB_PASSWORD = "stivihome2026"

MYSQL_ACTIVO = True
MYSQL_HOST = "127.0.0.1"
MYSQL_PUERTO = 3306
MYSQL_BD = "stivihome_cctv"
MYSQL_USUARIO = "cctv_user"
MYSQL_PASSWORD = "TuPasswordSegura123"




#######################################################################################################





Dentro del bloque de lectura de config.json (y en recargar_configuracion()), añade la carga con descifrar_secreto():
python
            _web = _guardados.get("web", {})
            if isinstance(_web, dict):
                WEB_ACTIVO = _web.get("activo", WEB_ACTIVO)
                WEB_PUERTO = int(_web.get("puerto", WEB_PUERTO))
                WEB_USUARIO = _web.get("usuario", WEB_USUARIO)
                WEB_PASSWORD = descifrar_secreto(_web.get("password", WEB_PASSWORD))

            _mysql = _guardados.get("mysql", {})
            if isinstance(_mysql, dict):
                MYSQL_ACTIVO = _mysql.get("activo", MYSQL_ACTIVO)
                MYSQL_HOST = _mysql.get("host", MYSQL_HOST)
                MYSQL_PUERTO = int(_mysql.get("puerto", MYSQL_PUERTO))
                MYSQL_BD = _mysql.get("bd", MYSQL_BD)
                MYSQL_USUARIO = _mysql.get("usuario", MYSQL_USUARIO)
                MYSQL_PASSWORD = descifrar_secreto(_mysql.get("password", MYSQL_PASSWORD))



#####################################################################################################

2. En configuracion.py: Pestaña "Servidor y BD" con cifrado automático


A. Importar los nuevos valores y crear la pestaña

En las importaciones superiores de configuracion.py:
python
    EMAIL_INTERVALO_ALERTAS, EMAIL_ADJUNTAR_FOTO, MODO_MOSAICO,
    WEB_ACTIVO, WEB_PUERTO, WEB_USUARIO, WEB_PASSWORD,
    MYSQL_ACTIVO, MYSQL_HOST, MYSQL_PUERTO, MYSQL_BD, MYSQL_USUARIO, MYSQL_PASSWORD,
)


---------------------------------------------------------------

Donde se crean las pestañas del notebook:
python
    tab_mant = ttk.Frame(notebook, padding=16)
    notebook.add(tab_mant, text="Mantenimiento")
    tab_servidor = ttk.Frame(notebook, padding=16)
    notebook.add(tab_servidor, text="Servidor y BD")
    tab_acerca = ttk.Frame(notebook, padding=18)
    notebook.add(tab_acerca, text="Acerca de")


##########################################################################################################

B. Campos visuales de Servidor Web y MySQL

Pega este bloque justo antes de la pestaña Acerca de:
python
    # --- PESTAÑA: SERVIDOR WEB Y BASE DE DATOS MYSQL ---
    web_guardado = guardados.get("web", {})
    mysql_guardado = guardados.get("mysql", {})

    grupo_web = ttk.LabelFrame(tab_servidor, text="Servidor Web Local / Proxy Apache", padding=10)
    grupo_web.pack(fill="x", pady=(0, 12))

    var_web_activo = tk.BooleanVar(value=web_guardado.get("activo", WEB_ACTIVO))
    ttk.Checkbutton(grupo_web, text="Activar servidor web interno", variable=var_web_activo).pack(anchor="w", pady=(0, 6))

    entrada_web_puerto = campo(grupo_web, "Puerto interno", web_guardado.get("puerto", WEB_PUERTO), ancho=25)
    entrada_web_user = campo(grupo_web, "Usuario acceso", web_guardado.get("usuario", WEB_USUARIO), ancho=25)
    entrada_web_pass = campo(grupo_web, "Contraseña acceso", WEB_PASSWORD, ocultar=True, ancho=25)

    grupo_mysql = ttk.LabelFrame(tab_servidor, text="Base de Datos MySQL / MariaDB (Historial)", padding=10)
    grupo_mysql.pack(fill="x", pady=(0, 8))

    var_mysql_activo = tk.BooleanVar(value=mysql_guardado.get("activo", MYSQL_ACTIVO))
    ttk.Checkbutton(grupo_mysql, text="Registrar historial en MySQL", variable=var_mysql_activo).pack(anchor="w", pady=(0, 6))

    entrada_mysql_host = campo(grupo_mysql, "Servidor / Host", mysql_guardado.get("host", MYSQL_HOST), ancho=25)
    entrada_mysql_puerto = campo(grupo_mysql, "Puerto MySQL", mysql_guardado.get("puerto", MYSQL_PUERTO), ancho=25)
    entrada_mysql_bd = campo(grupo_mysql, "Base de datos", mysql_guardado.get("bd", MYSQL_BD), ancho=25)
    entrada_mysql_user = campo(grupo_mysql, "Usuario BD", mysql_guardado.get("usuario", MYSQL_USUARIO), ancho=25)
    entrada_mysql_pass = campo(grupo_mysql, "Contraseña BD", MYSQL_PASSWORD, ocultar=True, ancho=25)


###############################################################################################

C. Guardar y cifrar en guardar()

Dentro de guardar(), añade estos dos bloques y inclúyelos en el diccionario datos:
python
            datos_web = {
                "activo": bool(var_web_activo.get()),
                "puerto": entero(entrada_web_puerto, "Puerto interno Web"),
                "usuario": entrada_web_user.get().strip() or "admin",
                "password": cifrar_secreto(entrada_web_pass.get().strip()),
            }

            datos_mysql = {
                "activo": bool(var_mysql_activo.get()),
                "host": entrada_mysql_host.get().strip() or "127.0.0.1",
                "puerto": entero(entrada_mysql_puerto, "Puerto MySQL"),
                "bd": entrada_mysql_bd.get().strip() or "stivihome_cctv",
                "usuario": entrada_mysql_user.get().strip() or "cctv_user",
                "password": cifrar_secreto(entrada_mysql_pass.get().strip()),
            }

            datos = {
                "camaras_rtsp": lista_camaras,
                "patio": patio,
                "parametros": parametros,
                "carpetas": {k: v.get().strip() for k, v in entradas_carpetas.items()},
                "dispositivo_salida_audio": dispositivo,
                "telegram_token": cifrar_secreto(entrada_token.get().strip()),
                "telegram_chat_id": entrada_chat.get().strip(),
                "email": datos_email,
                "mantenimiento": datos_mant,
                "web": datos_web,
                "mysql": datos_mysql,
            }




'''
