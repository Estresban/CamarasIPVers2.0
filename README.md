# 🛡️ Sistema de Videovigilancia StiVi-Home (`CamarasIPVers2.0`)

Sistema integral de videovigilancia multiplataforma (**Windows** y **Linux**) desarrollado en Python. Permite visualizar, controlar, grabar y supervisar cámaras IP estándar (**RTSP / ONVIF**) y cámaras de doble lente (**DVRIP / XMeye**) en tiempo real, con detección de movimiento, pre-buffer de vídeo, audio bidireccional y control remoto completo mediante **Bot de Telegram** y **alertas por correo electrónico**.

---

## ✨ Características Principales

* **Mosaico Dinámico:** Vista configurable en cuadrícula **1×1**, **1×2** o **2×2** con ampliación instantánea a pantalla completa mediante doble clic o tecla `Enter`.
* **Compatibilidad Híbrida de Cámaras:**
  * **RTSP + ONVIF:** Captura de vídeo por TCP, control PTZ continuo, gestión de presets y audio en vivo con `ffplay`.
  * **DVRIP / XMeye (Doble Lente):** Decodificación paralela mediante subprocesos `FFmpeg`, unión vertical de ambas lentes, control PTZ y audio G.711 A-Law.
* **Detección de Movimiento Optimizada:** Procesamiento de bajo consumo de CPU con umbral ajustable y captura automática de fotogramas.
* **Grabación Continua y por Eventos (Pre-Buffer):**
  * Codificación directa en **MP4 (H.264 + Audio AAC)** compatible con navegadores y teléfonos móviles.
  * Búfer circular en memoria RAM que guarda los **5 segundos previos** y **15 segundos posteriores** a cada detección de movimiento.
* **Audio Bidireccional:** Escucha en tiempo real del entorno de la cámara y envío de voz desde el micrófono del PC hacia la cámara (protocolo NetIP `OPTalk`).
* **Control Remoto por Telegram:** Bot interactivo con teclado táctil persistente para mover cámaras PTZ, activar/desactivar alertas, pedir capturas, consultar logs y recibir clips de vídeo.
* **Alertas por Correo Electrónico (SMTP SSL):** Envío automático de fotografías y clips `.mp4` tras detectar movimiento, con control de intervalo anti-spam.
* **Mantenimiento Automático y Watchdog:**
  * **Watchdog:** Detecta flujos congelados o desconectados, fuerza la reconexión automática y notifica por Telegram si una cámara cae de forma prolongada.
  * **Retención Circular de Disco:** Elimina automáticamente los archivos más antiguos al superar el límite de gigabytes configurado.
  * **Programación Horaria:** Armado y desarmado automático de detección, pre-buffer y alertas según franja horaria (soporta tramos nocturnos que cruzan medianoche).
* **Almacenamiento Seguro de Credenciales:** Cifrado simétrico autenticado (`ENC:...`) vinculado al hardware local para proteger contraseñas y tokens en `config.json`.

---

## 📁 Estructura del Proyecto

```text
CamarasIPVers2.0/
├── main.py                  # Punto de entrada, interfaz gráfica OpenCV y panel lateral
├── camara_base.py           # Clase base thread-safe (detección, zoom, grabación, NetIP)
├── camaras.py               # Implementaciones específicas CamaraRTSP y CamaraDVRIP
├── config.py                # Plantilla de parámetros, carga/recarga y cifrado de claves
├── configuracion.py         # Interfaz gráfica (Tkinter) para editar ajustes e historial
├── escritor_video.py        # Codificador FFmpeg en tiempo real (vídeo H.264 + audio AAC)
├── grabacion_eventos.py     # Búfer circular en RAM para clips con pre-buffer
├── notificaciones.py        # Bot de Telegram, teclado táctil, historial y envío de medios
├── correo_alertas.py        # Envío asíncrono de alertas y clips por correo SMTP SSL
├── mantenimiento.py         # Limpieza circular de disco, horarios y recarga en caliente
├── watchdog.py              # Supervisión de salud de cámaras y reconexión automática
├── logger.py                # Registro rotativo en disco (sistema.log)
└── camarasIP/               # Carpeta de datos generados (vídeos, capturas, logs, clave)
    ├── grabaciones/
    ├── capturas_movimiento/
    ├── capturas_fotogramas/
    ├── historial.txt
    └── sistema.log
```

---

## ⚙️ Requisitos e Instalación

