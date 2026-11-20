"""
servidor_web.py
Servidor web local (Flask) diseñado para ejecutarse en segundo plano o detrás de Apache Proxy Inverso.
Proporciona:
  - Retransmisión de vídeo en directo (MJPEG) sin abrir conexiones extra contra las cámaras.
  - Controles PTZ, captura manual, grabación, detección y luces LED por cámara.
  - Consulta y filtrado dinámico (por cámara y fecha) del historial en MySQL/MariaDB.
  - Descarga y reproducción de grabaciones MP4.
  - Autenticación HTTP Basic con lectura en caliente de credenciales desde config.py.
"""

from functools import wraps
import logging
import os
import threading
import time
import cv2
from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    render_template_string,
    request,
    send_from_directory,
)

from base_datos import obtener_eventos_filtrados
import config

app = Flask(__name__)
_CAMARAS = []


# ==============================================================================
# SEGURIDAD Y AUTENTICACIÓN HTTP BASIC
# ==============================================================================

def _requiere_auth(f):
    """Decorador que protege todas las rutas usando las credenciales vigentes en config.py."""
    @wraps(f)
    def decorador(*args, **kwargs):
        auth = request.authorization
        usuario_valido = str(getattr(config, "WEB_USUARIO", "admin")).strip()
        password_valida = str(getattr(config, "WEB_PASSWORD", "stivihome2026")).strip()

        if auth is None or auth.username != usuario_valido or auth.password != password_valida:
            return Response(
                "Acceso restringido - Sistema de Videovigilancia StiVi-Home",
                401,
                {"WWW-Authenticate": 'Basic realm="StiVi-Home CCTV"'},
            )
        return f(*args, **kwargs)
    return decorador


# ==============================================================================
# PLANTILLA HTML / CSS / JS DEL CENTRO DE CONTROL WEB
# ==============================================================================

