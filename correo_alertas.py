"""Módulo de envío de alertas y clips de vídeo por correo electrónico (SMTP SSL)."""
from datetime import datetime
from email.message import EmailMessage
import json
import os
import smtplib
import threading
import time
import cv2

from config import (
    EMAIL_ACTIVO,
    EMAIL_ADJUNTAR_FOTO,
    EMAIL_DESTINATARIO,
    EMAIL_INTERVALO_ALERTAS,
    EMAIL_PASSWORD,
    EMAIL_REMITENTE,
    EMAIL_SMTP_PUERTO,
    EMAIL_SMTP_SERVIDOR,
    RUTA_CONFIG_JSON,
    descifrar_secreto,
)

email_alertas_activas = EMAIL_ACTIVO

_ultimos_envios = {}
_lock_correo = threading.Lock()
_semaforo_smtp = threading.Semaphore(2)  # Máximo 2 conexiones SMTP simultáneas


def _obtener_config_email():
    """Devuelve la configuración de correo actual combinando config.py y config.json."""
    cfg = {
        "adjuntar_foto": EMAIL_ADJUNTAR_FOTO,
        "remitente": EMAIL_REMITENTE,
        "password": EMAIL_PASSWORD,
        "destinatario": EMAIL_DESTINATARIO,
        "smtp_servidor": EMAIL_SMTP_SERVIDOR,
        "smtp_puerto": EMAIL_SMTP_PUERTO,
        "intervalo_alertas": EMAIL_INTERVALO_ALERTAS,
    }
    if os.path.exists(RUTA_CONFIG_JSON):
        try:
            with open(RUTA_CONFIG_JSON, "r", encoding="utf-8") as f:
                guardados = json.load(f)
            if isinstance(guardados, dict) and isinstance(guardados.get("email"), dict):
                cfg.update(guardados["email"])
                cfg["password"] = descifrar_secreto(cfg["password"])
        except (OSError, json.JSONDecodeError):
            pass
    return cfg


# Sincronizamos el estado inicial con config.json si existe
if os.path.exists(RUTA_CONFIG_JSON):
    try:
        with open(RUTA_CONFIG_JSON, "r", encoding="utf-8") as _f:
            _data = json.load(_f)
        if isinstance(_data, dict) and "email" in _data:
            email_alertas_activas = bool(_data["email"].get("activo", email_alertas_activas))
    except (OSError, json.JSONDecodeError):
        pass


def alternar_alertas_correo():
    """Activa o desactiva el envío de alertas por correo en tiempo real."""
    global email_alertas_activas
    email_alertas_activas = not email_alertas_activas
    estado = "ACTIVADAS" if email_alertas_activas else "DESACTIVADAS"
    print(f"[EMAIL] Alertas por correo {estado}")


def _despachar_mensaje_smtp(asunto, cuerpo, adjunto=None):
    """Construye y envía el correo electrónico de forma thread-safe."""
    cfg = _obtener_config_email()
    remitente = str(cfg["remitente"]).strip()
    password = str(cfg["password"]).strip()
    destinatario = str(cfg["destinatario"]).strip()

    if not remitente or not password or not destinatario or password == "CONTRASEÑA_DE_APLICACION_GMAIL":
        return False

    with _semaforo_smtp:
        try:
            mensaje = EmailMessage()
            mensaje["Subject"] = asunto
            mensaje["From"] = remitente
            mensaje["To"] = destinatario
            mensaje.set_content(cuerpo)

            if adjunto is not None:
                datos_binarios, maintype, subtype, nombre_archivo = adjunto
                mensaje.add_attachment(
                    datos_binarios,
                    maintype=maintype,
                    subtype=subtype,
                    filename=nombre_archivo,
                )

            with smtplib.SMTP_SSL(
                cfg["smtp_servidor"], int(cfg["smtp_puerto"]), timeout=25
            ) as servidor:
                servidor.login(remitente, password)
                servidor.send_message(mensaje)

            return True
        except Exception as exc:
            print(f"[EMAIL] Error enviando correo: {exc}")
            return False


