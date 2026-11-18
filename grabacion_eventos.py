"""Módulo independiente para grabación por movimiento con pre-buffer circular."""
from collections import deque
from datetime import datetime
import os
import threading
import time
import cv2

from config import ALTO_CELDA, ANCHO_CELDA, CARPETA_GRABACIONES
from correo_alertas import enviar_video_correo
from notificaciones import enviar_video_evento

from escritor_video import EscritorVideoH264

class GrabadorEventos:
    """Gestiona un búfer circular en RAM y guarda clips ante detección de movimiento."""

    def __init__(self, nombre_camara, seg_prebuffer=5, seg_postevento=15, fps=20.0):
        self.nombre = nombre_camara
        self.nombre_archivo = self.nombre.replace(" ", "_")
        self.fps = fps
        self.seg_postevento = seg_postevento

        self.activa = False
        self.grabando_ahora = False

        # Búfer circular en memoria (5 seg * 20 fps = 100 fotogramas)
        self.prebuffer = deque(maxlen=int(seg_prebuffer * fps))
        self.writer = None
        self.ruta_actual = None
        self.fin_grabacion = 0
        self.lock = threading.Lock()

    def alternar(self):
        """Activa o desactiva el modo de espera con pre-buffer de forma segura."""
        with self.lock:
            self.activa = not self.activa
            if not self.activa:
                self._limpiar_sin_lock()
            estado = "ACTIVADA" if self.activa else "DESACTIVADA"
            print(f"[{self.nombre}] Grabación por movimiento (Pre-buffer): {estado}")
            return self.activa

    
    def procesar_audio(self, raw_bytes):
        """Escribe audio en el clip del evento mientras está grabando."""
        with self.lock:
            if self.grabando_ahora and self.writer is not None:
                self.writer.write_audio(raw_bytes)
    
    
    
    def procesar_frame(self, frame, hay_movimiento):
        """Debe llamarse en cada fotograma recibido por el hilo de la cámara."""
        ruta_para_enviar = None

        with self.lock:
            if not self.activa:
                return

            ahora = time.time()

            # Si detecta movimiento, inicia el clip volcando el pre-buffer o prolonga 15s
            if hay_movimiento:
                self.fin_grabacion = ahora + self.seg_postevento
                if self.writer is None:
                    os.makedirs(CARPETA_GRABACIONES, exist_ok=True)
                    fecha_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                    nombre_mp4 = f"EVENTO_{self.nombre_archivo}_{fecha_str}.mp4"
                    self.ruta_actual = os.path.join(CARPETA_GRABACIONES, nombre_mp4)

                    #fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                    #self.writer = cv2.VideoWriter(self.ruta_actual, fourcc, self.fps, (ANCHO_CELDA, ALTO_CELDA))
                    self.writer = EscritorVideoH264(self.ruta_actual, self.fps, ANCHO_CELDA, ALTO_CELDA, con_audio=True)
                    
                    for f_previo in self.prebuffer:
                        self.writer.write(f_previo)
                    self.prebuffer.clear()

                    self.grabando_ahora = True
                    print(f"[{self.nombre}] Grabando clip con pre-buffer -> {self.ruta_actual}")

            # Escritura activa del clip o almacenamiento en el búfer circular
            if self.writer is not None:
                if ahora <= self.fin_grabacion:
                    self.writer.write(frame)
                else:
                    self.writer.release()
                    self.writer = None
                    self.grabando_ahora = False
                    print(f"[{self.nombre}] Clip de evento finalizado: {self.ruta_actual}")
                    ruta_para_enviar = self.ruta_actual
                    self.ruta_actual = None
            else:
                self.prebuffer.append(frame.copy())

        # Los envíos de red se lanzan fuera del lock para no frenar el hilo de vídeo
        if ruta_para_enviar:
            enviar_video_evento(ruta_para_enviar, self.nombre)
            enviar_video_correo(ruta_para_enviar, self.nombre)

    def _limpiar_sin_lock(self):
        """Libera recursos internos asumiendo que el lock ya está adquirido."""
        self.prebuffer.clear()
        self.grabando_ahora = False
        if self.writer is not None:
            self.writer.release()
            self.writer = None
            self.ruta_actual = None

    def detener_y_limpiar(self):
        """Libera el archivo de vídeo y vacía la RAM de forma segura al cerrar."""
        with self.lock:
            self._limpiar_sin_lock()
