import base64
import hashlib
import hmac
import json
import os
import sys
import uuid
import numpy as np


def obtener_ruta_base():
    """Devuelve la carpeta real donde está el .exe (si está compilado) o el script .py."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


RUTA_BASE = obtener_ruta_base()
DIR_DATOS = os.path.join(RUTA_BASE, "camarasIP")
RUTA_CONFIG_JSON = os.path.join(RUTA_BASE, "config.json")
RUTA_CLAVE_MAESTRA = os.path.join(DIR_DATOS, ".secret.key")


def _obtener_clave_maestra():
    """Obtiene o genera una clave única vinculada a esta máquina (Windows/Linux)."""
    os.makedirs(DIR_DATOS, exist_ok=True)
    if not os.path.exists(RUTA_CLAVE_MAESTRA):
        semilla = os.urandom(32) + str(uuid.getnode()).encode("utf-8")
        clave = hashlib.sha256(semilla).digest()
        with open(RUTA_CLAVE_MAESTRA, "wb") as f:
            f.write(clave)
        try:
            os.chmod(RUTA_CLAVE_MAESTRA, 0o600)  # Solo lectura/escritura para el propietario en Linux
        except OSError:
            pass
    else:
        with open(RUTA_CLAVE_MAESTRA, "rb") as f:
            clave = f.read()
    # Vinculamos también al hardware actual para impedir copiar config.json a otro PC sin la clave
    huella_hw = str(uuid.getnode()).encode("utf-8")
    return hashlib.sha256(clave + huella_hw).digest()


def cifrar_secreto(texto):
    """Cifra una contraseña en texto plano devolviendo una cadena 'ENC:...'."""
    if not texto:
        return ""
    texto = str(texto)
    if texto.startswith("ENC:") or texto in ("TU_PASSWORD", "TU_TOKEN_TELEGRAM", "CONTRASEÑA_DE_APLICACION_GMAIL"):
        return texto
    clave = _obtener_clave_maestra()
    iv = os.urandom(16)
    datos = texto.encode("utf-8")
    # Flujo de cifrado CTR basado en SHA-256 + verificación de integridad HMAC
    flujo = bytearray()
    contador = 0
    while len(flujo) < len(datos):
        bloque = hashlib.sha256(clave + iv + contador.to_bytes(4, "big")).digest()
        flujo.extend(bloque)
        contador += 1
    cifrado = bytes(a ^ b for a, b in zip(datos, flujo[:len(datos)]))
    firma = hmac.new(clave, iv + cifrado, hashlib.sha256).digest()[:16]
    token = base64.urlsafe_b64encode(iv + firma + cifrado).decode("ascii")
    return f"ENC:{token}"


def descifrar_secreto(valor):
    """Descifra una cadena 'ENC:...' o devuelve el texto si aún no estaba cifrado."""
    if not valor or not isinstance(valor, str) or not valor.startswith("ENC:"):
        return valor
    try:
        raw = base64.urlsafe_b64decode(valor[4:].encode("ascii"))
        iv, firma_recibida, cifrado = raw[:16], raw[16:32], raw[32:]
        clave = _obtener_clave_maestra()
        firma_esperada = hmac.new(clave, iv + cifrado, hashlib.sha256).digest()[:16]
        if not hmac.compare_digest(firma_recibida, firma_esperada):
            return ""
        flujo = bytearray()
        contador = 0
        while len(flujo) < len(cifrado):
            bloque = hashlib.sha256(clave + iv + contador.to_bytes(4, "big")).digest()
            flujo.extend(bloque)
            contador += 1
        return bytes(a ^ b for a, b in zip(cifrado, flujo[:len(cifrado)])).decode("utf-8")
    except Exception:
        return ""

# ==============================================================================
# PLANTILLA DE CONFIGURACIÓN DE CÁMARAS (Renombrar este archivo a config.py)
# ==============================================================================

CONFIG_CAMARAS_RTSP = [
    {
        "nombre": "Camara 1",
        "ip": "192.168.1.101",
        "usuario": "admin",
        "password": "TU_PASSWORD",
        "puerto_rtsp": 554,
        "puerto_onvif": 8899,
        "puerto_netip": 34567,
        "canal": 1,
        "stream": 0,
    },
    {
        "nombre": "Camara 2",
        "ip": "192.168.1.102",
        "usuario": "admin",
        "password": "TU_PASSWORD",
        "puerto_rtsp": 554,
        "puerto_onvif": 8899,
        "puerto_netip": 34567,
        "canal": 1,
        "stream": 0,
    },
    {
        "nombre": "Camara 3",
        "ip": "192.168.1.103",
        "usuario": "admin",
        "password": "TU_PASSWORD",
        "puerto_rtsp": 554,
        "puerto_onvif": 8899,
        "puerto_netip": 34567,
        "canal": 1,
        "stream": 0,
    },
]

CONFIG_PATIO = {
    "nombre": "Camara 4",
    "ip": "192.168.1.104",
    "usuario": "admin",
    "password": "TU_PASSWORD",
    "puerto_netip": 34567,
    "canales": (0, 1),
}

# ==========================================
# CONFIGURACIÓN DE TOKEN TELEGRAM
# ==========================================

TELEGRAM_TOKEN = "TU_TOKEN_TELEGRAM"
TELEGRAM_CHAT_ID = "TU_CHAT_ID"


# ==========================================
# CONFIGURACIÓN DE CORREO GMAIL
# ==========================================

EMAIL_ACTIVO = True
EMAIL_ADJUNTAR_FOTO = True

EMAIL_REMITENTE = "tu_correo@gmail.com"
EMAIL_PASSWORD = "CONTRASEÑA_DE_APLICACION_GMAIL"
EMAIL_DESTINATARIO = "destino@gmail.com"

EMAIL_SMTP_SERVIDOR = "smtp.gmail.com"
EMAIL_SMTP_PUERTO = 465

# Tiempo mínimo entre correos por cámara
EMAIL_INTERVALO_ALERTAS = 60


# ==============================================================================
# PARÁMETROS DE INTERFAZ, GRABACIÓN Y DETECCIÓN
# ==============================================================================


ANCHO_CELDA = 640
ALTO_CELDA = 360
ALTO_LENTE_DVRIP = ALTO_CELDA // 2
ANCHO_TOTAL_BASE = ANCHO_CELDA * 2
ALTO_TOTAL_BASE = ALTO_CELDA * 2

DISPOSITIVO_SALIDA_AUDIO = 3


MINUTOS_POR_BLOQUE_VIDEO = 10
SENSIBILIDAD_MOVIMIENTO = 1200
COOLDOWN_CAPTURA_SEG = 5
INTERVALO_FOTOGRAMA_AUTO_SEG = 10

MODO_MOSAICO = 4  # 1 = 1x1 (1 cámara), 2 = 1x2 (2 cámaras), 4 = 2x2 (4 cámaras)

_nombre_grabaciones = "grabaciones"
_nombre_movimiento = "capturas_movimiento"
_nombre_fotogramas = "capturas_fotogramas"


# ==============================================================================
# PARÁMETROS DE INTERFAZ, GRABACIÓN Y DETECCIÓN
# ==============================================================================

# Tamaño de cada recuadro en la cuadrícula 2x2 (Total ventana base: 1280x720)
ANCHO_CELDA = 640
ALTO_CELDA = 360
ALTO_LENTE_DVRIP = ALTO_CELDA // 2  # 180 px por lente apilada en modo 4 cámaras
ANCHO_TOTAL_BASE = ANCHO_CELDA * 2  # 1280
ALTO_TOTAL_BASE = ALTO_CELDA * 2    # 720

# Dispositivo de salida de audio para sounddevice
DISPOSITIVO_SALIDA_AUDIO = 3

# Parámetros de grabación y analítica
MINUTOS_POR_BLOQUE_VIDEO = 10
SENSIBILIDAD_MOVIMIENTO = 1200
COOLDOWN_CAPTURA_SEG = 5
INTERVALO_FOTOGRAMA_AUTO_SEG = 10

MODO_MOSAICO = 4  # 1 = 1x1 (1 cámara), 2 = 1x2 (2 cámaras), 4 = 2x2 (4 cámaras)

# Nombres de subcarpetas por defecto
_nombre_grabaciones = "grabaciones"
_nombre_movimiento = "capturas_movimiento"
_nombre_fotogramas = "capturas_fotogramas"

# ==============================================================================
# CARGA DE CONFIGURACIÓN PERSONALIZADA (config.json)
# ==============================================================================

if os.path.exists(RUTA_CONFIG_JSON):
    try:
        with open(RUTA_CONFIG_JSON, "r", encoding="utf-8") as _f:
            _guardados = json.load(_f)
        if isinstance(_guardados, dict):
            if "camaras_rtsp" in _guardados:
                CONFIG_CAMARAS_RTSP = _guardados["camaras_rtsp"]   
                for _cam in CONFIG_CAMARAS_RTSP:
                    if "password" in _cam:
                        _cam["password"] = descifrar_secreto(_cam["password"])  
            
            TELEGRAM_TOKEN = descifrar_secreto(_guardados.get("telegram_token", TELEGRAM_TOKEN))
            TELEGRAM_CHAT_ID = _guardados.get("telegram_chat_id", TELEGRAM_CHAT_ID)


            if "patio" in _guardados:
                CONFIG_PATIO = _guardados["patio"]
                if "password" in CONFIG_PATIO:
                    CONFIG_PATIO["password"] = descifrar_secreto(CONFIG_PATIO["password"])
                if "canales" in CONFIG_PATIO:
                    CONFIG_PATIO["canales"] = tuple(CONFIG_PATIO["canales"])

            _params = _guardados.get("parametros", {})
            MINUTOS_POR_BLOQUE_VIDEO = _params.get("minutos_por_bloque_video", MINUTOS_POR_BLOQUE_VIDEO)
            SENSIBILIDAD_MOVIMIENTO = _params.get("sensibilidad_movimiento", SENSIBILIDAD_MOVIMIENTO)
            COOLDOWN_CAPTURA_SEG = _params.get("cooldown_captura_seg", COOLDOWN_CAPTURA_SEG)
            INTERVALO_FOTOGRAMA_AUTO_SEG = _params.get("intervalo_fotograma_auto_seg", INTERVALO_FOTOGRAMA_AUTO_SEG)
            MODO_MOSAICO = int(_params.get("modo_mosaico", MODO_MOSAICO))
            if MODO_MOSAICO not in (1, 2, 4):
                MODO_MOSAICO = 4
            DISPOSITIVO_SALIDA_AUDIO = _guardados.get("dispositivo_salida_audio", DISPOSITIVO_SALIDA_AUDIO)

            _carpetas = _guardados.get("carpetas", {})
            _nombre_grabaciones = _carpetas.get("grabaciones") or _nombre_grabaciones
            _nombre_movimiento = _carpetas.get("capturas_movimiento") or _nombre_movimiento
            _nombre_fotogramas = _carpetas.get("capturas_fotogramas") or _nombre_fotogramas

            # --- BLOQUE DE CORREO ELECTRÓNICO ---
            _email = _guardados.get("email", {})
            if isinstance(_email, dict):
                EMAIL_ACTIVO = _email.get("activo", EMAIL_ACTIVO)
                EMAIL_ADJUNTAR_FOTO = _email.get("adjuntar_foto", EMAIL_ADJUNTAR_FOTO)
                EMAIL_REMITENTE = _email.get("remitente", EMAIL_REMITENTE)
                EMAIL_PASSWORD = descifrar_secreto(_email.get("password", EMAIL_PASSWORD))
                EMAIL_DESTINATARIO = _email.get("destinatario", EMAIL_DESTINATARIO)
                EMAIL_SMTP_SERVIDOR = _email.get("smtp_servidor", EMAIL_SMTP_SERVIDOR)
                EMAIL_SMTP_PUERTO = _email.get("smtp_puerto", EMAIL_SMTP_PUERTO)
                EMAIL_INTERVALO_ALERTAS = _email.get("intervalo_alertas", EMAIL_INTERVALO_ALERTAS)
                
            
    except (OSError, json.JSONDecodeError) as _exc:
        print(f"[CONFIG] No se pudo leer config.json, usando valores por defecto: {_exc}")

# ==============================================================================
# RUTAS FINALES DE ALMACENAMIENTO
# ==============================================================================

def _resolver_carpeta(nombre_o_ruta):
    """Permite usar tanto un nombre relativo (dentro de camarasIP) como una ruta absoluta."""
    if os.path.isabs(nombre_o_ruta):
        return nombre_o_ruta
    return os.path.join(DIR_DATOS, nombre_o_ruta)


CARPETA_GRABACIONES = _resolver_carpeta(_nombre_grabaciones)
CARPETA_CAPTURAS = _resolver_carpeta(_nombre_movimiento)
CARPETA_MOVIMIENTO = CARPETA_CAPTURAS
CARPETA_FOTOGRAMAS = _resolver_carpeta(_nombre_fotogramas)

CARPETAS_SALIDA = (
    CARPETA_GRABACIONES,
    CARPETA_CAPTURAS,
    CARPETA_FOTOGRAMAS,
)

for carpeta in CARPETAS_SALIDA:
    os.makedirs(carpeta, exist_ok=True)
    
    
# ==============================================================================
# RECARGAR EN CALIENTE
# ===================================================================

def recargar_configuracion():
    """Actualiza en caliente los parámetros y credenciales desde config.json."""
    global TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
    global MINUTOS_POR_BLOQUE_VIDEO, SENSIBILIDAD_MOVIMIENTO
    global COOLDOWN_CAPTURA_SEG, INTERVALO_FOTOGRAMA_AUTO_SEG
    global MODO_MOSAICO, DISPOSITIVO_SALIDA_AUDIO
    global EMAIL_ACTIVO, EMAIL_ADJUNTAR_FOTO, EMAIL_REMITENTE
    global EMAIL_PASSWORD, EMAIL_DESTINATARIO, EMAIL_SMTP_SERVIDOR
    global EMAIL_SMTP_PUERTO, EMAIL_INTERVALO_ALERTAS

    if not os.path.exists(RUTA_CONFIG_JSON):
        return False
    try:
        with open(RUTA_CONFIG_JSON, "r", encoding="utf-8") as f:
            guardados = json.load(f)
        if not isinstance(guardados, dict):
            return False

        TELEGRAM_TOKEN = descifrar_secreto(guardados.get("telegram_token", TELEGRAM_TOKEN))
        TELEGRAM_CHAT_ID = guardados.get("telegram_chat_id", TELEGRAM_CHAT_ID)
        DISPOSITIVO_SALIDA_AUDIO = guardados.get("dispositivo_salida_audio", DISPOSITIVO_SALIDA_AUDIO)

        params = guardados.get("parametros", {})
        if isinstance(params, dict):
            MINUTOS_POR_BLOQUE_VIDEO = params.get("minutos_por_bloque_video", MINUTOS_POR_BLOQUE_VIDEO)
            SENSIBILIDAD_MOVIMIENTO = params.get("sensibilidad_movimiento", SENSIBILIDAD_MOVIMIENTO)
            COOLDOWN_CAPTURA_SEG = params.get("cooldown_captura_seg", COOLDOWN_CAPTURA_SEG)
            INTERVALO_FOTOGRAMA_AUTO_SEG = params.get("intervalo_fotograma_auto_seg", INTERVALO_FOTOGRAMA_AUTO_SEG)
            nuevo_mosaico = int(params.get("modo_mosaico", MODO_MOSAICO))
            if nuevo_mosaico in (1, 2, 4):
                MODO_MOSAICO = nuevo_mosaico

        email = guardados.get("email", {})
        if isinstance(email, dict):
            EMAIL_ACTIVO = email.get("activo", EMAIL_ACTIVO)
            EMAIL_ADJUNTAR_FOTO = email.get("adjuntar_foto", EMAIL_ADJUNTAR_FOTO)
            EMAIL_REMITENTE = email.get("remitente", EMAIL_REMITENTE)
            EMAIL_PASSWORD = descifrar_secreto(email.get("password", EMAIL_PASSWORD))
            EMAIL_DESTINATARIO = email.get("destinatario", EMAIL_DESTINATARIO)
            EMAIL_SMTP_SERVIDOR = email.get("smtp_servidor", EMAIL_SMTP_SERVIDOR)
            EMAIL_SMTP_PUERTO = email.get("smtp_puerto", EMAIL_SMTP_PUERTO)
            EMAIL_INTERVALO_ALERTAS = email.get("intervalo_alertas", EMAIL_INTERVALO_ALERTAS)

        return True
    except (OSError, ValueError, json.JSONDecodeError):
        return False




# ==============================================================================
# FUNCIONES AUXILIARES COMPARTIDAS (CIFRADO Y AUDIO G.711 A-LAW)
# ==============================================================================

def hash_xmeye(password):
    """Genera el hash de contraseña requerido por el protocolo NetIP/DVRIP."""
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    res = ""
    md5_bytes = hashlib.md5(password.encode()).digest()
    for i in range(0, 16, 2):
        val = (md5_bytes[i] + md5_bytes[i + 1]) % 62
        res += chars[val]
    return res


def alaw_a_pcm(datos):
    """Decodifica audio G.711 A-law recibido de la cámara a PCM 16-bit."""
    datos = np.frombuffer(datos, dtype=np.uint8) ^ 0x55
    valor = ((datos & 0x0F).astype(np.int16) << 4) + 8
    segmento = (datos & 0x70) >> 4
    valor += np.where(segmento >= 1, 0x100, 0)
    valor = np.where(segmento > 1, valor << (segmento - 1), valor)
    return np.where((datos & 0x80) != 0, valor, -valor).astype(np.int16)


def pcm16_a_alaw(samples_int16):
    """Codifica muestras PCM 16-bit del micrófono a G.711 A-law."""
    pcm = np.clip(samples_int16.astype(np.int32), -32768, 32767)
    sign = np.where(pcm >= 0, 0x80, 0x00)
    pcm = np.where(pcm < 0, -pcm - 1, pcm)
    exp = np.zeros_like(pcm)
    for bit in range(1, 8):
        cond = pcm >= (256 << (bit - 1))
        exp = np.where(cond, bit, exp)
    mantissa = np.where(
        exp == 0,
        (pcm >> 4) & 0x0F,
        (pcm >> (exp + 3)) & 0x0F,
    )
    alaw = (sign | (exp << 4) | mantissa) ^ 0x55
    return alaw.astype(np.uint8).tobytes()
