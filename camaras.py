### 2. `camaras.py` (Implementaciones específicas RTSP y DVRIP)

#Este archivo sustituye a `clase_rtsp.py` y `clase_dvrip.py`, reduciendo ambos a menos de la mitad de líneas.


import os
import queue
import subprocess
import threading
import time
import cv2
from dvrip import DVRIPCam
import numpy as np
from onvif import ONVIFCamera
import sounddevice as sd

from camara_base import CamaraBase
from config import (
    ALTO_CELDA,
    ALTO_LENTE_DVRIP,
    ANCHO_CELDA,
    DISPOSITIVO_SALIDA_AUDIO,
    alaw_a_pcm,
)

os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"


class CamaraRTSP(CamaraBase):
    """Cámara IP estándar mediante RTSP (vídeo/audio) y ONVIF (PTZ)."""

    def __init__(self, cfg, indice):
        super().__init__(cfg, indice)
        self.url = (
            f"rtsp://{cfg['ip']}:{cfg['puerto_rtsp']}/user={cfg['usuario']}_"
            f"password={cfg['password']}_channel={cfg['canal']}_"
            f"stream={cfg['stream']}.sdp"
        )
        self.proceso_ffplay = None
        self.forzar_reinicio_stream = False
        self.ptz = None
        self.media_profile = None

        threading.Thread(target=self._conectar_onvif, daemon=True).start()
        threading.Thread(target=self._bucle_video, daemon=True).start()
        threading.Thread(target=self._bucle_captura_audio_rtsp, daemon=True).start()
        
        
    def _conectar_onvif(self):
        try:
            cam = ONVIFCamera(self.cfg["ip"], self.cfg["puerto_onvif"], self.cfg["usuario"], self.cfg["password"])
            media = cam.create_media_service()
            self.ptz = cam.create_ptz_service()
            perfiles = media.GetProfiles()
            if perfiles:
                self.media_profile = perfiles[0]
        except Exception as e:
            print(f"[{self.nombre}] ONVIF no disponible: {e}")

    def mover_ptz(self, pan=0.0, tilt=0.0, zoom=0.0):
        if not self.ptz or not self.media_profile:
            return

        def _enviar():
            if not self.lock_red.acquire(blocking=False):
                return
            try:
                req = self.ptz.create_type("ContinuousMove")
                req.ProfileToken = self.media_profile.token
                req.Velocity = {"Zoom": {"x": zoom}} if zoom != 0.0 else {"PanTilt": {"x": pan, "y": tilt}}
                self.ptz.ContinuousMove(req)
                time.sleep(0.35)
                self.ptz.Stop({"ProfileToken": self.media_profile.token})
            except Exception as e:
                print(f"[{self.nombre}] Error PTZ ONVIF: {e}")
            finally:
                self.lock_red.release()

        threading.Thread(target=_enviar, daemon=True).start()
        
    def ir_a_preset(self, numero):
        if not self.ptz or not self.media_profile:
            return

        def _ir():
            if not self.lock_red.acquire(blocking=False):
                return
            try:
                self.ptz.GotoPreset({
                    "ProfileToken": self.media_profile.token,
                    "PresetToken": str(numero),
                })
                print(f"[{self.nombre}] Moviendo a Preset {numero} (ONVIF)")
            except Exception as e:
                print(f"[{self.nombre}] Error yendo a Preset {numero}: {e}")
            finally:
                self.lock_red.release()

        threading.Thread(target=_ir, daemon=True).start()

    def guardar_preset(self, numero):
        if not self.ptz or not self.media_profile:
            return

        def _guardar():
            if not self.lock_red.acquire(blocking=False):
                return
            try:
                self.ptz.SetPreset({
                    "ProfileToken": self.media_profile.token,
                    "PresetToken": str(numero),
                    "PresetName": f"Preset_{numero}",
                })
                print(f"[{self.nombre}] Posición guardada en Preset {numero} (ONVIF)")
            except Exception as e:
                print(f"[{self.nombre}] Error guardando Preset {numero}: {e}")
            finally:
                self.lock_red.release()

        threading.Thread(target=_guardar, daemon=True).start()

    def _bucle_captura_audio_rtsp(self):
      """Extrae audio PCM del stream RTSP solo mientras hay una grabación activa."""
      while not self.detener:
          if not (self.grabando or self.grabador_eventos.grabando_ahora):
              time.sleep(0.5)
              continue

          cmd = [
              "ffmpeg", "-loglevel", "error",
              "-rtsp_transport", "tcp",
              "-i", self.url,
              "-vn", "-acodec", "pcm_s16le",
              "-ar", "8000", "-ac", "1",
              "-f", "s16le", "pipe:1",
          ]
          proc = None
          try:
              creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
              proc = subprocess.Popen(
                  cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=creationflags
              )
              while not self.detener and (self.grabando or self.grabador_eventos.grabando_ahora):
                  datos = proc.stdout.read(1600)  # 0.1 segundos de audio a 8kHz int16
                  if not datos:
                      break
                  self._procesar_nuevo_audio(datos)
          except Exception:
              time.sleep(2)
          finally:
              if proc:
                  try:
                      proc.terminate()
                      proc.wait(timeout=2)
                  except Exception:
                      pass
    
    
    def alternar_escuchar_audio(self):
        self.escuchando_audio = not self.escuchando_audio
        if self.escuchando_audio:
            cmd = ["ffplay", "-nodisp", "-vn", "-rtsp_transport", "tcp", "-fflags", "nobuffer", "-flags", "low_delay", self.url]
            self.proceso_ffplay = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif self.proceso_ffplay:
            self.proceso_ffplay.terminate()
            self.proceso_ffplay = None

    def forzar_reconexion(self):
        self.conectada = False
        self.forzar_reinicio_stream = True

    def _bucle_video(self):
        cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
        while not self.detener:
            if self.forzar_reinicio_stream:
                self.forzar_reinicio_stream = False
                self.conectada = False
                cap.release()
                time.sleep(2)
                cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
                continue

            ret, frame = cap.read()
            if ret:
                frame_redim = cv2.resize(frame, (ANCHO_CELDA, ALTO_CELDA))
                self._procesar_nuevo_fotograma(frame_redim)
            else:
                self.conectada = False
                cap.release()
                time.sleep(1)
                cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)

        cap.release()

    def cerrar(self):
        self.cerrar_base()
        if self.proceso_ffplay:
            self.proceso_ffplay.terminate()


