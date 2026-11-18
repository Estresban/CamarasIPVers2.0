"""Escritor de vídeo H.264 + Audio AAC compatible con móviles mediante FFmpeg."""
import os
import subprocess
import threading
import cv2


class EscritorVideoH264:
    """Codifica vídeo BGR y audio PCM opcional en MP4 (H.264 + AAC)."""

    def __init__(self, ruta_salida, fps, ancho, alto, con_audio=False):
        self.ruta_salida = ruta_salida
        self.proceso = None
        self.writer_opencv = None
        self.pipe_audio_w = None
        self.lock_audio = threading.Lock()

        pipe_audio_r = None
        cmd = [
            "ffmpeg",
            "-y",
            "-loglevel", "error",
            # Entrada 0: Vídeo raw BGR desde stdin
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-pix_fmt", "bgr24",
            "-s", f"{ancho}x{alto}",
            "-r", str(fps),
            "-i", "pipe:0",
        ]

        if con_audio:
            try:
                pipe_audio_r, self.pipe_audio_w = os.pipe()
                os.set_inheritable(pipe_audio_r, True)
                cmd.extend([
                    # Entrada 1: Audio PCM 8kHz mono desde descriptor de archivo
                    "-f", "s16le",
                    "-ar", "8000",
                    "-ac", "1",
                    "-i", f"pipe:{pipe_audio_r}",
                    "-c:a", "aac",
                    "-b:a", "64k",
                    "-shortest",
                ])
            except Exception:
                con_audio = False

        cmd.extend([
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "26",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            ruta_salida,
        ])

        try:
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            pass_fds = (pipe_audio_r,) if (con_audio and pipe_audio_r is not None) else ()
            self.proceso = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                pass_fds=pass_fds,
                close_fds=False if os.name == "nt" else True,
                creationflags=creationflags,
            )
        except Exception:
            self.proceso = None
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            self.writer_opencv = cv2.VideoWriter(ruta_salida, fourcc, fps, (ancho, alto))
        finally:
            if pipe_audio_r is not None:
                try:
                    os.close(pipe_audio_r)
                except OSError:
                    pass

    def write(self, frame):
        if self.proceso and self.proceso.stdin:
            try:
                self.proceso.stdin.write(frame.tobytes())
            except (BrokenPipeError, OSError):
                pass
        elif self.writer_opencv is not None:
            self.writer_opencv.write(frame)

    def write_audio(self, pcm_bytes):
        """Escribe bytes PCM int16 (8000Hz mono) en la pista de audio."""
        if not pcm_bytes or self.pipe_audio_w is None:
            return
        with self.lock_audio:
            if self.pipe_audio_w is not None:
                try:
                    os.write(self.pipe_audio_w, pcm_bytes)
                except OSError:
                    pass

    def release(self):
        with self.lock_audio:
            if self.pipe_audio_w is not None:
                try:
                    os.close(self.pipe_audio_w)
                except OSError:
                    pass
                self.pipe_audio_w = None

        if self.proceso:
            try:
                if self.proceso.stdin:
                    self.proceso.stdin.close()
                self.proceso.wait(timeout=5)
            except Exception:
                try:
                    self.proceso.kill()
                except Exception:
                    pass
            finally:
                self.proceso = None

        if self.writer_opencv is not None:
            self.writer_opencv.release()
            self.writer_opencv = None