### 1. Requisitos del Sistema
* **Python 3.10 o superior** (incluyendo Python 3.13 / 3.15).
* **FFmpeg y FFplay** instalados y accesibles en el `PATH` del sistema operativo:
  * **Windows:** Descargar FFmpeg, añadir la carpeta `bin/` a las variables de entorno del sistema (`PATH`) y verificar con `ffmpeg -version`.
  * **Linux (Ubuntu/Debian):**
    ```bash
    sudo apt update && sudo apt install -y ffmpeg python3-tk libportaudio2
    ```

### 2. Instalación de Dependencias Python
Crea un entorno virtual e instala las librerías necesarias:

```bash
python -m venv venv
# En Windows:
venv\Scripts\activate
# En Linux:
source venv/bin/activate

pip install opencv-python numpy sounddevice onvif-zeep dvrip
```

### 3. Configuración Inicial
1. Si aún no existe `config.py`, copia la plantilla `config.example.py` como `config.py`.
2. Ejecuta la aplicación por primera vez:
   ```bash
   python main.py
   ```
3. Haz clic en el botón **AJUSTES** del panel lateral (o ejecuta `python configuracion.py`) para introducir las IPs, usuarios, contraseñas de tus cámaras, token de Telegram y datos de correo.
4. Al pulsar **Guardar** o **Aplicar**, se generará `config.json` con todas las contraseñas cifradas automáticamente.

---

## 📖 Manual de Usuario

### 🖥️ 1. Interfaz Principal y Panel Lateral
La ventana se divide en dos zonas:
* **Área de Cámaras (Izquierda):** Muestra las cámaras configuradas.
  * **1 clic** sobre una celda: Selecciona la cámara activa (borde amarillo).
  * **Doble clic** sobre una celda: Amplía esa cámara a pantalla completa (doble clic de nuevo o `ESC` para volver al mosaico).
  * **Indicadores en pantalla:**
    * `Z:1.0x`: Nivel de zoom digital actual.
    * `Auto / BLANCA / IR`: Modo de iluminación LED activo.
    * `MOV:ON/OFF`: Estado de la detección de movimiento.
    * `FOT:ON/OFF`: Captura automática periódica de fotogramas.
    * `PRE` (amarillo/rojo): Pre-buffer armado en espera / grabando evento.
    * `REC` (rojo): Grabación continua manual activa.
* **Panel de Control (Derecha):** Permite operar todas las funciones sobre la cámara seleccionada con el ratón:
  * **Cruceta (Arriba, Abajo, Izquierda, Derecha):** Movimiento motorizado PTZ.
  * **ZOOM + / ZOOM -:** Zoom digital progresivo (hasta 4.0x).
  * **DETECCION / GRABAR / GRAB MOV (PRE-BUFFER):** Activa o detiene la detección, la grabación continua o la grabación inteligente por eventos.
  * **AUTO FOTO / FOTO:** Activa capturas periódicas o toma una fotografía instantánea.
  * **AUDIO / MICRO:** Escucha el audio de la cámara o transmite voz desde el micrófono del PC.
  * **BLANCA / IR / AUTO:** Cambia el modo de iluminación de la cámara vía protocolo NetIP.
  * **TELEGRAM / EMAIL:** Silencia o reactiva las notificaciones remotas de todo el sistema.
  * **AJUSTES:** Abre la ventana de configuración sin detener la grabación.

---

### ⌨️ 2. Atajos de Teclado

| Tecla | Acción sobre la cámara seleccionada |
| :--- | :--- |
| **Flechas / `W` `A` `S` `D`** | Mover cámara PTZ (Arriba, Izquierda, Abajo, Derecha) |
| **`+` / `Z`** | Aumentar Zoom Digital |
| **`-` / `X`** | Reducir Zoom Digital |
| **`Tab`** | Cambiar a la siguiente cámara del mosaico |
| **`Enter`** | Ampliar cámara seleccionada / Volver al mosaico |
| **`M`** | Activar / Desactivar detección de movimiento |
| **`R`** | Iniciar / Detener grabación continua |
| **`F`** | Activar / Desactivar captura automática de fotos |
| **`Espacio`** | Tomar fotografía manual instantánea |
| **`V`** | Activar / Silenciar escucha de audio |
| **`T`** | Activar / Desactivar micrófono PC → Cámara |
| **`1` o `L`** | Encender luz LED blanca |
| **`2` o `I`** | Cambiar a modo Infrarrojos (IR) |
| **`3` o `O`** | Cambiar iluminación a modo Automático |
| **`4`, `5`, `6`** | Mover cámara PTZ a Preset 1, 2 o 3 |
| **`7`, `8`, `9`** | Guardar posición actual en Preset 1, 2 o 3 |
| **`N`** | Activar / Silenciar alertas de Telegram |
| **`E`** | Activar / Silenciar alertas por Correo |
| **`Q` o `ESC`** | Salir del programa de forma segura |

