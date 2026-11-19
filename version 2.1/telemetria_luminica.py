
'''

Añadir estos atributos en __init__ de CamaraBase:

        self.ultimo_registro_luz = 0
        self.ruta_csv_luz = os.path.join(config.DIR_DATOS, f"luz_{self.nombre_archivo}.csv")

####################################################################
####################################################################

Llamar al método dentro de _procesar_nuevo_fotograma(self, frame_bgr):

        self._registrar_telemetria_luz(frame_bgr)
        
####################################################################
####################################################################


Añadir el método a la clase 

CamaraBase:
    
    def _registrar_telemetria_luz(self, frame_bgr, intervalo_seg=300)

####################################################################
####################################################################

Cada cámara generará su archivo en camarasIP/luz_Patio.csv, camarasIP/luz_Entrada.csv, etc.:

ejemplo de csv

fecha,hora,timestamp,camara,luminancia,saturacion,modo_ir,luz_led
2026-11-19,14:00:00,1795093200,Patio,178.45,64.12,0,Auto
2026-11-19,17:45:00,1795106700,Patio,52.10,41.80,0,Auto
2026-11-19,17:50:00,1795107000,Patio,89.30,1.15,1,Auto



'''







import time
import cv2
import datetime
import os
import config
import threading
import numpy as np


def _registrar_telemetria_luz(self, frame_bgr, intervalo_seg=300):
    """Guarda cada 5 minutos el nivel de luz y color en un CSV para análisis."""
    ahora = time.time()
    if (ahora - self.ultimo_registro_luz) < intervalo_seg:
        return
    self.ultimo_registro_luz = ahora

    # Reducimos la imagen para que el cálculo tarde menos de 1 milisegundo
    pequeno = cv2.resize(frame_bgr, (160, 90), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(pequeno, cv2.COLOR_BGR2HSV)

    # Canal S (1) = saturación de color; Canal V (2) = brillo/luminancia
    saturacion_media = round(float(np.mean(hsv[:, :, 1])), 2)
    luminancia_media = round(float(np.mean(hsv[:, :, 2])), 2)
    modo_ir_activo = 1 if saturacion_media < 8.0 else 0

    dt = datetime.now()
    archivo_nuevo = not os.path.exists(self.ruta_csv_luz)

    def _escribir_csv():
        try:
            os.makedirs(config.DIR_DATOS, exist_ok=True)
            with open(self.ruta_csv_luz, "a", encoding="utf-8") as f:
                if archivo_nuevo:
                    f.write("fecha,hora,timestamp,camara,luminancia,saturacion,modo_ir,luz_led\n")
                f.write(
                    f"{dt.strftime('%Y-%m-%d')},{dt.strftime('%H:%M:%S')},"
                    f"{int(ahora)},{self.nombre},{luminancia_media},"
                    f"{saturacion_media},{modo_ir_activo},{self.modo_luz_actual}\n"
                )
        except OSError as exc:
            print(f"[{self.nombre}] Error escribiendo telemetría de luz: {exc}")

    threading.Thread(target=_escribir_csv, daemon=True).start()
