"""Módulo de notificaciones, historial y control remoto mediante Bot de Telegram."""
from datetime import datetime
import http.client
import json
import os
import re
import threading
import time
import urllib.parse
import cv2
from logger import RUTA_LOG

import config
from config import DIR_DATOS, TELEGRAM_CHAT_ID, TELEGRAM_TOKEN
import correo_alertas

alertas_activas = True
camara_telegram_idx = 0
_detener_bot = False

ARCHIVO_HISTORIAL = os.path.join(DIR_DATOS, "historial.txt")
_lock_historial = threading.Lock()
_semaforo_envios = threading.Semaphore(3)  # Máximo 3 envíos simultáneos a Telegram

# Teclado táctil completo con selector de cámara, cruceta PTZ y controles
TECLADO_TELEGRAM = {
    "keyboard": [
        [{"text": "📹 Cám 1"}, {"text": "📹 Cám 2"}, {"text": "📹 Cám 3"}, {"text": "📹 Cám 4"}],
        [{"text": "🔍 Zoom -"}, {"text": "⬆️ Arriba"}, {"text": "🔍 Zoom +"}],
        [{"text": "⬅️ Izquierda"}, {"text": "📸 Foto Actual"}, {"text": "➡️ Derecha"}],
        [{"text": "💡 Luz"}, {"text": "⬇️ Abajo"}, {"text": "🎥 Grabar"}],
        [{"text": "📸 Foto 1"}, {"text": "📸 Foto 2"}, {"text": "📸 Foto 3"}, {"text": "📸 Foto 4"}],
        [{"text": "🎥 Grabar 1"}, {"text": "🎥 Grabar 2"}, {"text": "🎥 Grabar 3"}, {"text": "🎥 Grabar 4"}],
        [{"text": "👁️ Detec 1"}, {"text": "👁️ Detec 2"}, {"text": "👁️ Detec 3"}, {"text": "👁️ Detec 4"}],
        [{"text": "🎬 Pre-Buf 1"}, {"text": "🎬 Pre-Buf 2"}, {"text": "🎬 Pre-Buf 3"}, {"text": "🎬 Pre-Buf 4"}],
        [{"text": "💡 Luz 1"}, {"text": "💡 Luz 2"}, {"text": "💡 Luz 3"}, {"text": "💡 Luz 4"}],
        [{"text": "📷 Todas Fotos"}, {"text": "🔔 Alertas ON/OFF"}, {"text": "📧 Email ON/OFF"}],
        [{"text": "📊 Estado"}, {"text": "📋 Historial"}, {"text": "📄 Logs"}],
        [{"text": "📍 Punto 1"}, {"text": "📍 Punto 2"}, {"text": "📍 Punto 3"}],

    ],
    "resize_keyboard": False,
    "is_persistent": True,
}

MAPEO_BOTONES = {
    "📹 cám 1": "/sel1",
    "📹 cám 2": "/sel2",
    "📹 cám 3": "/sel3",
    "📹 cám 4": "/sel4",
    "⬆️ arriba": "/ptz_arriba",
    "⬇️ abajo": "/ptz_abajo",
    "⬅️ izquierda": "/ptz_izquierda",
    "➡️ derecha": "/ptz_derecha",
    "🔍 zoom +": "/zoom_mas",
    "🔍 zoom -": "/zoom_menos",
    "📸 foto actual": "/foto_actual",
    "💡 luz": "/luz_actual",
    "🎥 grabar": "/grabar_actual",
    "📸 foto 1": "/foto1",
    "📸 foto 2": "/foto2",
    "📸 foto 3": "/foto3",
    "📸 foto 4": "/foto4",
    "🎥 grabar 1": "/grabar1",
    "🎥 grabar 2": "/grabar2",
    "🎥 grabar 3": "/grabar3",
    "🎥 grabar 4": "/grabar4",
    "👁️ detec 1": "/deteccion1",
    "👁️ detec 2": "/deteccion2",
    "👁️ detec 3": "/deteccion3",
    "👁️ detec 4": "/deteccion4",
    "💡 luz 1": "/luz1",
    "💡 luz 2": "/luz2",
    "💡 luz 3": "/luz3",
    "💡 luz 4": "/luz4",
    "📷 todas fotos": "/foto",
    "🔔 alertas on/off": "/alertas",
    "🎬 pre-buf 1": "/prebuffer1",
    "🎬 pre-buf 2": "/prebuffer2",
    "🎬 pre-buf 3": "/prebuffer3",
    "🎬 pre-buf 4": "/prebuffer4",
    "📍 punto 1": "/preset1",
    "📍 punto 2": "/preset2",
    "📍 punto 3": "/preset3",
    "📧 email on/off": "/email",
    "📋 historial": "/historial",
    "📊 estado": "/estado",
    "📄 logs": "/logs",
}