---

### 📱 3. Control Remoto por Telegram

Al iniciar el sistema, el bot responde únicamente al `TELEGRAM_CHAT_ID` autorizado. Escribe `/start` para desplegar la botonera táctil persistente:

* **Selección y Movimiento PTZ:**
  * `📹 Cám 1` .. `📹 Cám 4` (`/sel1`..`/sel4`): Selecciona la cámara a controlar y envía una captura actual.
  * `⬆️ Arriba`, `⬇️ Abajo`, `⬅️ Izquierda`, `➡️ Derecha`: Gira la cámara seleccionada.
  * `🔍 Zoom +` / `🔍 Zoom -`: Ajusta el zoom digital y devuelve una imagen actualizada.
  * `📍 Punto 1` .. `📍 Punto 3` (`/preset1`..`/preset9`): Mueve la cámara a una posición guardada (`/setpreset1`..`/setpreset9` para guardar).
* **Capturas y Grabación:**
  * `📸 Foto Actual` o `📸 Foto 1..4` (`/foto1`..`/foto4`, `/foto` para todas): Envía fotografías al instante.
  * `🎥 Grabar` o `🎥 Grabar 1..4` (`/grabar1`..`/grabar4`): Inicia o detiene la grabación manual.
  * `🎬 Pre-Buf 1..4` (`/prebuffer1`..`/prebuffer4`): Activa o desactiva la grabación por movimiento con pre-buffer.
* **Vigilancia, Iluminación y Diagnóstico:**
  * `👁️ Detec 1..4` (`/deteccion1`..`/deteccion4`): Activa o desactiva la detección de movimiento.
  * `💡 Luz` o `💡 Luz 1..4` (`/luz1`..`/luz4`): Alterna entre Luz Blanca, Infrarrojos y Automático.
  * `🔔 Alertas ON/OFF` (`/alertas`) y `📧 Email ON/OFF` (`/email`): Silencia o activa notificaciones.
  * `📊 Estado` (`/estado`): Resumen en tiempo real de grabación, detección y luz de todas las cámaras.
  * `📋 Historial` (`/historial`): Muestra las últimas 5 detecciones registradas.
  * `📄 Logs` (`/logs`): Muestra las últimas 15 líneas de `sistema.log` para diagnóstico remoto.

---

### 🛠️ 4. Ventana de Configuración (`Ajustes`)

La ventana de configuración cuenta con 6 pestañas y dos modos de guardado:
* **Aplicar:** Guarda los cambios en `config.json` y mantiene la ventana abierta.
* **Guardar:** Guarda los cambios y cierra la ventana.

> **Recarga en caliente:** Los cambios de *sensibilidad de movimiento, tiempos de grabación, cooldowns, modo de mosaico, credenciales de Telegram/Correo y horarios* se aplican automáticamente en **menos de 5 segundos** sin necesidad de reiniciar. Únicamente los cambios de *IP, puertos, usuario o contraseña de las cámaras* requieren reiniciar la aplicación.

---

## 🔒 Seguridad y Compilación

### Protección de Credenciales
* Al guardar desde la ventana de configuración, todas las contraseñas y tokens se cifran en `config.json` con prefijo `ENC:...` utilizando una clave secreta única generada en `camarasIP/.secret.key` vinculada al identificador de hardware del equipo.
* Nunca subas `config.json` ni `camarasIP/.secret.key` a repositorios públicos (asegúrate de incluirlos en tu `.gitignore`).

### Compilación a Ejecutable (Windows / Linux)
Para generar un ejecutable independiente con **PyInstaller**:

```bash
pyinstaller --noconsole --onedir --name "StiViHome_CCTV" main.py
```

*(Recuerda copiar `ffmpeg` y `ffplay` junto al ejecutable generado si el equipo de destino no los tiene instalados en el sistema).*

## 🛠️ Especificaciones Técnicas y Arquitectura

### 1. Motor de Vídeo y Codificación
* **Resolución de Captura y Mosaico:** Cada celda opera a **640×360 px** (16:9), generando un lienzo base de **1280×720 px** (HD) más un panel de control lateral de **360×720 px** (resolución total de ventana: **1640×720 px**).
* **Formato de Grabación:** Contenedor **MP4** con vídeo **H.264 (`libx264`, preset `ultrafast`, CRF 26, perfil `yuv420p`)** y flag `+faststart` para reproducción inmediata desde cualquier navegador web o teléfono móvil.
* **Segmentación Continua:** División automática de las grabaciones continuas en bloques configurables (por defecto **10 minutos** por archivo) para evitar pérdida de datos ante cortes eléctricos.
* **Búfer Circular de Eventos (Pre-Buffer):** Almacenamiento dinámico en memoria RAM mediante `collections.deque` (por defecto **100 fotogramas** a 20 FPS = **5 segundos previos** al evento) más **15 segundos posteriores** prorrogables mientras persista el movimiento.

