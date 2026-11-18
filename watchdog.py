"""Módulo Watchdog para detectar flujos caídos, reconectarlos y notificar salud."""
import threading
import time
import numpy as np

import notificaciones


class WatchdogCamaras:
    """Supervisa todas las cámaras, fuerza su reconexión y avisa si hay caídas prolongadas."""

    def __init__(self, camaras, timeout_seg=8.0, intervalo_revision=3.0, umbral_alerta_seg=180.0):
        self.camaras = camaras
        self.timeout_seg = timeout_seg
        self.intervalo_revision = intervalo_revision
        self.umbral_alerta_seg = umbral_alerta_seg
        self._evento_detener = threading.Event()
        self._estado = {}

    def iniciar(self):
        threading.Thread(target=self._bucle_vigilancia, daemon=True).start()
        print(f"[WATCHDOG] Supervisión activa (reconexión: {self.timeout_seg}s | alerta: {self.umbral_alerta_seg}s)")

    def cerrar(self):
        """Detiene inmediatamente la espera del hilo de supervisión."""
        self._evento_detener.set()

    def _firma_rapida(self, frame):
        """Calcula una huella ligera del fotograma para detectar si está congelado."""
        if frame is None:
            return None
        muestra = frame[::32, ::32]
        return int(np.sum(muestra, dtype=np.uint64))

    def _notificar_salud(self, texto):
        """Envía el aviso de salud a Telegram en un hilo independiente para no frenar el watchdog."""
        if notificaciones.alertas_activas:
            threading.Thread(
                target=notificaciones.enviar_mensaje_telegram,
                args=(texto, False),
                daemon=True,
            ).start()

    def _bucle_vigilancia(self):
        if self._evento_detener.wait(timeout=10.0):
            return

        while not self._evento_detener.is_set():
            ahora = time.time()

            for idx, cam in enumerate(self.camaras):
                if getattr(cam, "detener", False):
                    continue

                frame_actual = getattr(cam, "frame", None)
                firma = self._firma_rapida(frame_actual)

                info = self._estado.setdefault(
                    idx,
                    {
                        "firma": firma,
                        "ultimo_cambio": ahora,
                        "reiniciando": False,
                        "inicio_caida": None,
                        "alerta_enviada": False,
                    },
                )

                # --- CASO 1: LA CÁMARA ESTÁ VIVA Y EMITIENDO VÍDEO NUEVO ---
                if firma is not None and firma != info["firma"]:
                    if info["alerta_enviada"] and info["inicio_caida"] is not None:
                        minutos = int((ahora - info["inicio_caida"]) // 60)
                        print(f"[SALUD] ✅ {cam.nombre} ha recuperado la conexión tras {minutos} min.")
                        self._notificar_salud(
                            f"✅ CÁMARA RECUPERADA\n• {cam.nombre} vuelve a estar en línea (estuvo {minutos} min caída)."
                        )

                    info["firma"] = firma
                    info["ultimo_cambio"] = ahora
                    info["reiniciando"] = False
                    info["inicio_caida"] = None
                    info["alerta_enviada"] = False
                    continue

                # --- CASO 2: LA CÁMARA ESTÁ CONGELADA O SIN SEÑAL ---
                if info["inicio_caida"] is None:
                    info["inicio_caida"] = info["ultimo_cambio"]

                tiempo_parada = ahora - info["ultimo_cambio"]
                tiempo_total_caida = ahora - info["inicio_caida"]

                # Intento automático de reconexión
                if tiempo_parada >= self.timeout_seg and not info["reiniciando"]:
                    info["reiniciando"] = True
                    info["ultimo_cambio"] = ahora
                    print(f"[WATCHDOG] ⚠️ {cam.nombre} sin señal ({tiempo_parada:.1f}s). Reconectando...")

                    if hasattr(cam, "forzar_reconexion"):
                        threading.Thread(target=cam.forzar_reconexion, daemon=True).start()

                # Aviso único de salud si supera el umbral (ej. 3 minutos caída)
                if tiempo_total_caida >= self.umbral_alerta_seg and not info["alerta_enviada"]:
                    info["alerta_enviada"] = True
                    minutos = int(tiempo_total_caida // 60)
                    print(f"[SALUD] 🚨 Alerta prolongada: {cam.nombre} lleva {minutos} min desconectada.")
                    self._notificar_salud(
                        f"🚨 FALLO DE SALUD EN CÁMARA\n• {cam.nombre} lleva más de {minutos} minutos sin señal."
                    )

            self._evento_detener.wait(timeout=self.intervalo_revision)