def enviar_correo_evento(camara, evento, imagen=None):
    """Envía un correo con los datos del evento y una fotografía opcional."""
    if not email_alertas_activas:
        return False

    cfg = _obtener_config_email()
    ahora = datetime.now()
    nombre = getattr(camara, "nombre", "Cámara desconocida")
    asunto = f"ALERTA CCTV - {nombre}"

    cuerpo = (
        "Se ha recibido un evento de videovigilancia.\n\n"
        f"Cámara: {nombre}\n"
        f"Fecha: {ahora.strftime('%d/%m/%Y')}\n"
        f"Hora: {ahora.strftime('%H:%M:%S')}\n\n"
        f"Evento recibido:\n{evento}\n"
    )

    adjunto = None
    if cfg["adjuntar_foto"] and imagen is not None:
        exito, buffer = cv2.imencode(".jpg", imagen, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if exito:
            adjunto = (buffer.tobytes(), "image", "jpeg", f"{nombre}_{ahora:%Y%m%d_%H%M%S}.jpg")

    if _despachar_mensaje_smtp(asunto, cuerpo, adjunto):
        print(f"[EMAIL] Alerta enviada: {nombre}")
        return True
    return False


def _puede_enviar_alerta(nombre_camara):
    """Comprueba y actualiza el tiempo de espera entre alertas por cámara."""
    cfg = _obtener_config_email()
    intervalo = int(cfg["intervalo_alertas"])
    ahora = time.time()

    with _lock_correo:
        ultimo = _ultimos_envios.get(nombre_camara, 0)
        if ahora - ultimo < intervalo:
            return False
        _ultimos_envios[nombre_camara] = ahora
        return True


def procesar_evento_correo(camara, datos_evento, _numero_secuencia):
    """Callback para alarmas DVRIP de cada cámara."""
    if not email_alertas_activas:
        return

    nombre = getattr(camara, "nombre", "Cámara desconocida")
    if not _puede_enviar_alerta(nombre):
        return

    try:
        evento_texto = json.dumps(datos_evento, ensure_ascii=False, default=str)
    except Exception:
        evento_texto = str(datos_evento)

    print(f"[EVENTO DVRIP] {nombre}: {evento_texto}")

    cfg = _obtener_config_email()
    imagen = None
    if cfg["adjuntar_foto"] and getattr(camara, "frame", None) is not None:
        imagen = camara.frame.copy()

    threading.Thread(
        target=enviar_correo_evento,
        args=(camara, evento_texto, imagen),
        daemon=True,
    ).start()


def crear_callback_correo(camara):
    """Crea un callback independiente para cada cámara."""
    def callback(datos_evento, numero_secuencia):
        procesar_evento_correo(camara, datos_evento, numero_secuencia)
    return callback


def enviar_alerta_correo_rtsp(nombre_camara, imagen):
    """Envía alerta por correo ante detección de movimiento respetando el intervalo."""
    if not email_alertas_activas or not _puede_enviar_alerta(nombre_camara):
        return

    cfg = _obtener_config_email()
    camara_info = type("CamaraInfo", (), {"nombre": nombre_camara})()
    copia_imagen = imagen.copy() if (cfg["adjuntar_foto"] and imagen is not None) else None

    threading.Thread(
        target=enviar_correo_evento,
        args=(camara_info, "Detección de movimiento", copia_imagen),
        daemon=True,
    ).start()


def _enviar_video_correo_hilo(ruta_video, nombre_camara):
    """Lee el archivo .mp4 y lo envía por SMTP en segundo plano."""
    try:
        with open(ruta_video, "rb") as f:
            datos_mp4 = f.read()
    except OSError as exc:
        print(f"[EMAIL] No se pudo leer el clip {ruta_video}: {exc}")
        return

    ahora = datetime.now()
    asunto = f"VÍDEO ALERTA CCTV - {nombre_camara}"
    cuerpo = (
        "Se ha grabado un clip de vídeo tras detectar movimiento.\n\n"
        f"Cámara: {nombre_camara}\n"
        f"Fecha: {ahora.strftime('%d/%m/%Y')}\n"
        f"Hora: {ahora.strftime('%H:%M:%S')}\n"
    )
    adjunto = (datos_mp4, "video", "mp4", os.path.basename(ruta_video))

    if _despachar_mensaje_smtp(asunto, cuerpo, adjunto):
        print(f"[EMAIL] Clip de vídeo enviado: {ruta_video}")


def enviar_video_correo(ruta_video, nombre_camara):
    """Lanza el envío del clip .mp4 por correo si las alertas están activas."""
    if not email_alertas_activas:
        return
    threading.Thread(
        target=_enviar_video_correo_hilo,
        args=(ruta_video, nombre_camara),
        daemon=True,
    ).start()