### 2. Procesamiento de Audio Bidireccional
* **Entrada de Audio (Cámara → PC):**
  * **RTSP:** Extracción directa bajo demanda mediante tuberías `FFmpeg` en formato PCM `s16le` (8000 Hz, mono) y reproducción en vivo de baja latencia con `ffplay`.
  * **DVRIP / XMeye:** Decodificación nativa en tiempo real mediante tabla vectorizada NumPy desde **G.711 A-Law** a **PCM int16 (8000 Hz)** y salida por `sounddevice`.
* **Salida de Audio (PC → Cámara):** Captura desde el micrófono local a **8000 Hz / 16 bits** en bloques de 320 muestras, codificación al vuelo a **G.711 A-Law** y transmisión por socket TCP mediante el comando propietario NetIP `OPTalk`.
* **Grabación con Audio:** Multiplexado síncrono de vídeo raw y audio PCM mediante descriptores de archivo (`os.pipe`) hacia `FFmpeg`, codificando la pista de sonido en **AAC a 64 kbps**.

### 3. Protocolos de Red y Control PTZ
* **RTSP sobre TCP:** Transporte forzado por TCP (`rtsp_transport;tcp`) para evitar artefactos y pérdida de paquetes en redes Wi-Fi o con congestión.
* **ONVIF (Perfil S / PTZ):** Descubrimiento automático de perfiles multimedia, movimiento continuo (`ContinuousMove` con parada controlada) y gestión de posiciones predefinidas (`GotoPreset` / `SetPreset`).
* **NetIP / DVRIP (Puerto 34567):** Autenticación con hash propietario XMeye, flujo dual simultáneo para cámaras de doble lente (unión vertical de canal 0 y canal 1), control de iluminación LED (`Camera.WhiteLight`) y comandos PTZ (`OPPTZControl`).

### 4. Concurrencia, Tolerancia a Fallos y Rendimiento
* **Arquitectura Multihilo Thread-Safe:** Captura de vídeo, decodificación FFmpeg, detección de movimiento, envío de alertas SMTP/Telegram, escucha del bot y renderizado de interfaz operan en hilos independientes sincronizados mediante cerrojos reentrantes (`threading.RLock`) y semáforos de red (`threading.Semaphore`).
* **Detección de Movimiento de Bajo Consumo:** Submuestreo espacial al 50% (`320×180 px`), desenfoque gaussiano `(15×15)` y sustracción adaptativa de fondo (`addWeighted`), reduciendo en un **75% la carga de CPU** por fotograma sin sacrificar precisión.
* **Watchdog de Salud Activa:** Monitorización continua cada **3 segundos** mediante huella rápida de píxeles; si un flujo se congela durante más de **8 segundos**, fuerza su reconexión automática y envía una alerta si la caída supera los **3 minutos**.
* **Gestión de Almacenamiento y Logs:** Retención circular automática en disco con margen de seguridad (libera hasta el 90% del límite en GB) y rotación de registros (`RotatingFileHandler` con archivos de 2 MB y 3 copias de respaldo).


### Instalación de Dependencias Python
Crea un entorno virtual e instala las librerías listadas en `requirements.txt`:

```bash
python -m venv venv
# En Windows:
venv\Scripts\activate
# En Linux:
source venv/bin/activate

pip install -r requirements.txt
```

Contenido del archivo `requirements.txt`:

```text
opencv-python>=4.8.0
numpy>=1.24.0
sounddevice>=0.4.6
onvif-zeep>=0.2.12
python-dvrip>=0.1.3
```

#### Notas importantes de instalación
* **Módulos incluidos en Python:**  
`tkinter`, `json`, `smtplib`, `http.client`, `logging`, `hashlib`, `hmac`, `uuid` y `subprocess`   
forman parte de la librería estándar de Python y no deben incluirse en `requirements.txt`.
* **En Linux (Ubuntu/Debian):** Si `tkinter` o `sounddevice` dan error al instalar o ejecutar, instala los paquetes de sistema correspondientes antes de ejecutar `pip install -r requirements.txt`:
  ```bash
  sudo apt update && sudo apt install -y python3-tk libportaudio2 ffmpeg
  ```
* **Dependencia externa obligatoria:** Asegúrate de tener `ffmpeg` y `ffplay` instalados y accesibles en el `PATH` del sistema (no se instalan vía `pip`).
