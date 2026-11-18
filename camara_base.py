from datetime import datetime
import json
import os
import socket
import struct
import threading
import time
import cv2
import numpy as np
import sounddevice as sd

from config import (
    ALTO_CELDA,
    ANCHO_CELDA,
    CARPETA_CAPTURAS,
    CARPETA_FOTOGRAMAS,
    CARPETA_GRABACIONES,
    COOLDOWN_CAPTURA_SEG,
    INTERVALO_FOTOGRAMA_AUTO_SEG,
    MINUTOS_POR_BLOQUE_VIDEO,
    SENSIBILIDAD_MOVIMIENTO,
    hash_xmeye,
    pcm16_a_alaw,
)
from correo_alertas import enviar_alerta_correo_rtsp
from grabacion_eventos import GrabadorEventos
from notificaciones import enviar_alerta_movimiento
from escritor_video import EscritorVideoH264

class CamaraBase:
    """Clase base thread-safe con toda la lógica común (detección, grabación, NetIP, UI)."""

    def __init__(self, cfg, indice):
        self.cfg = cfg
        self.indice = indice
        self.nombre = cfg["nombre"]
        self.nombre_archivo = self.nombre.replace(" ", "_")

        # Sincronización y estado
        self.lock = threading.RLock()
        self.lock_red = threading.Lock()  # Evita colisiones en sockets NetIP/PTZ
        self._frame = None
        self.conectada = False
        self.detener = False

        # Interruptores de estado
        self.grabando = False
        self.deteccion_activa = False
        self.captura_auto_activa = False
        self.escuchando_audio = False
        self.hablando_micro = False
        self.movimiento_detectado = False
        self.modo_luz_actual = "Auto"
        self.zoom_digital = 1.0

        # Submódulos y control interno
        self.grabador_eventos = GrabadorEventos(self.nombre)
        self.video_writer = None
        self.inicio_bloque = 0
        self.fondo_gris = None
        self.ultima_captura_mov = 0
        self.ultimo_fotograma_auto = 0

    @property
    def frame(self):
        with self.lock:
            return self._frame

    @frame.setter
    def frame(self, nuevo_frame):
        with self.lock:
            self._frame = nuevo_frame

    # --- PIPELINE DE PROCESAMIENTO (Ejecutado siempre en el hilo de captura) ---
    def _procesar_nuevo_fotograma(self, frame_bgr):
        """Procesa detección, grabación y zoom en segundo plano antes de publicar el frame."""
        self.conectada = True
        hay_mov = self._detectar_movimiento(frame_bgr)
        self.movimiento_detectado = hay_mov

        self.grabador_eventos.procesar_frame(frame_bgr, hay_mov)
        self._gestionar_grabacion(frame_bgr)
        self._gestionar_captura_auto(frame_bgr)

        frame_final = self._aplicar_zoom_digital(frame_bgr)
        self.frame = frame_final

    def _guardar_imagen_async(self, ruta, frame, mensaje_log=None):
        """Guarda una imagen JPEG en segundo plano sin bloquear el hilo de vídeo."""
        copia = frame.copy()

        def _tarea_guardar():
            try:
                cv2.imwrite(ruta, copia)
                if mensaje_log:
                    print(mensaje_log)
            except Exception as exc:
                print(f"[{self.nombre}] Error guardando imagen {ruta}: {exc}")

        threading.Thread(target=_tarea_guardar, daemon=True).start()
    
    
    def _detectar_movimiento(self, frame):
        if not self.deteccion_activa:
            return False

        # Reducimos a la mitad (4x menos píxeles) para ahorrar CPU sin perder precisión
        pequeno = cv2.resize(frame, (0, 0), fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
        gris = cv2.GaussianBlur(cv2.cvtColor(pequeno, cv2.COLOR_BGR2GRAY), (15, 15), 0)
        if self.fondo_gris is None or self.fondo_gris.shape != gris.shape:
            self.fondo_gris = gris
            return False

        diff = cv2.absdiff(self.fondo_gris, gris)
        _, th = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
        th = cv2.dilate(th, None, iterations=2)
        contornos, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        umbral_escalado = SENSIBILIDAD_MOVIMIENTO / 4.0
        hay_movimiento = any(cv2.contourArea(c) > umbral_escalado for c in contornos)
        self.fondo_gris = cv2.addWeighted(self.fondo_gris, 0.95, gris, 0.05, 0)

        if hay_movimiento:
            ahora = time.time()
            if (ahora - self.ultima_captura_mov) >= COOLDOWN_CAPTURA_SEG:
                self.ultima_captura_mov = ahora
                fecha_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                ruta = os.path.join(CARPETA_CAPTURAS, f"MOV_{self.nombre_archivo}_{fecha_str}.jpg")
                self._guardar_imagen_async(ruta, frame, f"¡ALERTA! Movimiento en {self.nombre} -> {ruta}")
                enviar_alerta_movimiento(frame, self.nombre)
                enviar_alerta_correo_rtsp(self.nombre, frame)

        return hay_movimiento

    def _gestionar_grabacion(self, frame):
        with self.lock:
            if not self.grabando:
                if self.video_writer is not None:
                    self.video_writer.release()
                    self.video_writer = None
                return

            ahora = time.time()
            if self.video_writer is None or (ahora - self.inicio_bloque) >= (MINUTOS_POR_BLOQUE_VIDEO * 60):
                if self.video_writer is not None:
                    self.video_writer.release()
                fecha_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                ruta = os.path.join(CARPETA_GRABACIONES, f"{self.nombre_archivo}_{fecha_str}.mp4")
                #fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                #self.video_writer = cv2.VideoWriter(ruta, fourcc, 20.0, (ANCHO_CELDA, ALTO_CELDA))
                self.video_writer = EscritorVideoH264(ruta, 20.0, ANCHO_CELDA, ALTO_CELDA, con_audio=True)
                
                self.inicio_bloque = ahora

            self.video_writer.write(frame)
            
    def _procesar_nuevo_audio(self, pcm_int16):
        """Envía fragmentos de audio PCM a los grabadores activos."""
        if pcm_int16 is None or len(pcm_int16) == 0:
            return
        raw_bytes = pcm_int16.tobytes() if hasattr(pcm_int16, "tobytes") else bytes(pcm_int16)

        with self.lock:
            if self.grabando and self.video_writer is not None:
                self.video_writer.write_audio(raw_bytes)

        if hasattr(self.grabador_eventos, "procesar_audio"):
            self.grabador_eventos.procesar_audio(raw_bytes)


    def _gestionar_captura_auto(self, frame):
        if not self.captura_auto_activa:
            return
        ahora = time.time()
        if (ahora - self.ultimo_fotograma_auto) >= INTERVALO_FOTOGRAMA_AUTO_SEG:
            self.ultimo_fotograma_auto = ahora
            fecha_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            ruta = os.path.join(CARPETA_FOTOGRAMAS, f"AUTO_{self.nombre_archivo}_{fecha_str}.jpg")
            self._guardar_imagen_async(ruta, frame)

    def _aplicar_zoom_digital(self, frame):
        if self.zoom_digital <= 1.0:
            return frame
        h, w = frame.shape[:2]
        mitad_y = h // 2
        parte_superior = frame[:mitad_y, :]
        parte_inferior = frame[mitad_y:, :]

        nh, nw = int(mitad_y / self.zoom_digital), int(w / self.zoom_digital)
        y1, x1 = (mitad_y - nh) // 2, (w - nw) // 2
        recorte_inf = parte_inferior[y1:y1 + nh, x1:x1 + nw]
        parte_inferior_zoom = cv2.resize(recorte_inf, (w, h - mitad_y))
        return np.vstack((parte_superior, parte_inferior_zoom))

    # --- CONTROLES DE USUARIO ---
    def cambiar_zoom(self, incremento):
        self.zoom_digital = max(1.0, min(4.0, self.zoom_digital + incremento))
        
        
    def ir_a_preset(self, numero):
        """Mueve la cámara a una posición predefinida (1..N)."""
        pass

    def guardar_preset(self, numero):
        """Guarda la posición actual en la memoria interna de la cámara."""
        pass


    def alternar_deteccion(self):
        self.deteccion_activa = not self.deteccion_activa
        if not self.deteccion_activa:
            self.movimiento_detectado = False
            self.fondo_gris = None

    def alternar_grabacion(self):
        with self.lock:
            self.grabando = not self.grabando
            if not self.grabando and self.video_writer:
                self.video_writer.release()
                self.video_writer = None

    def alternar_grab_movimiento(self):
        activo = self.grabador_eventos.alternar()
        if activo and not self.deteccion_activa:
            self.alternar_deteccion()

    def alternar_captura_auto(self):
        self.captura_auto_activa = not self.captura_auto_activa

    def capturar_fotograma_manual(self):
        copia = self.frame
        if copia is not None:
            fecha_str = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            ruta = os.path.join(CARPETA_FOTOGRAMAS, f"MANUAL_{self.nombre_archivo}_{fecha_str}.jpg")
            self._guardar_imagen_async(ruta, copia, f"[{self.nombre}] Foto manual guardada -> {ruta}")

    # --- PROTOCOLO NETIP COMPARTIDO (LED Y MICRÓFONO BIDIRECCIONAL) ---

    def _login_netip(self, sock):
        login_payload = json.dumps({
            "EncryptType": "MD5",
            "LoginType": "DVRIP-Web",
            "PassWord": hash_xmeye(self.cfg["password"]),
            "UserName": self.cfg["usuario"],
        }).encode()
        cab = (
            struct.pack("<BB2xII2xHI", 0xFF, 0x00, 0, 0, 1000, len(login_payload) + 2)
            + login_payload
            + b"\x0a\x00"
        )
        sock.sendall(cab)
        resp = sock.recv(1024)
        return struct.unpack("<I", resp[4:8])[0] if len(resp) >= 8 else 0


    def cambiar_luz_led(self, modo):
        self.modo_luz_actual = modo

        def _tarea_luz():
            if not self.lock_red.acquire(blocking=False):
                return  # Evita acumular peticiones si el usuario pulsa muy rápido
            mapa = {"BLANCA": "KeepOpen", "IR": "Close", "AUTO": "Auto"}
            work_mode = mapa.get(modo, "Auto")
            sock = None
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(3)
                sock.connect((self.cfg["ip"], self.cfg["puerto_netip"]))
                sid = self._login_netip(sock)

                payload = json.dumps({
                    "Name": "Camera.WhiteLight",
                    "SessionID": f"0x{sid:08X}",
                    "Camera.WhiteLight": {
                        "WorkMode": work_mode,
                        "WorkPeriod": {"EHour": 23, "EMinute": 59, "Enable": 1, "SHour": 0, "SMinute": 0},
                    },
                }).encode()
                cab = struct.pack("<BB2xII2xHI", 0xFF, 0x00, sid, 1, 1040, len(payload) + 2) + payload + b"\x0a\x00"
                sock.sendall(cab)
                sock.recv(1024)
                print(f"[{self.nombre}] Iluminación cambiada a: {modo}")
            except Exception as e:
                print(f"[{self.nombre}] Error cambiando luz LED: {e}")
            finally:
                if sock:
                    sock.close()
                self.lock_red.release()

        threading.Thread(target=_tarea_luz, daemon=True).start()
        

    def alternar_hablar_micro(self):
        self.hablando_micro = not self.hablando_micro
        if self.hablando_micro:
            print(f"[{self.nombre}] Micrófono PC -> Cámara: ACTIVADO")
            threading.Thread(target=self._bucle_enviar_voz, daemon=True).start()
        else:
            print(f"[{self.nombre}] Micrófono PC -> Cámara: APAGADO")

    def _bucle_enviar_voz(self):
        # Evita abrir dos sesiones de voz simultáneas si se pulsa el botón muy rápido
        if not self.lock_red.acquire(blocking=False):
            self.hablando_micro = False
            return

        sock = None
        sid = 0
        seq = 1
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(4)
            sock.connect((self.cfg["ip"], self.cfg["puerto_netip"]))
            sid = self._login_netip(sock)

            for accion, codigo in (("Claim", 1434), ("Start", 1430)):
                payload = json.dumps({
                    "Name": "OPTalk",
                    "SessionID": f"0x{sid:08X}",
                    "OPTalk": {
                        "Action": accion,
                        "AudioFormat": {
                            "BitRate": 128,
                            "EncodeType": "G711_ALAW",
                            "SampleBit": 8,
                            "SampleRate": 8000,
                        },
                    },
                }).encode()
                cab = (
                    struct.pack("<BB2xII2xHI", 0xFF, 0x00, sid, seq, codigo, len(payload) + 2)
                    + payload
                    + b"\x0a\x00"
                )
                sock.sendall(cab)
                sock.recv(1024)
                seq += 1

            chunk_size = 320
            with sd.InputStream(samplerate=8000, channels=1, dtype="int16", blocksize=chunk_size) as mic:
                while self.hablando_micro and not self.detener:
                    pcm_array, _ = mic.read(chunk_size)
                    alaw = pcm16_a_alaw(pcm_array.flatten())
                    pkt = b"\x00\x00\x01\xfa\x0e\x02" + struct.pack("<H", len(alaw)) + alaw
                    cab = struct.pack("<BB2xII2xHI", 0xFF, 0x00, sid, seq, 1432, len(pkt)) + pkt
                    sock.sendall(cab)
                    seq += 1

        except Exception as e:
            print(f"[{self.nombre}] Error micrófono: {e}")
            self.hablando_micro = False
        finally:
            if sock and sid:
                try:
                    stop = json.dumps({
                        "Name": "OPTalk",
                        "SessionID": f"0x{sid:08X}",
                        "OPTalk": {"Action": "Stop"},
                    }).encode()
                    cab = (
                        struct.pack("<BB2xII2xHI", 0xFF, 0x00, sid, seq, 1430, len(stop) + 2)
                        + stop
                        + b"\x0a\x00"
                    )
                    sock.sendall(cab)
                    sock.recv(1024)
                except Exception:
                    pass
            if sock:
                sock.close()
            self.lock_red.release()

    # --- DIBUJADO DE INTERFAZ (Solo lectura rápida, cero bloqueo) ---
    def obtener_imagen_ui(self, seleccionada=False):
        frame_actual = self.frame
        if self.conectada and frame_actual is not None:
            img = frame_actual.copy()
        else:
            img = np.zeros((ALTO_CELDA, ANCHO_CELDA, 3), dtype=np.uint8)
            cv2.putText(
                img,
                f"[{self.indice + 1}] {self.nombre}: Conectando...",
                (120, 180),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 0, 255),
                2,
            )

        color_titulo = (0, 255, 255) if seleccionada else (0, 255, 0)
        marca = " [ACTIVA]" if seleccionada else ""
        titulo = f"[{self.indice + 1}] {self.nombre}{marca} | Z:{self.zoom_digital:.1f}x | {self.modo_luz_actual}"
        cv2.putText(img, titulo, (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.52, color_titulo, 2)

        cv2.putText(
            img,
            "MOV:ON" if self.deteccion_activa else "MOV:OFF",
            (370, 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.46,
            (0, 255, 0) if self.deteccion_activa else (140, 140, 140),
            2,
        )
        cv2.putText(
            img,
            "FOT:ON" if self.captura_auto_activa else "FOT:OFF",
            (445, 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.46,
            (0, 255, 255) if self.captura_auto_activa else (140, 140, 140),
            2,
        )

        if self.grabador_eventos.activa:
            c_pre = (0, 0, 255) if self.grabador_eventos.grabando_ahora else (0, 255, 255)
            cv2.circle(img, (526, 19), 5, c_pre, -1)
            cv2.putText(img, "PRE", (535, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.46, c_pre, 2)

        if self.grabando:
            cv2.circle(img, (582, 19), 6, (0, 0, 255), -1)
            cv2.putText(img, "REC", (592, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 0, 255), 2)

        if self.movimiento_detectado:
            cv2.rectangle(img, (3, 3), (ANCHO_CELDA - 3, ALTO_CELDA - 3), (0, 0, 255), 4)
            cv2.putText(img, "MOVIMIENTO DETECTADO", (415, 342), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 0, 255), 2)
        elif seleccionada:
            cv2.rectangle(img, (2, 2), (ANCHO_CELDA - 2, ALTO_CELDA - 2), (0, 255, 255), 3)

        return img

    def cerrar_base(self):
        self.detener = True
        self.grabando = False
        self.deteccion_activa = False
        self.escuchando_audio = False
        self.hablando_micro = False
        self.grabador_eventos.detener_y_limpiar()

        writer_a_cerrar = None
        with self.lock:
            writer_a_cerrar = self.video_writer
            self.video_writer = None

        if writer_a_cerrar is not None:
            writer_a_cerrar.release()