HTML_PANEL = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>StiVi-Home CCTV — Centro de Control</title>
    <style>
        :root {
            --bg-main: #12171e;
            --bg-card: #1e293b;
            --bg-input: #334155;
            --border-color: #334155;
            --text-main: #f1f5f9;
            --text-muted: #94a3b8;
            --accent: #38bdf8;
            --danger: #dc2626;
            --success: #16a34a;
        }
        body {
            background: var(--bg-main);
            color: var(--text-main);
            font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
            margin: 0;
            padding: 16px;
        }
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 10px;
        }
        h1 { font-size: 1.3rem; margin: 0; color: var(--accent); }
        h2 { font-size: 1.1rem; margin: 0 0 12px 0; color: var(--text-main); }

        /* Cuadrícula adaptable de cámaras */
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
            gap: 14px;
        }
        .card {
            background: var(--bg-card);
            border-radius: 10px;
            padding: 12px;
            border: 1px solid var(--border-color);
        }
        .header-cam {
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-weight: 600;
            margin-bottom: 8px;
            font-size: 0.95rem;
        }
        .badge-luz {
            background: var(--bg-input);
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 0.8rem;
            color: var(--text-muted);
        }
        .card img {
            width: 100%;
            border-radius: 6px;
            display: block;
            margin-bottom: 10px;
            background: #000;
        }

        /* Controles PTZ y botones de acción */
        .controls {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            justify-content: space-between;
            align-items: center;
        }
        .ptz {
            display: grid;
            grid-template-columns: repeat(3, 36px);
            gap: 4px;
        }
        .btns {
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            flex: 1;
            justify-content: flex-end;
        }
        button {
            background: var(--bg-input);
            color: #fff;
            border: none;
            border-radius: 6px;
            padding: 7px 10px;
            cursor: pointer;
            font-size: 0.84rem;
            transition: background 0.15s;
        }
        button:hover { background: #475569; }
        .rec-on { background: var(--danger) !important; }
        .det-on { background: var(--success) !important; }

        /* Secciones inferiores (Historial y Vídeos) */
        .section {
            margin-top: 20px;
            background: var(--bg-card);
            padding: 16px;
            border-radius: 10px;
            border: 1px solid var(--border-color);
        }
        .filtros {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-bottom: 12px;
            align-items: center;
        }
        select, input[type="date"] {
            background: var(--bg-input);
            color: #fff;
            border: 1px solid #475569;
            padding: 6px 10px;
            border-radius: 6px;
            font-size: 0.88rem;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.88rem;
        }
        th, td {
            text-align: left;
            padding: 9px 8px;
            border-bottom: 1px solid var(--border-color);
        }
        th { color: var(--text-muted); font-weight: 600; }
        ul.lista-videos {
            list-style: none;
            padding: 0;
            margin: 0;
            max-height: 260px;
            overflow-y: auto;
        }
        ul.lista-videos li {
            padding: 7px 4px;
            border-bottom: 1px solid var(--border-color);
            font-size: 0.9rem;
        }
        a { color: var(--accent); text-decoration: none; }
        a:hover { text-decoration: underline; }
    </style>
</head>
<body>
    <header>
        <h1>🛡️ StiVi-Home — Centro de Control Web</h1>
        <span style="color: var(--text-muted); font-size: 0.85rem;">Cámaras activas: {{ camaras|length }}</span>
    </header>

    <!-- CUADRÍCULA DE CÁMARAS EN DIRECTO -->
    <div class="grid">
        {% for idx, cam in camaras %}
        <div class="card">
            <div class="header-cam">
                <span>[{{ idx + 1 }}] {{ cam.nombre }}</span>
                <span class="badge-luz">Luz: {{ cam.modo_luz_actual }}</span>
            </div>
            <img src="/stream/{{ idx }}" alt="{{ cam.nombre }}">
            <div class="controls">
                <div class="ptz">
                    <div></div>
                    <button title="Arriba" onclick="accion({{ idx }}, 'ptz_arriba')">⬆️</button>
                    <div></div>
                    <button title="Izquierda" onclick="accion({{ idx }}, 'ptz_izq')">⬅️</button>
                    <button title="Capturar Foto" onclick="accion({{ idx }}, 'foto')">📸</button>
                    <button title="Derecha" onclick="accion({{ idx }}, 'ptz_der')">➡️</button>
                    <div></div>
                    <button title="Abajo" onclick="accion({{ idx }}, 'ptz_abajo')">⬇️</button>
                    <div></div>
                </div>
                <div class="btns">
                    <button class="{{ 'rec-on' if cam.grabando else '' }}" onclick="accion({{ idx }}, 'grabar')">
                        {{ '⏹️ Parar REC' if cam.grabando else '🔴 Grabar' }}
                    </button>
                    <button class="{{ 'det-on' if cam.deteccion_activa else '' }}" onclick="accion({{ idx }}, 'deteccion')">
                        {{ '👁️ Detec ON' if cam.deteccion_activa else '👁️ Detec OFF' }}
                    </button>
                    <button onclick="accion({{ idx }}, 'luz_blanca')">💡 Blanca</button>
                    <button onclick="accion({{ idx }}, 'luz_ir')">🌙 IR</button>
                    <button onclick="accion({{ idx }}, 'luz_auto')">🔄 Auto</button>
                </div>
            </div>
        </div>
        {% endfor %}
    </div>

        <!-- HISTORIAL DE DETECCIONES (MYSQL) -->
    <div class="section">
        <h2>📋 Historial de Detecciones (MySQL)</h2>
        <div class="filtros">
            <select id="filtro_camara">
                <option value="">Todas las cámaras</option>
                {% for idx, cam in camaras %}
                <option value="{{ cam.nombre }}">{{ cam.nombre }}</option>
                {% endfor %}
            </select>
            <input type="date" id="filtro_fecha">
            <button onclick="filtrarHistorial()">🔍 Filtrar</button>
            <button onclick="limpiarFiltro()" style="background:#475569;">🔄 Limpiar</button>
        </div>
        <table>
            <thead>
                <tr>
                    <th>Fecha y Hora</th>
                    <th>Cámara</th>
                    <th>Tipo de Evento</th>
                </tr>
            </thead>
            <tbody id="tabla_eventos">
                {% for ev in eventos %}
                <tr>
                    <td>{{ ev.fecha }}</td>
                    <td>{{ ev.camara }}</td>
                    <td>{{ ev.tipo_evento }}</td>
                </tr>
                {% else %}
                <tr>
                    <td colspan="3" style="color: var(--text-muted);">Sin registros disponibles en MySQL.</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>

    <div class="section">
        <h2>🎥 Últimas Grabaciones MP4</h2>

        <ul class="lista-videos">
            {% for v in videos %}
            <li><a href="/descargar/video/{{ v }}" target="_blank">🎬 {{ v }}</a></li>
            {% else %}
            <li style="color: var(--text-muted);">No hay vídeos grabados todavía.</li>
            {% endfor %}
        </ul>
    </div>

    <script>
        function accion(idx, cmd) {
            fetch('/api/camara/' + idx + '/' + cmd, { method: 'POST' })
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (data.recargar) {
                        location.reload();
                    }
                })
                .catch(function(err) { console.error('Error ejecutando acción:', err); });
        }

        function filtrarHistorial() {
            const cam = encodeURIComponent(document.getElementById('filtro_camara').value);
            const fecha = encodeURIComponent(document.getElementById('filtro_fecha').value);

            fetch('/api/historial?camara=' + cam + '&fecha=' + fecha)
                .then(function(r) { return r.json(); })
                .then(function(datos) {
                    const tbody = document.getElementById('tabla_eventos');
                    if (!datos.length) {
                        tbody.innerHTML = '<tr><td colspan="3" style="color: var(--text-muted);">No se encontraron detecciones con ese filtro.</td></tr>';
                        return;
                    }
                    tbody.innerHTML = datos.map(function(ev) {
                        return '<tr><td>' + ev.fecha + '</td><td>' + ev.camara + '</td><td>' + ev.tipo_evento + '</td></tr>';
                    }).join('');
                })
                .catch(function(err) { console.error('Error filtrando historial:', err); });
        }

        function limpiarFiltro() {
            document.getElementById('filtro_camara').value = '';
            document.getElementById('filtro_fecha').value = '';
            filtrarHistorial();
        }
    </script>
