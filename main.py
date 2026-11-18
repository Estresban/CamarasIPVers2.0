"""
main.py
Interfaz principal para las cámaras RTSP y DVRIP.

"""

import math
import os
import sys
import threading
import numpy as np

from config import (
    ALTO_CELDA,
    ALTO_TOTAL_BASE,
    ANCHO_CELDA,
    ANCHO_TOTAL_BASE,
    CARPETAS_SALIDA,
    CONFIG_CAMARAS_RTSP,
    CONFIG_PATIO,
    DIR_DATOS,
    MODO_MOSAICO,
)

# 1. Evita que FFmpeg / OpenCV creen archivos .log sueltos o muestren ruido innecesario
os.environ["OPENCV_FFMPEG_LOGLEVEL"] = "-8"
os.environ["OPENCV_LOG_LEVEL"] = "ERROR"

# 2. Fuerza que cualquier archivo temporal o log residual se cree dentro de camarasIP
os.chdir(DIR_DATOS)

import cv2
from camaras import CamaraDVRIP, CamaraRTSP
import configuracion
import correo_alertas
import notificaciones
from watchdog import WatchdogCamaras
import logger
from mantenimiento import GestorMantenimiento

logger.configurar_logs()

VENTANA = "Sistema de videovigilancia de StiVi-Home"
ANCHO_PANEL = 360

CAMARAS = []
seleccionada = 0
vista_ampliada = False
salir_panel = False
ventana_config_abierta = False
raton_panel = (-1, -1)


def preparar_carpetas():
    """Crea las carpetas de salida antes de iniciar la captura."""
    for carpeta in CARPETAS_SALIDA:
        os.makedirs(carpeta, exist_ok=True)


def iniciar_camaras():
    """Instancia las cámaras RTSP y la cámara DVRIP del patio."""
    camaras = []

    for indice, cfg in enumerate(CONFIG_CAMARAS_RTSP):
        try:
            print(f"[MAIN] Iniciando cámara RTSP: {cfg['nombre']}")
            camaras.append(CamaraRTSP(cfg, indice))
        except Exception as exc:
            print(f"[MAIN] No se pudo iniciar {cfg.get('nombre', indice)}: {exc}")

    try:
        indice = len(camaras)
        print(f"[MAIN] Iniciando cámara DVRIP: {CONFIG_PATIO['nombre']}")
        camaras.append(CamaraDVRIP(CONFIG_PATIO, indice))
    except Exception as exc:
        print(f"[MAIN] No se pudo iniciar Patio: {exc}")

    return camaras