def alternar_alertas():
    """Activa o desactiva el envío de notificaciones a Telegram."""
    global alertas_activas
    alertas_activas = not alertas_activas
    estado = "ACTIVADAS" if alertas_activas else "DESACTIVADAS"
    print(f"[ALERTA] Notificaciones Telegram {estado}")


def _obtener_credenciales():
    token = str(config.TELEGRAM_TOKEN).strip()
    chat_id = str(config.TELEGRAM_CHAT_ID).strip()
    if not token or not chat_id or token == "TU_TOKEN_TELEGRAM":
        return None, None
    return token, chat_id


def enviar_mensaje_telegram(texto, incluir_teclado=True):
    """Envía un mensaje de texto con la botonera táctil adjunta."""
    token, chat_id = _obtener_credenciales()
    if not token:
        return

    conn = None
    try:
        datos = {"chat_id": chat_id, "text": texto}
        if incluir_teclado:
            datos["reply_markup"] = json.dumps(TECLADO_TELEGRAM)

        params = urllib.parse.urlencode(datos)
        conn = http.client.HTTPSConnection("api.telegram.org", timeout=10)
        conn.request("GET", f"/bot{token}/sendMessage?{params}")
        resp = conn.getresponse()
        resp.read()
    except Exception as exc:
        print(f"[ALERTA] Error enviando texto a Telegram: {exc}")
    finally:
        if conn:
            conn.close()


def _enviar_multipart_telegram(endpoint, campo_archivo, nombre_archivo, mime_type, datos_binarios, caption):
    """Método genérico thread-safe para subir fotos o vídeos a Telegram."""
    token, chat_id = _obtener_credenciales()
    if not token:
        return False

    conn = None
    with _semaforo_envios:
        try:
            boundary = "----BoundaryAlertaCamara7MA4YWxkTrZu0gW"
            cuerpo = (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="chat_id"\r\n\r\n'
                f"{chat_id}\r\n"
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="caption"\r\n\r\n'
                f"{caption}\r\n"
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{campo_archivo}"; filename="{nombre_archivo}"\r\n'
                f"Content-Type: {mime_type}\r\n\r\n"
            ).encode("utf-8") + datos_binarios + f"\r\n--{boundary}--\r\n".encode("utf-8")

            cabeceras = {
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(cuerpo)),
            }

            conn = http.client.HTTPSConnection("api.telegram.org", timeout=30)
            conn.request("POST", f"/bot{token}/{endpoint}", body=cuerpo, headers=cabeceras)
            resp = conn.getresponse()
            resp.read()
            return True
        except Exception as exc:
            print(f"[ALERTA] Error enviando {campo_archivo} a Telegram: {exc}")
            return False
        finally:
            if conn:
                conn.close()