</body>
</html>
"""


# ==============================================================================
# GENERADOR DE FLUJO MJPEG EN DIRECTO
# ==============================================================================

def _generar_mjpeg(indice):
    """Genera fotogramas JPEG continuos a ~15 FPS desde la caché thread-safe de cada cámara."""
    while True:
        if 0 <= indice < len(_CAMARAS):
            camara = _CAMARAS[indice]
            if getattr(camara, "detener", False):
                break
            frame = camara.frame
            if frame is not None:
                ok, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
                if ok:
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n"
                    )
        time.sleep(0.065)


# ==============================================================================
# RUTAS Y ENDPOINTS API DEL SERVIDOR WEB
# ==============================================================================

@app.route("/")
@_requiere_auth
def index():
    """Renderiza el panel principal con cámaras en vivo, historial MySQL y grabaciones."""
    videos = []
    carpeta_grab = getattr(config, "CARPETA_GRABACIONES", "")
    if carpeta_grab and os.path.isdir(carpeta_grab):
        videos = sorted(
            [f for f in os.listdir(carpeta_grab) if f.lower().endswith(".mp4")],
            reverse=True,
        )[:25]

    eventos = obtener_eventos_filtrados(limite=15)
    return render_template_string(
        HTML_PANEL,
        camaras=list(enumerate(_CAMARAS)),
        videos=videos,
        eventos=eventos,
    )


@app.route("/stream/<int:indice>")
@_requiere_auth
def stream_camara(indice):
    """Sirve el stream de vídeo MJPEG continuo."""
    if indice < 0 or indice >= len(_CAMARAS):
        abort(404)
    return Response(
        _generar_mjpeg(indice),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route("/api/camara/<int:indice>/<cmd>", methods=["POST"])
@_requiere_auth
def controlar_camara_web(indice, cmd):
    """Ejecuta comandos PTZ, grabación, detección o iluminación sobre la cámara indicada."""
    if indice < 0 or indice >= len(_CAMARAS):
        return jsonify({"ok": False, "error": "Cámara no encontrada"}), 404

    cam = _CAMARAS[indice]
    acciones = {
        "ptz_arriba": lambda: cam.mover_ptz(0.0, 0.5, 0.0),
        "ptz_abajo": lambda: cam.mover_ptz(0.0, -0.5, 0.0),
        "ptz_izq": lambda: cam.mover_ptz(0.5, 0.0, 0.0),
        "ptz_der": lambda: cam.mover_ptz(-0.5, 0.0, 0.0),
        "foto": cam.capturar_fotograma_manual,
        "grabar": cam.alternar_grabacion,
        "deteccion": cam.alternar_deteccion,
        "luz_blanca": lambda: cam.cambiar_luz_led("BLANCA"),
        "luz_ir": lambda: cam.cambiar_luz_led("IR"),
        "luz_auto": lambda: cam.cambiar_luz_led("AUTO"),
    }

    if cmd not in acciones:
        return jsonify({"ok": False, "error": "Comando no válido"}), 400

    acciones[cmd]()
    recargar = cmd in ("grabar", "deteccion", "luz_blanca", "luz_ir", "luz_auto")
    return jsonify({"ok": True, "recargar": recargar})


@app.route("/api/historial")
@_requiere_auth
def api_historial():
    """Devuelve en formato JSON las detecciones de MySQL filtradas por cámara y/o fecha."""
    camara = request.args.get("camara", "").strip()
    fecha = request.args.get("fecha", "").strip()
    eventos = obtener_eventos_filtrados(camara=camara, fecha=fecha, limite=50)
    return jsonify(eventos)


@app.route("/descargar/video/<path:nombre>")
@_requiere_auth
def descargar_video(nombre):
    """Permite reproducir en el navegador o descargar un archivo MP4 grabado."""
    carpeta_grab = getattr(config, "CARPETA_GRABACIONES", "")
    if not carpeta_grab or not os.path.isdir(carpeta_grab):
        abort(404)
    return send_from_directory(carpeta_grab, nombre)


# ==============================================================================
# INICIALIZACIÓN EN SEGUNDO PLANO
# ==============================================================================

def iniciar_servidor_web(camaras, host="127.0.0.1"):
    """Arranca el servidor Flask en un hilo daemon sin bloquear el bucle de OpenCV."""
    global _CAMARAS
    _CAMARAS = camaras

    if not getattr(config, "WEB_ACTIVO", True):
        print("[WEB] Servidor web desactivado en la configuración.")
        return

    puerto = int(getattr(config, "WEB_PUERTO", 8080))

    def _run():
        logging.getLogger("werkzeug").setLevel(logging.ERROR)
        app.run(host=host, port=puerto, threaded=True, use_reloader=False)

    threading.Thread(target=_run, daemon=True).start()
    print(f"[WEB] Servidor web activo en http://{host}:{puerto}")
    
    
    
    '''
    
    Cómo conectarlo en `main.py`
Asegúrate de tener estas líneas en tu **`main.py`** para arrancar tanto la base de datos como el servidor web:

1. En las importaciones superiores de `main.py`:

import base_datos
import servidor_web

2. Dentro de main(), justo después de mantenimiento.iniciar():

    mantenimiento = GestorMantenimiento(CAMARAS)
    mantenimiento.iniciar()
    base_datos.inicializar_bd()
    servidor_web.iniciar_servidor_web(CAMARAS, host="127.0.0.1")
    
    
    
    '''
    