class CamaraDVRIP(CamaraBase):
    """Cámara de doble lente mediante protocolo propietario DVRIP/XMeye."""

    def __init__(self, cfg, indice):
        super().__init__(cfg, indice)
        self.ultima_lente = {0: None, 1: None}
        self.colas_video = {0: queue.Queue(maxsize=60), 1: queue.Queue(maxsize=60)}
        self.cola_audio = queue.Queue(maxsize=60)
        self.procesos = {}
        self.logs = {}
        self.camaras_dvrip = {}
        self.cam_control = None

        threading.Thread(target=self._iniciar_dvrip, daemon=True).start()

    def _iniciar_dvrip(self):
        try:
            self.cam_control = DVRIPCam(self.cfg["ip"], user=self.cfg["usuario"], password=self.cfg["password"])
            self.cam_control.login()

            for canal in self.cfg["canales"]:
                cam = DVRIPCam(self.cfg["ip"], user=self.cfg["usuario"], password=self.cfg["password"])
                if not cam.login():
                    raise RuntimeError(f"Error login DVRIP canal {canal}")
                self.camaras_dvrip[canal] = cam

                cmd = [
                    "ffmpeg", "-loglevel", "error", "-f", "hevc", "-i", "pipe:0",
                    "-an", "-vf", f"scale={ANCHO_CELDA}:{ALTO_LENTE_DVRIP}",
                    "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1",
                ]
                log = open(f"ffmpeg_patio_lente_{canal}.log", "w")
                proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, bufsize=0)
                self.procesos[canal] = proc
                self.logs[canal] = log

                threading.Thread(target=self._alimentar_ffmpeg, args=(canal,), daemon=True).start()
                threading.Thread(target=self._leer_ffmpeg, args=(canal,), daemon=True).start()
                threading.Thread(target=self._bucle_monitor_dvrip, args=(canal,), daemon=True).start()

            self.conectada = True
        except Exception as e:
            self.conectada = False
            print(f"[{self.nombre}] Error iniciando DVRIP: {e}")

    def _bucle_monitor_dvrip(self, canal):
        while not self.detener:
            cam = self.camaras_dvrip.get(canal)
            if not cam:
                break
            try:
                cam.start_monitor(self._crear_callback(canal), None, channel=canal)
            except Exception:
                if not self.detener:
                    time.sleep(2)
                    try:
                        cam.close()
                    except Exception:
                        pass
                    nueva = DVRIPCam(self.cfg["ip"], user=self.cfg["usuario"], password=self.cfg["password"])
                    if nueva.login():
                        self.camaras_dvrip[canal] = nueva

    def _crear_callback(self, canal):
        def callback(frame, meta, _user):
            if self.detener or frame is None or not meta:
                return
            if meta.get("frame") in ("I", "P"):
                q = self.colas_video[canal]
                if q.full():
                    try:
                        q.get_nowait()
                    except queue.Empty:
                        pass
                q.put_nowait(bytes(frame))
            elif meta.get("type") == "g711a" and canal == 0:
              if self.escuchando_audio or self.grabando or self.grabador_eventos.grabando_ahora:
                  pcm = alaw_a_pcm(frame)
                  self._procesar_nuevo_audio(pcm)
                  if self.escuchando_audio:
                      if self.cola_audio.full():
                          try:
                              self.cola_audio.get_nowait()
                          except queue.Empty:
                              pass
                      self.cola_audio.put_nowait(pcm)
        return callback

    def _alimentar_ffmpeg(self, canal):
        proc = self.procesos[canal]
        q = self.colas_video[canal]
        while not self.detener and proc.poll() is None:
            paquete = q.get()
            if paquete is None or self.detener:
                break
            try:
                proc.stdin.write(paquete)
                proc.stdin.flush()
            except OSError:
                break

    def _leer_ffmpeg(self, canal):
        proc = self.procesos[canal]
        n = ANCHO_CELDA * ALTO_LENTE_DVRIP * 3
        buffer = bytearray()
        while not self.detener and proc.poll() is None:
            data = proc.stdout.read(65536)
            if not data:
                break
            buffer.extend(data)
            while len(buffer) >= n:
                raw = bytes(buffer[:n])
                del buffer[:n]
                img = np.frombuffer(raw, dtype=np.uint8).reshape((ALTO_LENTE_DVRIP, ANCHO_CELDA, 3)).copy()
                combinado = None
                with self.lock:
                    self.ultima_lente[canal] = img
                    sup, inf = self.ultima_lente.get(1), self.ultima_lente.get(0)
                    if sup is not None and inf is not None:
                        combinado = np.vstack((sup, inf)).astype(np.uint8, copy=False)
                if combinado is not None:       
                    # Se procesa en el hilo decodificador, nunca en la UI
                    self._procesar_nuevo_fotograma(combinado)
   
                        
    def mover_ptz(self, pan=0.0, tilt=0.0, zoom=0.0):
        direcciones = {
            (0, 1, 0): "DirectionUp",
            (0, -1, 0): "DirectionDown",
            (1, 0, 0): "DirectionLeft",
            (-1, 0, 0): "DirectionRight",
            (0, 0, 1): "ZoomTile",
            (0, 0, -1): "ZoomWide",
        }
        clave = (int(np.sign(pan)), int(np.sign(tilt)), int(np.sign(zoom)))
        direccion = direcciones.get(clave)
        if not direccion or not self.cam_control:
            return

        def _ejecutar():
            if not self.lock_red.acquire(blocking=False):
                return
            try:
                for preset in (65535, -1):
                    params = {
                        "AUX": {"Number": 0, "Status": "On"},
                        "Channel": 0,
                        "MenuOpts": "Enter",
                        "POINT": {"bottom": 0, "left": 0, "right": 0, "top": 0},
                        "Pattern": "SetBegin",
                        "Preset": preset,
                        "Step": 4,
                        "Tour": 0,
                    }
                    self.cam_control.set_command(
                        "OPPTZControl", {"Command": direccion, "Parameter": params}
                    )
                    if preset == 65535:
                        time.sleep(0.35)
            except Exception as e:
                print(f"[{self.nombre}] Error PTZ DVRIP: {e}")
            finally:
                self.lock_red.release()

        threading.Thread(target=_ejecutar, daemon=True).start()
        
        
    def _comando_preset_dvrip(self, comando, numero):
        if not self.cam_control:
            return

        def _ejecutar():
            if not self.lock_red.acquire(blocking=False):
                return
            try:
                params = {
                    "AUX": {"Number": 0, "Status": "On"},
                    "Channel": 0,
                    "MenuOpts": "Enter",
                    "POINT": {"bottom": 0, "left": 0, "right": 0, "top": 0},
                    "Pattern": "SetBegin",
                    "Preset": int(numero),
                    "Step": 4,
                    "Tour": 0,
                }
                self.cam_control.set_command(
                    "OPPTZControl", {"Command": comando, "Parameter": params}
                )
                print(f"[{self.nombre}] {comando} -> Preset {numero} (DVRIP)")
            except Exception as e:
                print(f"[{self.nombre}] Error {comando} {numero}: {e}")
            finally:
                self.lock_red.release()

        threading.Thread(target=_ejecutar, daemon=True).start()

    def ir_a_preset(self, numero):
        self._comando_preset_dvrip("GotoPreset", numero)

    def guardar_preset(self, numero):
        self._comando_preset_dvrip("SetPreset", numero)


    def alternar_escuchar_audio(self):
        self.escuchando_audio = not self.escuchando_audio
        if self.escuchando_audio:
            while not self.cola_audio.empty():
                try:
                    self.cola_audio.get_nowait()
                except queue.Empty:
                    break
            threading.Thread(target=self._reproducir_audio, daemon=True).start()
        print(f"[{self.nombre}] Escucha DVRIP: {'ACTIVADA' if self.escuchando_audio else 'SILENCIADA'}")

    def _reproducir_audio(self):
        try:
            with sd.OutputStream(
                device=DISPOSITIVO_SALIDA_AUDIO, samplerate=8000, channels=1, dtype="int16"
            ) as out:
                while self.escuchando_audio and not self.detener:
                    try:
                        out.write(self.cola_audio.get(timeout=0.2))
                    except queue.Empty:
                        continue
        except Exception as e:
            print(f"[{self.nombre}] Error de salida de audio: {e}")
        finally:
            self.escuchando_audio = False

    def _detener_procesos_ffmpeg(self):
        """Detiene limpiamente los subprocesos FFmpeg y desbloquea sus colas."""
        for canal, q in self.colas_video.items():
            try:
                q.put_nowait(None)
            except queue.Full:
                pass
        for proc in self.procesos.values():
            try:
                if proc.stdin:
                    proc.stdin.close()
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self.procesos.clear()

    def forzar_reconexion(self):
        if not self.lock_red.acquire(blocking=False):
            return
        try:
            self.conectada = False
            self._detener_procesos_ffmpeg()
            time.sleep(1)
            threading.Thread(target=self._iniciar_dvrip, daemon=True).start()
        finally:
            self.lock_red.release()

    def cerrar(self):
        self.cerrar_base()
        for cam in self.camaras_dvrip.values():
            try:
                cam.stop_monitor()
                cam.close()
            except Exception:
                pass
        if self.cam_control:
            try:
                self.cam_control.close()
            except Exception:
                pass
        self._detener_procesos_ffmpeg()
        for log in self.logs.values():
            try:
                log.close()
            except Exception:
                pass
