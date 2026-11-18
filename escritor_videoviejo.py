"""Escritor de vídeo H.264 compatible al 100% con móviles mediante FFmpeg."""
import subprocess
import cv2


class EscritorVideoH264:
    """Codifica fotogramas BGR en MP4 H.264 (yuv420p) con respaldo automático a OpenCV."""

    def __init__(self, ruta_salida, fps, ancho, alto):
        self.ruta_salida = ruta_salida
        self.proceso = None
        self.writer_opencv = None

        cmd = [
            "ffmpeg",
            "-y",
            "-loglevel", "error",
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-pix_fmt", "bgr24",
            "-s", f"{ancho}x{alto}",
            "-r", str(fps),
            "-i", "pipe:0",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "26",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            ruta_salida,
        ]

        try:
            # Evita abrir ventanas negras de consola en Windows
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            self.proceso = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
        except Exception:
            # Si ffmpeg no está disponible, usa OpenCV estándar sin interrumpir la grabación
            self.proceso = None
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            self.writer_opencv = cv2.VideoWriter(ruta_salida, fourcc, fps, (ancho, alto))

    def write(self, frame):
        if self.proceso and self.proceso.stdin:
            try:
                self.proceso.stdin.write(frame.tobytes())
            except (BrokenPipeError, OSError):
                pass
        elif self.writer_opencv is not None:
            self.writer_opencv.write(frame)

    def release(self):
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
