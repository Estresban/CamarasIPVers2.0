import os
import sys
import tkinter as tk
from unittest.mock import MagicMock, patch
import cv2
import numpy as np

from camara_base import CamaraBase
from camaras import CamaraDVRIP, CamaraRTSP
import config
import configuracion
import correo_alertas
from escritor_video import EscritorVideoH264
import main
from mantenimiento import GestorMantenimiento
import notificaciones
from watchdog import WatchdogCamaras


def test_francotirador_ultimas_lineas():
    # 1. camara_base.py (línea 428): cerrar_base con video_writer activo
    cam_b = CamaraBase({"nombre": "B", "ip": "1.1.1.1", "usuario": "u", "password": "p", "puerto_netip": 1}, 0)
    w_mock = MagicMock()
    cam_b.video_writer = w_mock
    cam_b.cerrar_base()
    w_mock.release.assert_called_once()

    # 2. camaras.py (líneas 126-127, 432-433)
    with patch("camaras.threading.Thread"):
        rtsp = CamaraRTSP({
            "nombre": "R", "ip": "1.1.1.1", "puerto_rtsp": 554, "puerto_onvif": 80,
            "usuario": "u", "password": "p", "canal": 1, "stream": 0
        }, 0)
        dvr = CamaraDVRIP({"nombre": "D", "ip": "1.1.1.2", "usuario": "u", "password": "p", "canales":(0, 1)}, 1)

    # _bucle_captura_audio_rtsp cuando no está grabando (sleep 0.5)
    rtsp.detener = False
    rtsp.grabando = False
    with patch("camaras.time.sleep", side_effect=lambda _: setattr(rtsp, "detener", True)):
        rtsp._bucle_captura_audio_rtsp()

    # _reproducir_audio en DVRIP con error en OutputStream
    with patch("camaras.sd.OutputStream", side_effect=RuntimeError("Audio err")):
        dvr._reproducir_audio()

    # 3. configuracion.py (línea 462): OSError al eliminar config.json en restaurar()
    botones_cfg = {}

    class BtnFake:
        def __init__(self, _p, text="", command=None, **_kw):
            botones_cfg[text] = command
        def pack(self, *_a, **_kw):
            pass

    def run_restaurar_err(_self):
        with patch("configuracion.os.path.exists", return_value=True), \
             patch("configuracion.os.remove", side_effect=OSError("Bloqueado")):
            botones_cfg["Restaurar valores"]()

    with patch("configuracion.ttk.Button", BtnFake), \
         patch("configuracion.messagebox.askyesno", return_value=True), \
         patch("configuracion.messagebox.showerror") as mock_err_cfg, \
         patch.object(tk.Tk, "mainloop", run_restaurar_err):
        configuracion.iniciar()
        assert mock_err_cfg.called

    # 4. correo_alertas.py (líneas 139, 167-168, 194)
    correo_alertas.email_alertas_activas = True
    with patch("correo_alertas._obtener_config_email", return_value={"adjuntar_foto": False, "intervalo_alertas": 60}), \
         patch("correo_alertas._despachar_mensaje_smtp", return_value=False):
        assert correo_alertas.enviar_correo_evento(cam_b, "ev") is False

    correo_alertas._ultimos_envios.clear()
    with patch("correo_alertas._obtener_config_email", return_value={"adjuntar_foto": False, "intervalo_alertas": 60}), \
         patch("correo_alertas.json.dumps", side_effect=TypeError("No JSON")), \
         patch("correo_alertas.threading.Thread"):
        correo_alertas.procesar_evento_correo(cam_b, {"a": 1}, 1)

    correo_alertas.email_alertas_activas = False
    correo_alertas.enviar_alerta_correo_rtsp("CamX", None)

    # 5. escritor_video.py (líneas 93, 118-119)
    with patch("escritor_video.os.pipe", return_value=(10, 11)), \
         patch("escritor_video.os.set_inheritable"), \
         patch("escritor_video.os.close"), \
         patch("escritor_video.subprocess.Popen") as mock_p:
        mock_p.return_value.wait.side_effect = RuntimeError("Timeout")
        mock_p.return_value.kill.side_effect = OSError("Kill err")
        ew = EscritorVideoH264("x.mp4", 25, 10, 10, con_audio=True)
        ew.write_audio(b"")  # Retorno temprano línea 93
        ew.release()

    # 6. main.py (líneas 291-292, 560, 612-614, 648-649)
    lienzo = np.zeros((100, 100, 3), dtype=np.uint8)
    main.dibujar_icono(lienzo, "zoom_menos", 50, 50, True)
    main.al_hacer_clic_panel(cv2.EVENT_LBUTTONDOWN, 1, 1, [])

    cam_ui = MagicMock()
    cam_ui.obtener_imagen_ui.return_value = np.zeros((360, 640, 3), dtype=np.uint8)
    cam_ui.modo_luz_actual = "AUTO"
    with patch("main.sys.platform", "win32"), \
         patch("main.preparar_carpetas"), \
         patch("main.iniciar_camaras", return_value=[cam_ui]), \
         patch("main.notificaciones.iniciar_bot_comandos"), \
         patch("main.notificaciones.detener_bot"), \
         patch("main.WatchdogCamaras"), \
         patch("main.GestorMantenimiento") as mock_m, \
         patch("main.cv2.namedWindow"), \
         patch("main.cv2.resizeWindow"), \
         patch("main.cv2.setMouseCallback"), \
         patch("main.cv2.imshow"), \
         patch("main.cv2.waitKeyEx", return_value=-1), \
         patch("main.cv2.getWindowProperty", side_effect=cv2.error("Ventana cerrada")), \
         patch("main.cv2.destroyAllWindows"):
        mock_m.return_value.obtener_estado_visual.return_value = None
        main.main()

        # 7. mantenimiento.py (líneas 86-87, 90, 100, 107-108, 133, 169)
    gm = GestorMantenimiento([])
    stat_calls = {"n": 0}

    def fake_stat(_ruta):
        stat_calls["n"] += 1
        if stat_calls["n"] == 1:
            raise OSError("Stat err")
        return MagicMock(st_size=2000, st_mtime=0.0)

    with patch("mantenimiento.os.path.isdir", return_value=True), \
         patch("mantenimiento.os.walk", return_value=[("/dir", [], ["a.mp4", "b.mp4"])]), \
         patch("mantenimiento.os.stat", side_effect=fake_stat), \
         patch("mantenimiento.os.remove", side_effect=OSError("Remove err")):
        gm._limpiar_disco_si_excede(1 / (1024 ** 3))


    # 8. notificaciones.py (líneas 104, 191, 206-207, 327-329, 353-354)
    with patch("notificaciones._obtener_credenciales", return_value=("TK", "ID")), \
         patch("notificaciones.http.client.HTTPSConnection") as mock_http:
        notificaciones.enviar_mensaje_telegram("Sin teclado", incluir_teclado=False)
        assert mock_http.called

    notificaciones.alertas_activas = False
    notificaciones.enviar_video_evento("v.mp4", "Cam")
    notificaciones.enviar_alerta_movimiento(np.zeros((10, 10, 3), dtype=np.uint8), "Cam")

    with patch("notificaciones.enviar_mensaje_telegram"), \
         patch("notificaciones.os.path.exists", return_value=True), \
         patch("builtins.open", side_effect=OSError("Lectura err")):
        notificaciones._procesar_comando("/historial", [cam_ui])
        notificaciones._procesar_comando("/logs", [cam_ui])

    # 9. watchdog.py (línea 46): _bucle_vigilancia sale inmediatamente si se detiene en la espera inicial
    wd = WatchdogCamaras([])
    wd.cerrar()
    wd._bucle_vigilancia()
