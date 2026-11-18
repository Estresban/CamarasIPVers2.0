"""Módulo de mantenimiento automático: retención circular de disco y armado por horario."""
from datetime import datetime
import json
import os
import threading

from config import (
    CARPETA_CAPTURAS,
    CARPETA_FOTOGRAMAS,
    CARPETA_GRABACIONES,
    RUTA_CONFIG_JSON,
)
import correo_alertas
import notificaciones


class GestorMantenimiento:
    """Supervisa el espacio en disco y arma/desarma el sistema según el horario."""

    def __init__(self, camaras):
        self.camaras = camaras
        self._evento_detener = threading.Event()
        self._ultimo_chequeo_disco = 0.0
        self._estado_horario_previo = None  # None, True (armado) o False (desarmado)

    def iniciar(self):
        threading.Thread(target=self._bucle_mantenimiento, daemon=True).start()
        print("[MANTENIMIENTO] Servicio de limpieza de disco y horario iniciado.")

    def cerrar(self):
        self._evento_detener.set()

    def _leer_reglas(self):
        """Lee límites de disco y horario desde config.json con valores por defecto seguros."""
        reglas = {
            "max_gb": 50.0,
            "horario_activo": False,
            "hora_inicio": "23:30",
            "hora_fin": "07:00",
        }
        if os.path.exists(RUTA_CONFIG_JSON):
            try:
                with open(RUTA_CONFIG_JSON, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    mant = data.get("mantenimiento", {})
                    if isinstance(mant, dict):
                        reglas["max_gb"] = float(mant.get("max_gb", reglas["max_gb"]))
                        reglas["horario_activo"] = bool(mant.get("horario_activo", reglas["horario_activo"]))
                        reglas["hora_inicio"] = str(mant.get("hora_inicio", reglas["hora_inicio"]))
                        reglas["hora_fin"] = str(mant.get("hora_fin", reglas["hora_fin"]))
            except (OSError, ValueError, json.JSONDecodeError):
                pass
        return reglas

    # --- 1. LIMPIEZA AUTOMÁTICA DE DISCO (RETENCIÓN CIRCULAR) ---
    def _limpiar_disco_si_excede(self, max_gb):
        if max_gb <= 0:
            return

        limite_bytes = max_gb * (1024 ** 3)
        objetivo_bytes = limite_bytes * 0.90  # Libera hasta dejar el 90% del límite

        archivos = []
        tamano_total = 0

        for carpeta in (CARPETA_GRABACIONES, CARPETA_CAPTURAS, CARPETA_FOTOGRAMAS):
            if not os.path.isdir(carpeta):
                continue
            for raiz, _, nombres in os.walk(carpeta):
                for nombre in nombres:
                    if not nombre.lower().endswith((".mp4", ".jpg", ".jpeg", ".avi")):
                        continue
                    ruta = os.path.join(raiz, nombre)
                    try:
                        st = os.stat(ruta)
                        tamano_total += st.st_size
                        archivos.append((st.st_mtime, st.st_size, ruta))
                    except OSError:
                        continue

        if tamano_total <= limite_bytes:
            return

        # Ordenamos de más antiguo a más reciente
        archivos.sort(key=lambda x: x[0])
        borrados = 0
        ahora = datetime.now().timestamp()

        for mtime, size, ruta in archivos:
            # No tocar archivos modificados en los últimos 2 minutos (posible grabación en curso)
            if (ahora - mtime) < 120:
                continue
            try:
                os.remove(ruta)
                tamano_total -= size
                borrados += 1
                if tamano_total <= objetivo_bytes:
                    break
            except OSError:
                continue

        if borrados > 0:
            gb_actual = tamano_total / (1024 ** 3)
            print(f"[DISCO] 🧹 Limpieza automática: {borrados} archivos antiguos eliminados (Uso: {gb_actual:.2f}/{max_gb:.1f} GB).")

    # --- 2. ARMADO Y DESARMADO AUTOMÁTICO POR HORARIO ---
    def _esta_en_horario(self, inicio_str, fin_str):
        try:
            ahora = datetime.now().time()
            h_ini = datetime.strptime(inicio_str.strip(), "%H:%M").time()
            h_fin = datetime.strptime(fin_str.strip(), "%H:%M").time()
        except ValueError:
            return False

        if h_ini <= h_fin:
            return h_ini <= ahora <= h_fin
        # Rango nocturno que cruza la medianoche (ej. 23:30 a 07:00)
        return ahora >= h_ini or ahora <= h_fin
    
    
    def obtener_estado_visual(self):
        """Devuelve una etiqueta corta para la interfaz gráfica."""
        reglas = self._leer_reglas()
        if not reglas["horario_activo"]:
            return None
        armado = self._esta_en_horario(reglas["hora_inicio"], reglas["hora_fin"])
        estado = "ARMADO" if armado else "ESPERA"
        return f"Horario: {estado} ({reglas['hora_inicio']}-{reglas['hora_fin']})"


    def _aplicar_estado_armado(self, armar):
        accion_texto = "ARMADO NOCTURNO ACTIVADO 🛡️" if armar else "DESARMADO AUTOMÁTICO DIURNO ☀️"
        print(f"[HORARIO] {accion_texto}")

        for cam in self.camaras:
            if armar:
                if not cam.deteccion_activa:
                    cam.alternar_deteccion()
                if not cam.grabador_eventos.activa:
                    cam.alternar_grab_movimiento()
            else:
                if cam.grabador_eventos.activa:
                    cam.alternar_grab_movimiento()
                if cam.deteccion_activa:
                    cam.alternar_deteccion()

        notificaciones.alertas_activas = armar
        correo_alertas.email_alertas_activas = armar

        if notificaciones.alertas_activas and armar:
            threading.Thread(
                target=notificaciones.enviar_mensaje_telegram,
                args=(f"🛡️ Sistema armado automáticamente por horario.", False),
                daemon=True,
            ).start()

    # --- BUCLE PRINCIPAL ---
    def _bucle_mantenimiento(self):
        # Espera inicial breve para dejar arrancar las cámaras
        if self._evento_detener.wait(timeout=15.0):
            return

        while not self._evento_detener.is_set():
            reglas = self._leer_reglas()

            # 1. Comprobar programación horaria cada 30 segundos
            if reglas["horario_activo"]:
                en_franja = self._esta_en_horario(reglas["hora_inicio"], reglas["hora_fin"])
                if en_franja != self._estado_horario_previo:
                    self._estado_horario_previo = en_franja
                    self._aplicar_estado_armado(en_franja)
            else:
                self._estado_horario_previo = None

            # 2. Comprobar espacio en disco cada 15 minutos (900 segundos)
            ahora_ts = datetime.now().timestamp()
            if (ahora_ts - self._ultimo_chequeo_disco) >= 900:
                self._ultimo_chequeo_disco = ahora_ts
                self._limpiar_disco_si_excede(reglas["max_gb"])

            self._evento_detener.wait(timeout=30.0)