def _enviar_foto_telegram(imagen_bgr, texto):
    exito, buffer = cv2.imencode(".jpg", imagen_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    if exito:
        _enviar_multipart_telegram("sendPhoto", "photo", "alerta.jpg", "image/jpeg", buffer.tobytes(), texto)


def _enviar_video_telegram(ruta_video, texto):
    try:
        with open(ruta_video, "rb") as f:
            datos_mp4 = f.read()
        if _enviar_multipart_telegram("sendVideo", "video", "evento.mp4", "video/mp4", datos_mp4, texto):
            print(f"[TELEGRAM] Clip de vídeo enviado: {ruta_video}")
    except OSError as exc:
        print(f"[ALERTA] No se pudo leer el vídeo {ruta_video}: {exc}")


def enviar_video_evento(ruta_video, nombre_camara):
    """Lanza el envío del clip .mp4 a Telegram en segundo plano."""
    if not alertas_activas:
        return
    mensaje = f"🎥 Clip de evento (con pre-buffer) en: {nombre_camara}"
    threading.Thread(target=_enviar_video_telegram, args=(ruta_video, mensaje), daemon=True).start()


def enviar_alerta_movimiento(imagen_bgr, nombre_camara):
    """Guarda la detección en historial.txt y envía foto si las alertas están activas."""
    hora_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    linea = f"• {hora_str} — {nombre_camara}\n"

    with _lock_historial:
        try:
            os.makedirs(DIR_DATOS, exist_ok=True)
            with open(ARCHIVO_HISTORIAL, "a", encoding="utf-8") as f:
                f.write(linea)
        except OSError as exc:
            print(f"[HISTORIAL] Error escribiendo en historial.txt: {exc}")

    if not alertas_activas:
        return
    copia = imagen_bgr.copy()
    mensaje = f"🚨 Movimiento detectado en: {nombre_camara}"
    threading.Thread(target=_enviar_foto_telegram, args=(copia, mensaje), daemon=True).start()


def _enviar_captura_camara(camara, prefijo="📷"):
    """Extrae el fotograma actual de una cámara (thread-safe) y lo envía a Telegram."""
    frame = camara.frame
    if frame is not None:
        _enviar_foto_telegram(frame.copy(), f"{prefijo} {camara.nombre}")
    else:
        enviar_mensaje_telegram(f"⚠️ {camara.nombre} aún no tiene imagen disponible.")


def _procesar_comando(texto, camaras):
    """Procesa selección de cámara, movimientos PTZ, zoom y controles."""
    global camara_telegram_idx
    entrada = texto.strip().lower()
    cmd = MAPEO_BOTONES.get(entrada, entrada)

    if not camaras:
        enviar_mensaje_telegram("⚠️ No hay cámaras conectadas en el sistema.")
        return

    if camara_telegram_idx >= len(camaras):
        camara_telegram_idx = 0
    cam_activa = camaras[camara_telegram_idx]

    if cmd in ("/start", "/ayuda", "/help"):
        lista_cams = "\n".join(
            f"  {'👉' if i == camara_telegram_idx else '▫️'} {i + 1}. {c.nombre}"
            for i, c in enumerate(camaras)
        )
        ayuda = (
            "🛡️ CONTROL REMOTO PTZ Y CÁMARAS\n\n"
            f"Cámara activa: {cam_activa.nombre}\n"
            f"{lista_cams}\n\n"
            "• Pulsa Cám 1..4 para elegir qué cámara mover.\n"
            "• Usa la cruceta (Arriba, Abajo, Izquierda, Derecha) para girar la cámara."
        )
        enviar_mensaje_telegram(ayuda)
        return

    # 1. Seleccionar cámara activa (/sel1..4)
    match_sel = re.match(r"^/sel(\d+)$", cmd)
    if match_sel:
        idx = int(match_sel.group(1)) - 1
        if 0 <= idx < len(camaras):
            camara_telegram_idx = idx
            cam_activa = camaras[idx]
            _enviar_captura_camara(cam_activa, prefijo=f"✅ Seleccionada [{idx + 1}]")
        else:
            enviar_mensaje_telegram(f"⚠️ La cámara {idx + 1} no existe (hay {len(camaras)}).")
        return

    # 2. Movimiento PTZ sobre la cámara seleccionada
    movimientos_ptz = {
        "/ptz_arriba": (0.0, 0.5, 0.0),
        "/ptz_abajo": (0.0, -0.5, 0.0),
        "/ptz_izquierda": (0.5, 0.0, 0.0),
        "/ptz_derecha": (-0.5, 0.0, 0.0),
    }
    if cmd in movimientos_ptz:
        vx, vy, vz = movimientos_ptz[cmd]
        cam_activa.mover_ptz(vx, vy, vz)
        return

    # 3. Zoom digital sobre la cámara seleccionada
    if cmd in ("/zoom_mas", "/zoom_menos"):
        paso = 0.2 if cmd == "/zoom_mas" else -0.2
        cam_activa.cambiar_zoom(paso)
        _enviar_captura_camara(cam_activa, prefijo=f"🔍 Zoom {cam_activa.zoom_digital:.1f}x |")
        return

    # 4. Atajos sobre la cámara seleccionada actualmente
    if cmd == "/foto_actual":
        _enviar_captura_camara(cam_activa, prefijo="📸")
        return
    if cmd == "/luz_actual":
        cmd = f"/luz{camara_telegram_idx + 1}"
    elif cmd == "/grabar_actual":
        cmd = f"/grabar{camara_telegram_idx + 1}"

    if cmd == "/estado":
        lineas = [
            "📊 ESTADO DEL SISTEMA",
            f"• Cámara activa PTZ: [{camara_telegram_idx + 1}] {cam_activa.nombre}",
            f"• Alertas móvil: {'🟢 ON' if alertas_activas else '⚪ OFF'}\n",
        ]
        for i, c in enumerate(camaras):
            grab = "🔴 REC" if c.grabando else "⚪ OFF"
            det = "🟢 ON" if c.deteccion_activa else "⚪ OFF"
            marca = "👉 " if i == camara_telegram_idx else ""
            lineas.append(f"{marca}{i + 1}. {c.nombre}: Grab {grab} | Det {det} | Luz {c.modo_luz_actual}")
        enviar_mensaje_telegram("\n".join(lineas))
        return

    if cmd == "/alertas":
        alternar_alertas()
        enviar_mensaje_telegram(f"🔔 Alertas al móvil: {'ACTIVADAS 🟢' if alertas_activas else 'SILENCIADAS ⚪'}.")
        return

    if cmd == "/email":
        correo_alertas.alternar_alertas_correo()
        estado_mail = "ACTIVADAS 🟢" if correo_alertas.email_alertas_activas else "SILENCIADAS ⚪"
        enviar_mensaje_telegram(f"📧 Alertas por correo: {estado_mail}.")
        return

    if cmd == "/historial":
        with _lock_historial:
            if not os.path.exists(ARCHIVO_HISTORIAL):
                enviar_mensaje_telegram("📋 Aún no hay detecciones guardadas en historial.txt.")
                return
            try:
                with open(ARCHIVO_HISTORIAL, "r", encoding="utf-8") as f:
                    lineas = [l.strip() for l in f if l.strip()]
            except OSError as exc:
                enviar_mensaje_telegram(f"⚠️ Error leyendo historial: {exc}")
                return

        if not lineas:
            enviar_mensaje_telegram("📋 El archivo historial.txt está vacío.")
        else:
            ultimas_5 = list(reversed(lineas[-5:]))
            enviar_mensaje_telegram("📋 ÚLTIMAS 5 DETECCIONES:\n\n" + "\n".join(ultimas_5))
        return
    
    if cmd == "/logs":
        if not os.path.exists(RUTA_LOG):
            enviar_mensaje_telegram("📄 Aún no se ha generado el archivo sistema.log.")
            return
        try:
            with open(RUTA_LOG, "r", encoding="utf-8", errors="ignore") as f:
                lineas = [l.strip() for l in f if l.strip()]
            if not lineas:
                enviar_mensaje_telegram("📄 El registro sistema.log está vacío.")
            else:
                ultimas_15 = "\n".join(lineas[-15:])
                # Limitamos a 3800 caracteres para respetar el máximo de 4096 de Telegram
                if len(ultimas_15) > 3800:
                    ultimas_15 = "...\n" + ultimas_15[-3800:]
                enviar_mensaje_telegram(f"📄 ÚLTIMOS EVENTOS DEL SISTEMA:\n\n{ultimas_15}")
        except OSError as exc:
            enviar_mensaje_telegram(f"⚠️ Error leyendo sistema.log: {exc}")
        return


    # 5. Comandos individuales o globales (/foto1..4, /grabar1..4, /deteccion1..4, /prebuffer1..4, /luz1..4)
    coincidencia = re.match(r"^/(foto|grabar|deteccion|prebuffer|luz)(\d+)?$", cmd)
    if coincidencia:
        accion, num_str = coincidencia.groups()
        if num_str is not None:
            idx = int(num_str) - 1
            if idx < 0 or idx >= len(camaras):
                enviar_mensaje_telegram(f"⚠️ La cámara {num_str} no existe (hay {len(camaras)} cámaras).")
                return
            objetivos = [camaras[idx]]
        else:
            objetivos = camaras

        if accion == "foto":
            for c in objetivos:
                _enviar_captura_camara(c, prefijo="📷")

        elif accion == "grabar":
            respuestas = []
            for c in objetivos:
                c.alternar_grabacion()
                estado = "INICIADA 🔴" if c.grabando else "DETENIDA ⏹️"
                respuestas.append(f"🎥 {c.nombre}: Grabación {estado}")
            enviar_mensaje_telegram("\n".join(respuestas))

        elif accion == "deteccion":
            respuestas = []
            for c in objetivos:
                c.alternar_deteccion()
                estado = "ACTIVADA 🟢" if c.deteccion_activa else "DESACTIVADA ⚪"
                respuestas.append(f"👁️ {c.nombre}: Detección {estado}")
            enviar_mensaje_telegram("\n".join(respuestas))

        elif accion == "prebuffer":
            respuestas = []
            for c in objetivos:
                c.alternar_grab_movimiento()
                estado = "ACTIVADO 🟢" if c.grabador_eventos.activa else "DESACTIVADO ⚪"
                respuestas.append(f"🎬 {c.nombre}: Pre-buffer {estado}")
            enviar_mensaje_telegram("\n".join(respuestas))

        elif accion == "luz":
            ciclo = {"AUTO": "BLANCA", "BLANCA": "IR", "IR": "AUTO"}
            nombres_bonitos = {
                "BLANCA": "Luz BLANCA ☀️",
                "IR": "Infrarrojos (IR) 🌙",
                "AUTO": "Luz AUTOMÁTICA 🔄",
            }
            respuestas = []
            for c in objetivos:
                actual = str(c.modo_luz_actual).upper()
                siguiente = ciclo.get(actual, "BLANCA")
                c.cambiar_luz_led(siguiente)
                respuestas.append(f"💡 {c.nombre}: {nombres_bonitos[siguiente]}")
            enviar_mensaje_telegram("\n".join(respuestas))
        return

    # 6. Presets PTZ (/preset1..9 para ir, /setpreset1..9 para guardar)
    match_preset = re.match(r"^/(set)?preset(\d+)$", cmd)
    if match_preset:
        guardar, num_str = match_preset.groups()
        num_preset = int(num_str)
        if guardar:
            cam_activa.guardar_preset(num_preset)
            enviar_mensaje_telegram(f"💾 {cam_activa.nombre}: Posición guardada en Punto {num_preset}.")
        else:
            cam_activa.ir_a_preset(num_preset)
            time.sleep(1.5)
            _enviar_captura_camara(cam_activa, prefijo=f"📍 Punto {num_preset} |")
        return

    enviar_mensaje_telegram("❓ Comando no reconocido. Pulsa /start para actualizar los botones.")


def detener_bot():
    """Señaliza al hilo de Telegram que debe finalizar."""
    global _detener_bot
    _detener_bot = True


def iniciar_bot_comandos(camaras):
    """Hilo en segundo plano que escucha botones y comandos de Telegram."""
    global _detener_bot
    token, chat_autorizado = _obtener_credenciales()
    if not token:
        return

    _detener_bot = False

    def bucle_escucha():
        ultimo_update_id = 0
        print("[TELEGRAM] Bot PTZ con teclado táctil escuchando órdenes...")
        while not _detener_bot:
            conn = None
            try:
                ruta = f"/bot{token}/getUpdates?offset={ultimo_update_id + 1}&timeout=20"
                conn = http.client.HTTPSConnection("api.telegram.org", timeout=25)
                conn.request("GET", ruta)
                resp = conn.getresponse()
                datos = json.loads(resp.read().decode("utf-8", errors="ignore"))
                if datos.get("ok"):
                    for update in datos.get("result", []):
                        ultimo_update_id = update["update_id"]
                        msg = update.get("message", {})
                        remitente_id = str(msg.get("chat", {}).get("id", ""))
                        texto = msg.get("text", "")
                        if remitente_id == chat_autorizado and texto:
                            _procesar_comando(texto, camaras)
            except Exception:
                if not _detener_bot:
                    time.sleep(3)
            finally:
                if conn:
                    conn.close()

    threading.Thread(target=bucle_escucha, daemon=True).start()