def dibujar_interfaz(camaras, indice_activo):
    """Compone el mosaico dinámico de 1, 2 o 4 cámaras sobre el lienzo base."""
    lienzo = np.zeros((ALTO_TOTAL_BASE, ANCHO_TOTAL_BASE, 3), dtype=np.uint8)
    cols, filas, w_celda, h_celda = obtener_geometria_mosaico()
    total_celdas = cols * filas

    # Si estamos en modo de 1 cámara o vista ampliada, mostramos la cámara seleccionada
    if total_celdas == 1:
        idx = indice_activo if 0 <= indice_activo < len(camaras) else 0
        if idx < len(camaras):
            try:
                imagen = camaras[idx].obtener_imagen_ui(seleccionada=True)
            except Exception as exc:
                imagen = np.zeros((ALTO_TOTAL_BASE, ANCHO_TOTAL_BASE, 3), dtype=np.uint8)
                cv2.putText(
                    imagen, f"Error mostrando cámara: {exc}",
                    (30, 360), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2, cv2.LINE_AA
                )
            lienzo = cv2.resize(imagen, (ANCHO_TOTAL_BASE, ALTO_TOTAL_BASE), interpolation=cv2.INTER_LINEAR)
            if vista_ampliada and MODO_MOSAICO > 1:
                cv2.putText(
                    lienzo, "[DOBLE CLIC / ENTER: Volver al mosaico]",
                    (16, ALTO_TOTAL_BASE - 16), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2, cv2.LINE_AA
                )
        return lienzo

    # Mosaico de 2 (lado a lado) o 4 (cuadrícula 2x2)
    for pos in range(total_celdas):
        col = pos % cols
        fila = pos // cols
        x = col * w_celda
        y = fila * h_celda

        if pos < len(camaras):
            try:
                imagen = camaras[pos].obtener_imagen_ui(seleccionada=(pos == indice_activo))
            except Exception as exc:
                imagen = np.zeros((h_celda, w_celda, 3), dtype=np.uint8)
                cv2.putText(
                    imagen, f"Error mostrando cámara: {exc}",
                    (15, h_celda // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1, cv2.LINE_AA
                )
        else:
            imagen = np.zeros((h_celda, w_celda, 3), dtype=np.uint8)
            cv2.putText(
                imagen, "Sin cámara configurada", (max(20, w_celda // 4), h_celda // 2),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (130, 130, 130), 2
            )

        if imagen.shape[1] != w_celda or imagen.shape[0] != h_celda:
            imagen = cv2.resize(imagen, (w_celda, h_celda), interpolation=cv2.INTER_LINEAR)

        lienzo[y:y + h_celda, x:x + w_celda] = imagen
        cv2.rectangle(lienzo, (x, y), (x + w_celda - 1, y + h_celda - 1), (75, 75, 75), 1)

    return lienzo


# ---------------------------------------------------------------------
# Control por teclado
# ---------------------------------------------------------------------

FLECHAS_IZQ = (81, 65361, 2424832)
FLECHAS_ARR = (82, 65362, 2490368)
FLECHAS_DER = (83, 65363, 2555904)
FLECHAS_ABA = (84, 65364, 2621440)
TODAS_LAS_FLECHAS = FLECHAS_IZQ + FLECHAS_ARR + FLECHAS_DER + FLECHAS_ABA

def obtener_geometria_mosaico():
    """Devuelve (cols, filas, ancho_celda, alto_celda) para mosaicos de 1, 2 o 4 cámaras."""
    if vista_ampliada or MODO_MOSAICO == 1:
        return 1, 1, ANCHO_TOTAL_BASE, ALTO_TOTAL_BASE
    if MODO_MOSAICO == 2:
        return 2, 1, ANCHO_TOTAL_BASE // 2, ALTO_TOTAL_BASE
    return 2, 2, ANCHO_CELDA, ALTO_CELDA


def mover_ptz(camara, tecla):
    """Movimiento breve PTZ con las flechas del teclado."""
    if tecla in FLECHAS_IZQ:
        camara.mover_ptz(0.5, 0.0, 0.0)
    elif tecla in FLECHAS_ARR:
        camara.mover_ptz(0.0, 0.5, 0.0)
    elif tecla in FLECHAS_DER:
        camara.mover_ptz(-0.5, 0.0, 0.0)
    elif tecla in FLECHAS_ABA:
        camara.mover_ptz(0.0, -0.5, 0.0)


def cambiar_camara_siguiente():
    """Rota la selección a la siguiente cámara disponible."""
    global seleccionada
    if CAMARAS:
        seleccionada = (seleccionada + 1) % len(CAMARAS)

def controlar_camara(camara, tecla):
    """Aplica atajos de teclado sobre la cámara seleccionada."""
    acciones_tecla = {
        ord("w"): lambda: camara.mover_ptz(0.0, 0.5, 0.0),
        ord("a"): lambda: camara.mover_ptz(0.0, -0.5, 0.0),
        ord("s"): lambda: camara.mover_ptz(0.5, 0.0, 0.0),
        ord("d"): lambda: camara.mover_ptz(-0.5, 0.0, 0.0),
        ord("m"): camara.alternar_deteccion,
        ord("r"): camara.alternar_grabacion,
        ord("f"): camara.alternar_captura_auto,
        ord(" "): camara.capturar_fotograma_manual,
        ord("v"): camara.alternar_escuchar_audio,
        ord("t"): camara.alternar_hablar_micro,
        ord("+"): lambda: camara.cambiar_zoom(0.2),
        ord("z"): lambda: camara.cambiar_zoom(0.2),
        ord("-"): lambda: camara.cambiar_zoom(-0.2),
        ord("x"): lambda: camara.cambiar_zoom(-0.2),
        ord("1"): lambda: camara.cambiar_luz_led("BLANCA"),
        ord("l"): lambda: camara.cambiar_luz_led("BLANCA"),
        ord("2"): lambda: camara.cambiar_luz_led("IR"),
        ord("i"): lambda: camara.cambiar_luz_led("IR"),
        ord("3"): lambda: camara.cambiar_luz_led("AUTO"),
        ord("o"): lambda: camara.cambiar_luz_led("AUTO"),
        ord("e"): correo_alertas.alternar_alertas_correo,
        ord("n"): notificaciones.alternar_alertas,
        # Ir a Presets 1, 2, 3
        ord("4"): lambda: camara.ir_a_preset(1),
        ord("5"): lambda: camara.ir_a_preset(2),
        ord("6"): lambda: camara.ir_a_preset(3),
        # Guardar posición actual en Presets 1, 2, 3
        ord("7"): lambda: camara.guardar_preset(1),
        ord("8"): lambda: camara.guardar_preset(2),
        ord("9"): lambda: camara.guardar_preset(3),
        ord("\t"): lambda:cambiar_camara_siguiente(),

    }

    tecla_norm = ord(chr(tecla).lower()) if 65 <= tecla <= 90 else tecla
    accion = acciones_tecla.get(tecla_norm)
    if accion:
        accion()


# ---------------------------------------------------------------------
# Panel gráfico lateral y eventos de ratón
# ---------------------------------------------------------------------

BOTONES_PANEL = [
    ("ARRIBA",          105,  82, 255, 122, "arriba"),
    ("IZQUIERDA",        15, 128, 165, 168, "izquierda"),
    ("DERECHA",         195, 128, 345, 168, "derecha"),
    ("ABAJO",           105, 174, 255, 214, "abajo"),
    ("ZOOM  +",          15, 232, 165, 276, "zoom_mas"),
    ("ZOOM  -",         195, 232, 345, 276, "zoom_menos"),
    ("DETECCIÓN",        15, 298, 165, 342, "deteccion"),
    ("GRABACIÓN",       195, 298, 345, 342, "grabacion"),
    ("CAPTURA AUTO",     15, 354, 165, 398, "captura_auto"),
    ("FOTO MANUAL",     195, 354, 345, 398, "foto"),
    ("ESCUCHAR AUDIO",   15, 410, 165, 454, "audio"),
    ("MICRÓFONO",       195, 410, 345, 454, "micro"),
    ("LUZ BLANCA",       15, 478, 125, 522, "luz_blanca"),
    ("INFRARROJOS",     132, 478, 232, 522, "luz_ir"),
    ("LUZ AUTO",        240, 478, 345, 522, "luz_auto"),
    ("ALERTAS MOVIL",    15, 555, 125, 605, "alertas"),
    ("ALERTAS EMAIL",   132, 555, 232, 605, "alertas_email"),
    ("CONFIGURACION",   240, 555, 345, 605, "configuracion"),
    ("GRAB MOVIMIENTO",  15, 614, 345, 650, "grab_mov"),
    ("CERRAR",           15, 660, 345, 710, "salir"),
]


def dibujar_icono(panel, accion, cx, cy, activo):
    """Dibuja iconos vectoriales limpios usando primitivas de OpenCV."""
    blanco = (255, 255, 255)
    rojo_tachado = (80, 80, 255)

    if accion in ("arriba", "abajo", "izquierda", "derecha"):
        d = 9
        if accion == "arriba":
            pts = np.array([[cx, cy - d], [cx - d, cy + d - 3], [cx + d, cy + d - 3]])
        elif accion == "abajo":
            pts = np.array([[cx, cy + d], [cx - d, cy - d + 3], [cx + d, cy - d + 3]])
        elif accion == "izquierda":
            pts = np.array([[cx - d, cy], [cx + d - 3, cy - d], [cx + d - 3, cy + d]])
        else:
            pts = np.array([[cx + d, cy], [cx - d + 3, cy - d], [cx - d + 3, cy + d]])
        cv2.fillPoly(panel, [pts], blanco, cv2.LINE_AA)

    elif accion in ("zoom_mas", "zoom_menos"):
        cv2.circle(panel, (cx - 2, cy - 2), 7, blanco, 2, cv2.LINE_AA)
        cv2.line(panel, (cx + 3, cy + 3), (cx + 9, cy + 9), blanco, 2, cv2.LINE_AA)
        cv2.line(panel, (cx - 5, cy - 2), (cx + 1, cy - 2), blanco, 2, cv2.LINE_AA)
        if accion == "zoom_mas":
            cv2.line(panel, (cx - 2, cy - 5), (cx - 2, cy + 1), blanco, 2, cv2.LINE_AA)

    elif accion == "deteccion":
        cv2.ellipse(panel, (cx, cy), (11, 6), 0, 0, 360, blanco, 2, cv2.LINE_AA)
        cv2.circle(panel, (cx, cy), 3, blanco, -1, cv2.LINE_AA)

    elif accion == "grabacion":
        color_rec = (255, 255, 255) if activo else (180, 180, 220)
        cv2.circle(panel, (cx, cy), 7, color_rec, -1, cv2.LINE_AA)
        cv2.circle(panel, (cx, cy), 10, blanco, 1, cv2.LINE_AA)

    elif accion in ("captura_auto", "foto"):
        cv2.rectangle(panel, (cx - 10, cy - 5), (cx + 10, cy + 7), blanco, 2, cv2.LINE_AA)
        cv2.rectangle(panel, (cx - 4, cy - 8), (cx + 4, cy - 5), blanco, -1, cv2.LINE_AA)
        cv2.circle(panel, (cx, cy + 1), 3, blanco, 2, cv2.LINE_AA)

    elif accion == "audio":
        pts = np.array([[cx - 9, cy - 3], [cx - 4, cy - 3], [cx + 2, cy - 8],
                        [cx + 2, cy + 8], [cx - 4, cy + 3], [cx - 9, cy + 3]])
        cv2.fillPoly(panel, [pts], blanco, cv2.LINE_AA)
        if activo:
            cv2.ellipse(panel, (cx + 3, cy), (4, 6), 0, -60, 60, blanco, 2, cv2.LINE_AA)
            cv2.ellipse(panel, (cx + 3, cy), (8, 10), 0, -60, 60, blanco, 2, cv2.LINE_AA)

    elif accion == "micro":
        cv2.rectangle(panel, (cx - 3, cy - 9), (cx + 3, cy + 1), blanco, -1, cv2.LINE_AA)
        cv2.ellipse(panel, (cx, cy), (6, 6), 0, 0, 180, blanco, 2, cv2.LINE_AA)
        cv2.line(panel, (cx, cy + 6), (cx, cy + 10), blanco, 2, cv2.LINE_AA)
        cv2.line(panel, (cx - 5, cy + 10), (cx + 5, cy + 10), blanco, 2, cv2.LINE_AA)

    elif accion.startswith("luz_"):
        cv2.circle(panel, (cx, cy - 3), 6, blanco, 2 if not activo else -1, cv2.LINE_AA)
        cv2.rectangle(panel, (cx - 3, cy + 3), (cx + 3, cy + 7), blanco, -1, cv2.LINE_AA)
        if activo:
            for ang in (-45, 0, 45, 135, 180, 225):
                rad = math.radians(ang)
                cv2.line(
                    panel,
                    (int(cx + 8 * math.cos(rad)), int(cy - 3 + 8 * math.sin(rad))),
                    (int(cx + 11 * math.cos(rad)), int(cy - 3 + 11 * math.sin(rad))),
                    blanco, 1, cv2.LINE_AA,
                )

    elif accion == "configuracion":
        cv2.circle(panel, (cx, cy), 6, blanco, 2, cv2.LINE_AA)
        cv2.circle(panel, (cx, cy), 2, blanco, -1, cv2.LINE_AA)
        for i in range(8):
            ang = math.radians(i * 45)
            cv2.line(
                panel,
                (int(cx + 6 * math.cos(ang)), int(cy + 6 * math.sin(ang))),
                (int(cx + 9 * math.cos(ang)), int(cy + 9 * math.sin(ang))),
                blanco, 2, cv2.LINE_AA,
            )

    elif accion == "alertas_email":
        cv2.rectangle(panel, (cx - 10, cy - 6), (cx + 10, cy + 6), blanco, 2, cv2.LINE_AA)
        cv2.line(panel, (cx - 10, cy - 6), (cx, cy + 1), blanco, 2, cv2.LINE_AA)
        cv2.line(panel, (cx + 10, cy - 6), (cx, cy + 1), blanco, 2, cv2.LINE_AA)

    elif accion == "alertas":
        cv2.ellipse(panel, (cx, cy + 2), (7, 9), 0, 180, 360, blanco, -1, cv2.LINE_AA)
        cv2.line(panel, (cx - 9, cy + 3), (cx + 9, cy + 3), blanco, 2, cv2.LINE_AA)
        cv2.circle(panel, (cx, cy + 6), 2, blanco, -1, cv2.LINE_AA)

    elif accion == "grab_mov":
        cv2.circle(panel, (cx, cy), 7, blanco, -1 if activo else 2, cv2.LINE_AA)
        cv2.circle(panel, (cx, cy), 10, blanco, 1, cv2.LINE_AA)

    elif accion == "salir":
        cv2.line(panel, (cx - 7, cy - 7), (cx + 7, cy + 7), blanco, 2, cv2.LINE_AA)
        cv2.line(panel, (cx + 7, cy - 7), (cx - 7, cy + 7), blanco, 2, cv2.LINE_AA)

    botones_con_tachado = (
        "audio", "micro", "deteccion", "grabacion",
        "captura_auto", "alertas", "alertas_email", "grab_mov",
    )
    if accion in botones_con_tachado and not activo:
        cv2.line(panel, (cx - 11, cy - 11), (cx + 11, cy + 11), rojo_tachado, 2, cv2.LINE_AA)


def dibujar_boton_redondeado(img, x1, y1, x2, y2, radio, color_fondo, color_borde, grosor=1):
    """Dibuja un rectángulo con esquinas redondeadas usando primitivas de OpenCV."""
    cv2.rectangle(img, (x1 + radio, y1), (x2 - radio, y2), color_fondo, -1)
    cv2.rectangle(img, (x1, y1 + radio), (x2, y2 - radio), color_fondo, -1)

    esquinas = [
        (x1 + radio, y1 + radio, 180, 270),
        (x2 - radio, y1 + radio, 270, 360),
        (x2 - radio, y2 - radio, 0, 90),
        (x1 + radio, y2 - radio, 90, 180),
    ]
    for cx, cy, ang_ini, ang_fin in esquinas:
        cv2.circle(img, (cx, cy), radio, color_fondo, -1, cv2.LINE_AA)
        if color_borde is not None:
            cv2.ellipse(img, (cx, cy), (radio, radio), 0, ang_ini, ang_fin, color_borde, grosor, cv2.LINE_AA)

    if color_borde is not None:
        cv2.line(img, (x1 + radio, y1), (x2 - radio, y1), color_borde, grosor, cv2.LINE_AA)
        cv2.line(img, (x1 + radio, y2), (x2 - radio, y2), color_borde, grosor, cv2.LINE_AA)
        cv2.line(img, (x1, y1 + radio), (x1, y2 - radio), color_borde, grosor, cv2.LINE_AA)
        cv2.line(img, (x2, y1 + radio), (x2, y2 - radio), color_borde, grosor, cv2.LINE_AA)


def dibujar_panel(indice_activo, camaras, mantenimiento=None):
    """Crea el panel lateral con botones redondeados, iconos y efecto hover."""
    panel = np.full((ALTO_TOTAL_BASE, ANCHO_PANEL, 3), (50, 40, 32), dtype=np.uint8)

    cv2.putText(panel, "PANEL DE CONTROL", (22, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.78, (245, 245, 245), 2, cv2.LINE_AA)
    cv2.putText(panel, f"Camara seleccionada: {indice_activo + 1}/{len(camaras)}",
                (18, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1, cv2.LINE_AA)

    texto_horario = mantenimiento.obtener_estado_visual() if mantenimiento else None
    if texto_horario:
        color_h = (80, 230, 100) if "ARMADO" in texto_horario else (180, 190, 200)
        cv2.putText(panel, texto_horario, (18, 71),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, color_h, 1, cv2.LINE_AA)


    camara = camaras[indice_activo] if 0 <= indice_activo < len(camaras) else None
    estados = {}
    if camara is not None:
        modo_luz = str(camara.modo_luz_actual).upper()
        estados = {
            "deteccion": camara.deteccion_activa,
            "grabacion": camara.grabando,
            "captura_auto": camara.captura_auto_activa,
            "audio": camara.escuchando_audio,
            "micro": camara.hablando_micro,
            "luz_blanca": modo_luz in ("BLANCA", "WHITE"),
            "luz_ir": modo_luz in ("IR", "INFRARROJA", "INFRARROJOS"),
            "luz_auto": modo_luz in ("AUTO", "AUTOMATICO", "AUTOMÁTICO"),
            "grab_mov": camara.grabador_eventos.activa,
        }
    estados["alertas"] = notificaciones.alertas_activas
    estados["alertas_email"] = correo_alertas.email_alertas_activas
    etiquetas_visuales = {
        "zoom_mas": "ZOOM +",
        "zoom_menos": "ZOOM -",
        "luz_blanca": "BLANCA",
        "luz_ir": "IR",
        "luz_auto": "AUTO",
        "audio": "AUDIO",
        "micro": "MICRO",
        "deteccion": "DETECCION",
        "grabacion": "GRABAR",
        "captura_auto": "AUTO FOTO",
        "foto": "FOTO",
        "alertas": "TELEGRAM",
        "alertas_email": "EMAIL",
        "configuracion": "AJUSTES",
        "grab_mov": "GRAB MOV (PRE-BUFFER)",
    }

    mx, my = raton_panel
    radio_esquina = 10

    for texto, x1, y1, x2, y2, accion in BOTONES_PANEL:
        activo = estados.get(accion, False)
        encima = (x1 <= mx <= x2) and (y1 <= my <= y2)

        color = (128, 72, 58)
        if activo:
            color = (40, 150, 55)
        if accion == "salir":
            color = (45, 50, 175)
        elif accion.startswith("luz_") and not activo:
            color = (68, 82, 62)

        if encima:
            color = tuple(min(255, c + 30) for c in color)
            borde = (255, 255, 255)
            grosor_borde = 2
        else:
            borde = (120, 230, 130) if activo else (130, 140, 155)
            grosor_borde = 1

        dibujar_boton_redondeado(panel, x1 + 2, y1 + 3, x2 + 2, y2 + 3, radio_esquina, (20, 20, 20), None)
        dibujar_boton_redondeado(panel, x1, y1, x2, y2, radio_esquina, color, borde, grosor_borde)

        if accion in ("arriba", "abajo", "izquierda", "derecha"):
            dibujar_icono(panel, accion, (x1 + x2) // 2, (y1 + y2) // 2, True)
            continue

        dibujar_icono(panel, accion, x1 + 20, (y1 + y2) // 2, activo)

        texto_mostrar = etiquetas_visuales.get(accion, texto)
        escala = 0.42 if len(texto_mostrar) > 9 else 0.48
        tam, _ = cv2.getTextSize(texto_mostrar, cv2.FONT_HERSHEY_SIMPLEX, escala, 1)

        zona_texto_x1 = x1 + 36
        tx = zona_texto_x1 + max(2, (x2 - zona_texto_x1 - tam[0]) // 2)
        ty = y1 + (y2 - y1 + tam[1]) // 2
        cv2.putText(panel, texto_mostrar, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, escala, (255, 255, 255), 1, cv2.LINE_AA)

    return panel


def abrir_configuracion_hilo():
    """Abre la ventana Tkinter sin bloquear el vídeo ni usar subprocess."""
    global ventana_config_abierta
    if ventana_config_abierta:
        return
    ventana_config_abierta = True
    try:
        configuracion.iniciar()
    except Exception as exc:
        print(f"[CONFIG] Error en ventana de configuración: {exc}")
    finally:
        ventana_config_abierta = False


def ejecutar_accion_panel(accion, camaras):
    """Ejecuta la acción del botón sobre la cámara seleccionada."""
    if accion == "salir":
        return False
    if accion == "alertas":
        notificaciones.alternar_alertas()
        return True
    if accion == "alertas_email":
        correo_alertas.alternar_alertas_correo()
        return True
    if accion == "configuracion":
        threading.Thread(target=abrir_configuracion_hilo, daemon=True).start()
        return True
    if not camaras or seleccionada >= len(camaras):
        return True

    camara = camaras[seleccionada]
    acciones = {
        "arriba": lambda: camara.mover_ptz(0, 0.5, 0),
        "abajo": lambda: camara.mover_ptz(0, -0.5, 0),
        "izquierda": lambda: camara.mover_ptz(0.5, 0, 0),
        "derecha": lambda: camara.mover_ptz(-0.5, 0, 0),
        "zoom_mas": lambda: camara.cambiar_zoom(0.2),
        "zoom_menos": lambda: camara.cambiar_zoom(-0.2),
        "deteccion": camara.alternar_deteccion,
        "grabacion": camara.alternar_grabacion,
        "captura_auto": camara.alternar_captura_auto,
        "foto": camara.capturar_fotograma_manual,
        "audio": camara.alternar_escuchar_audio,
        "micro": camara.alternar_hablar_micro,
        "luz_blanca": lambda: camara.cambiar_luz_led("BLANCA"),
        "luz_ir": lambda: camara.cambiar_luz_led("IR"),
        "luz_auto": lambda: camara.cambiar_luz_led("AUTO"),
        "grab_mov": camara.alternar_grab_movimiento,
    }
    try:
        funcion = acciones.get(accion)
        if funcion:
            funcion()
    except Exception as exc:
        print(f"[PANEL] Error ejecutando {accion}: {exc}")
    return True


def al_hacer_clic_camaras(evento, x, y, camaras):
    """Selecciona celda (1 clic) o alterna vista ampliada (doble clic) según el mosaico."""
    global seleccionada, vista_ampliada

    if evento == cv2.EVENT_LBUTTONDBLCLK:
        if MODO_MOSAICO == 1:
            return
        if vista_ampliada:
            vista_ampliada = False
            return
        cols, _filas, w_celda, h_celda = obtener_geometria_mosaico()
        indice = (y // h_celda) * cols + (x // w_celda)
        if indice < len(camaras):
            seleccionada = indice
            vista_ampliada = True
        return

    if evento == cv2.EVENT_LBUTTONDOWN and not vista_ampliada and MODO_MOSAICO > 1:
        cols, _filas, w_celda, h_celda = obtener_geometria_mosaico()
        indice = (y // h_celda) * cols + (x // w_celda)
        if indice < len(camaras):
            seleccionada = indice



def al_hacer_clic_panel(evento, x, y, camaras):
    """Gestiona el hover y los clics sobre el panel lateral."""
    global salir_panel, raton_panel
    raton_panel = (x, y)

    if evento != cv2.EVENT_LBUTTONDOWN:
        return
    for _, x1, y1, x2, y2, accion in BOTONES_PANEL:
        if x1 <= x <= x2 and y1 <= y <= y2:
            if not ejecutar_accion_panel(accion, camaras):
                salir_panel = True
            break


def cerrar_camaras(camaras):
    """Detiene todas las cámaras de forma segura."""
    print("\n[MAIN] Cerrando cámaras...")
    for camara in camaras:
        try:
            camara.cerrar()
            notificaciones.detener_bot()
            print(f"[MAIN] {camara.nombre}: cerrada.")
        except Exception as exc:
            print(f"[MAIN] Error cerrando {camara.nombre}: {exc}")

    try:
        cv2.destroyAllWindows()
    except Exception:
        pass


def main():
    global CAMARAS, seleccionada, salir_panel, vista_ampliada

    preparar_carpetas()
    CAMARAS = iniciar_camaras()

    if not CAMARAS:
        print("[MAIN] No se ha podido inicializar ninguna cámara.")
        return

    notificaciones.iniciar_bot_comandos(CAMARAS)
    watchdog = WatchdogCamaras(CAMARAS, timeout_seg = 8.0, umbral_alerta_seg = 180.0)
    watchdog.iniciar()
    mantenimiento = GestorMantenimiento(CAMARAS)
    mantenimiento.iniciar()

    seleccionada = 0
    salir_panel = False

    cv2.namedWindow(VENTANA, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(VENTANA, ANCHO_TOTAL_BASE + ANCHO_PANEL, ALTO_TOTAL_BASE)

    if sys.platform.startswith("win"):
        try:
            import ctypes
            hwnd = ctypes.windll.user32.FindWindowW(None, VENTANA)
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 3)
        except Exception:
            pass
    else:
        cv2.setWindowProperty(VENTANA, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    def gestionar_raton(evento, x, y, _flags, params):
        global raton_panel
        if x >= ANCHO_TOTAL_BASE:
            al_hacer_clic_panel(evento, x - ANCHO_TOTAL_BASE, y, params)
        else:
            raton_panel = (-1, -1)
            al_hacer_clic_camaras(evento, x, y, params)

    cv2.setMouseCallback(VENTANA, gestionar_raton, CAMARAS)

    print("\n========== CONTROLES ==========")
    print("Panel lateral: clic en los botones")
    print("Ratón: seleccionar cámara (doble clic amplía)")
    print("Flechas / WASD: mover PTZ | +/-: zoom")
    print("M: detección | R: grabación | F: captura auto")
    print("Espacio: foto | V: audio | T: micrófono")
    print("1/2/3: luz blanca / IR / auto")
    print("Q / ESC: salir")
    print("===============================\n")

    try:
        while not salir_panel:
            lienzo_camaras = dibujar_interfaz(CAMARAS, seleccionada)
            panel = dibujar_panel(seleccionada, CAMARAS, mantenimiento)
            cv2.imshow(VENTANA, np.hstack((lienzo_camaras, panel)))

            tecla = cv2.waitKeyEx(30)
            try:
                if cv2.getWindowProperty(VENTANA, cv2.WND_PROP_VISIBLE) < 1:
                    break
            except cv2.error:
                break

            if tecla == -1:
                continue

            tecla_ascii = tecla & 0xFF
            if tecla_ascii == 27 and vista_ampliada:
                vista_ampliada = False
                continue
            if tecla_ascii in (27, ord("q"), ord("Q")):
                break
            if tecla_ascii == 13:
                vista_ampliada = not vista_ampliada
                continue

            if 0 <= seleccionada < len(CAMARAS):
                camara = CAMARAS[seleccionada]
                if tecla in TODAS_LAS_FLECHAS:
                    mover_ptz(camara, tecla)
                else:
                    controlar_camara(camara, tecla_ascii)

    except KeyboardInterrupt:
        print("\n[MAIN] Interrupción recibida.")
    finally:
        watchdog.cerrar()
        mantenimiento.cerrar()
        cerrar_camaras(CAMARAS)


if __name__ == "__main__":
    main()
