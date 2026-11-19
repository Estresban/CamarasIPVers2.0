import queue
from unittest.mock import MagicMock, patch
import numpy as np
from camaras import CamaraDVRIP, CamaraRTSP
from config import ALTO_LENTE_DVRIP, ANCHO_CELDA


CFG_RTSP = {
    "nombre": "Entrada",
    "ip": "192.168.1.50",
    "puerto_rtsp": 554,
    "puerto_onvif": 80,
    "usuario": "admin",
    "password": "123",
    "canal": 1,
    "stream": 0,
}

CFG_DVRIP = {
    "nombre": "Patio",
    "ip": "192.168.1.51",
    "usuario": "admin",
    "password": "123",
    "canales":[0,1],
}


def test_camara_rtsp_ptz_presets_y_audio():
    with patch("camaras.threading.Thread"):
        cam = CamaraRTSP(CFG_RTSP, 0)

    # Simular conexión ONVIF
    mock_onvif = MagicMock()
    perfil = MagicMock()
    perfil.token = "prof_1"
    mock_onvif.create_media_service.return_value.GetProfiles.return_value = [perfil]
    with patch("camaras.ONVIFCamera", return_value=mock_onvif):
        cam._conectar_onvif()
    assert cam.media_profile.token == "prof_1"

    # Ejecutar hilos internos de PTZ y presets directamente
    with patch("camaras.threading.Thread") as mock_th, patch("camaras.time.sleep"):
        mock_th.side_effect = lambda target, daemon=True: MagicMock(start=target)
        cam.mover_ptz(pan=0.5)
        cam.ir_a_preset(1)
        cam.guardar_preset(2)

    assert cam.ptz.ContinuousMove.called
    assert cam.ptz.Stop.called
    assert cam.ptz.GotoPreset.called
    assert cam.ptz.SetPreset.called

    # Alternar escucha de audio (ffplay) y cierre
    with patch("camaras.subprocess.Popen") as mock_popen:
        cam.alternar_escuchar_audio()
        assert cam.escuchando_audio is True
        cam.cerrar()
        assert mock_popen.return_value.terminate.called


def test_camara_rtsp_bucle_video_y_audio():
    with patch("camaras.threading.Thread"):
        cam = CamaraRTSP(CFG_RTSP, 0)

    # Bucle de vídeo: 1º frame válido, 2º fallo de lectura (reconecta), 3º detiene
    cap_mock = MagicMock()
    frame_ok = np.zeros((200, 200, 3), dtype=np.uint8)

    def leer_frames():
        if not hasattr(leer_frames, "n"):
            leer_frames.n = 0
        leer_frames.n += 1
        if leer_frames.n == 1:
            return True, frame_ok
        if leer_frames.n == 2:
            return False, None
        cam.detener = True
        return False, None

    cap_mock.read.side_effect = leer_frames

    with patch("camaras.cv2.VideoCapture", return_value=cap_mock), \
         patch("camaras.time.sleep"), \
         patch.object(cam, "_procesar_nuevo_fotograma") as mock_proc:
        cam._bucle_video()

    assert mock_proc.called
    assert cap_mock.release.call_count >= 2

    # Bucle captura audio RTSP
    cam.detener = False
    cam.grabando = True
    proc_audio = MagicMock()
    proc_audio.stdout.read.side_effect = [b"\x00" * 1600, b""]

    def parar_en_sleep(_s):
        cam.detener = True

    with patch("camaras.subprocess.Popen", return_value=proc_audio), \
         patch("camaras.time.sleep", side_effect=parar_en_sleep), \
         patch.object(cam, "_procesar_nuevo_audio") as mock_aud:
        cam._bucle_captura_audio_rtsp()

    assert mock_aud.called


def test_camara_dvrip_callbacks_ffmpeg_y_ptz():
    with patch("camaras.threading.Thread"):
        cam = CamaraDVRIP(CFG_DVRIP, 1)

    # Callback de vídeo y audio g711a
    cam.escuchando_audio = True
    cb = cam._crear_callback(0)
    with patch("camaras.alaw_a_pcm", return_value=b"\x01\x02"), \
         patch.object(cam, "_procesar_nuevo_audio") as mock_aud:
        cb(b"h265data", {"frame": "I"}, None)
        cb(b"alawdata", {"type": "g711a"}, None)

    assert not cam.colas_video[0].empty()
    assert mock_aud.called

    # Alimentar FFmpeg
    proc_mock = MagicMock()
    proc_mock.poll.return_value = None
    cam.procesos[0] = proc_mock
    cam.colas_video[0].put(None)  # Señal de parada limpia
    cam._alimentar_ffmpeg(0)
    assert proc_mock.stdin.write.called

    # Leer FFmpeg y combinar lentes superior e inferior
    n_bytes = ANCHO_CELDA * ALTO_LENTE_DVRIP * 3
    cam.ultima_lente[1] = np.zeros((ALTO_LENTE_DVRIP, ANCHO_CELDA, 3), dtype=np.uint8)
    proc_leer = MagicMock()
    proc_leer.poll.return_value = None
    proc_leer.stdout.read.side_effect = [b"\x00" * n_bytes, b""]
    cam.procesos[0] = proc_leer

    with patch.object(cam, "_procesar_nuevo_fotograma") as mock_comb:
        cam._leer_ffmpeg(0)
    assert mock_comb.called

    # PTZ y Presets DVRIP
    cam.cam_control = MagicMock()
    with patch("camaras.threading.Thread") as mock_th, patch("camaras.time.sleep"):
        mock_th.side_effect = lambda target, daemon=True: MagicMock(start=target)
        cam.mover_ptz(tilt=1.0)
        cam.ir_a_preset(3)

    assert cam.cam_control.set_command.called
    cam.cerrar()

def test_camara_rtsp_errores_y_reconexion():
    with patch("camaras.threading.Thread"):
        cam = CamaraRTSP(CFG_RTSP, 0)

    # 1. Error al conectar ONVIF (líneas 57-58)
    with patch("camaras.ONVIFCamera", side_effect=RuntimeError("Sin red ONVIF")):
        cam._conectar_onvif()
    assert cam.ptz is None

    # 2. Llamadas PTZ/presets sin inicializar o con lock ocupado (líneas 62, 66, 83, 87, 103, 107)
    cam.mover_ptz(0.5)
    cam.ir_a_preset(1)
    cam.guardar_preset(1)

    cam.ptz = MagicMock()
    cam.media_profile = MagicMock()
    cam.ptz.ContinuousMove.side_effect = RuntimeError("Fallo PTZ")
    cam.ptz.GotoPreset.side_effect = RuntimeError("Fallo Goto")
    cam.ptz.SetPreset.side_effect = RuntimeError("Fallo Set")

    with patch("camaras.threading.Thread") as mock_th, patch("camaras.time.sleep"):
        mock_th.side_effect = lambda target, daemon=True: MagicMock(start=target)
        # Primero probamos con lock bloqueado
        cam.lock_red.acquire()
        cam.mover_ptz(zoom=0.5)
        cam.ir_a_preset(1)
        cam.guardar_preset(1)
        cam.lock_red.release()

        # Ahora con lock libre pero lanzando excepciones internas (líneas 74-75, 94-95, 115-116)
        cam.mover_ptz(zoom=0.5)
        cam.ir_a_preset(1)
        cam.guardar_preset(1)

    # 3. Forzar reconexión en _bucle_video y errores en captura de audio (líneas 126-127, 155-156, 169-181)
    cam.forzar_reconexion()
    assert cam.forzar_reinicio_stream is True

    cap_mock = MagicMock()
    def leer_tras_reinicio():
        cam.detener = True
        return False, None

    cap_mock.read.side_effect = leer_tras_reinicio
    with patch("camaras.cv2.VideoCapture", return_value=cap_mock), patch("camaras.time.sleep"):
        cam._bucle_video()

    # Audio con excepción en Popen y cierre con kill() tras TimeoutExpired
    cam.detener = False
    cam.grabando = True
    with patch("camaras.subprocess.Popen", side_effect=OSError("Sin ffmpeg")), \
         patch("camaras.time.sleep", side_effect=lambda _: setattr(cam, "detener", True)):
        cam._bucle_captura_audio_rtsp()

    proc_colgado = MagicMock()
    proc_colgado.wait.side_effect = Exception("Timeout")
    cam.proceso_ffplay = proc_colgado
    cam.cerrar()
    assert proc_colgado.kill.called


def test_camara_dvrip_inicio_monitor_audio_y_cierre(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # Evita dejar archivos .log sueltos en tu carpeta raíz
    with patch("camaras.threading.Thread"):
        cam = CamaraDVRIP(CFG_DVRIP, 1)

    # 1. _iniciar_dvrip exitoso y con fallo de login (líneas 226-253)
    cam_ok = MagicMock()
    cam_ok.login.return_value = True
    with patch("camaras.DVRIPCam", return_value=cam_ok), \
         patch("camaras.subprocess.Popen", return_value=MagicMock()), \
         patch("camaras.threading.Thread"):
        cam._iniciar_dvrip()
        assert cam.conectada is True

    cam_fail = MagicMock()
    cam_fail.login.return_value = False
    with patch("camaras.DVRIPCam", return_value=cam_fail):
        cam._iniciar_dvrip()
        assert cam.conectada is False

    # 2. _bucle_monitor_dvrip con reconexión tras caída (líneas 256-271)
    cam_mon = MagicMock()
    def fallar_monitor(*_args, **_kwargs):
        cam.detener = True
        raise RuntimeError("Desconexión DVRIP")

    cam_mon.start_monitor.side_effect = fallar_monitor
    cam.camaras_dvrip = {0: cam_mon}
    cam.detener = False
    # Hacemos que en el except aún no esté detenido para que entre en el bloque de reconexión
    def fallar_y_detener_en_login():
        cam.detener = True
        return True

    cam_nueva = MagicMock()
    cam_nueva.login.side_effect = fallar_y_detener_en_login
    cam_mon.start_monitor.side_effect = RuntimeError("Caída")
    with patch("camaras.DVRIPCam", return_value=cam_nueva), patch("camaras.time.sleep"):
        cam._bucle_monitor_dvrip(0)
    assert cam.camaras_dvrip[0] is cam_nueva

    # 3. Cola llena en callback y reproducción de audio OutputStream (líneas 280-283, 291-294, 414-437)
    cam.detener = False
    cam.escuchando_audio = True
    for _ in range(60):
        cam.colas_video.get(0).put(b"x")
        cam.cola_audio.put(b"a")

    cb = cam._crear_callback(0)
    with patch("camaras.alaw_a_pcm", return_value=b"\x01\x02"), \
         patch.object(cam, "_procesar_nuevo_audio"):
        cb(b"nuevo_frame", {"frame": "P"}, None)
        cb(b"nuevo_audio", {"type": "g711a"}, None)

    stream_mock = MagicMock()
    def escribir_y_parar(_datos):
        cam.escuchando_audio = False

    stream_mock.__enter__.return_value.write.side_effect = escribir_y_parar
    with patch("camaras.sd.OutputStream", return_value=stream_mock):
        cam._reproducir_audio()
    assert cam.escuchando_audio is False

    # 4. Alternar audio, forzar_reconexion y cerrar completo (líneas 444-490)
    with patch("camaras.threading.Thread"):
        cam.alternar_escuchar_audio()
        assert cam.escuchando_audio is True
        cam.forzar_reconexion()

    proc_dvr = MagicMock()
    proc_dvr.wait.side_effect = Exception("No cierra")
    cam.procesos = {0: proc_dvr}
    cam.cam_control = MagicMock()
    cam.cerrar()
    assert proc_dvr.kill.called


def test_camaras_ramas_residuales_y_cierre_forzado():
    # 1. CamaraRTSP: cierre normal de ffplay (126-127, 155-156, 204-205)
    with patch("camaras.threading.Thread"):
        rtsp = CamaraRTSP(CFG_RTSP, 0)

    proc_ff = MagicMock()
    rtsp.proceso_ffplay = proc_ff
    rtsp.escuchando_audio = True
    rtsp.alternar_escuchar_audio()  # Apaga audio y llama a terminate()
    assert proc_ff.terminate.called

    # 2. CamaraDVRIP: ramas de excepción, locks ocupados y cierres con error (259, 276, 308-309, 347-490)
    with patch("camaras.threading.Thread"):
        dvr = CamaraDVRIP(CFG_DVRIP, 1)

    # _bucle_monitor_dvrip cuando no existe el canal
    dvr.camaras_dvrip = {}
    dvr._bucle_monitor_dvrip(99)

    # _crear_callback con frame None
    cb = dvr._crear_callback(0)
    cb(None, {"frame": "I"}, None)

    # _alimentar_ffmpeg con OSError al escribir en stdin
    proc_err = MagicMock()
    proc_err.poll.return_value = None
    proc_err.stdin.write.side_effect = OSError("Pipe roto")
    dvr.procesos = {0: proc_err}
    dvr.colas_video.get(0).put(b"datos")
    dvr._alimentar_ffmpeg(0)

    # guardar_preset y errores de red en PTZ/presets DVRIP (347, 351, 369-370, 379, 383, 399-400, 410)
    dvr.mover_ptz(0, 0, 0)  # Dirección inválida -> return temprano
    dvr.guardar_preset(1)   # Sin cam_control -> return temprano

    dvr.cam_control = MagicMock()
    dvr.cam_control.set_command.side_effect = RuntimeError("Error DVRIP")
    with patch("camaras.threading.Thread") as mock_th, patch("camaras.time.sleep"):
        mock_th.side_effect = lambda target, daemon=True: MagicMock(start=target)
        # Lock ocupado
        dvr.lock_red.acquire()
        dvr.mover_ptz(pan=1.0)
        dvr.guardar_preset(1)
        dvr.lock_red.release()

        # Lock libre pero set_command lanza excepción
        dvr.mover_ptz(pan=1.0)
        dvr.guardar_preset(1)

    # _reproducir_audio cuando OutputStream falla (432-435)
    with patch("camaras.sd.OutputStream", side_effect=RuntimeError("Sin tarjeta sonido")):
        dvr._reproducir_audio()
    assert dvr.escuchando_audio is False

    # forzar_reconexion con lock ocupado (455-456)
    dvr.lock_red.acquire()
    dvr.forzar_reconexion()
    dvr.lock_red.release()

    # cerrar() con excepciones en stop_monitor, cam_control.close y log.close (477-490)
    cam_bad = MagicMock()
    cam_bad.stop_monitor.side_effect = RuntimeError("Fallo stop")
    dvr.camaras_dvrip = {0: cam_bad}
    dvr.cam_control.close.side_effect = RuntimeError("Fallo close")
    log_bad = MagicMock()
    log_bad.close.side_effect = RuntimeError("Fallo log")
    dvr.logs = {0: log_bad}
    dvr.cerrar()

def test_camaras_excepciones_defensivas_internas():
    # 1. CamaraRTSP: errores en terminate() de ffmpeg audio (155-156) y ffplay en cerrar() (204-205)
    with patch("camaras.threading.Thread"):
        rtsp = CamaraRTSP(CFG_RTSP, 0)

    rtsp.grabando = True
    proc_audio_err = MagicMock()
    proc_audio_err.stdout.read.return_value = b""
    proc_audio_err.terminate.side_effect = OSError("Error terminate ffmpeg")
    with patch("camaras.subprocess.Popen", return_value=proc_audio_err):
        rtsp.detener = False
        # Cortamos el bucle en el finally haciendo que detener sea True al llamar a terminate
        def detener_en_term():
            rtsp.detener = True
            raise OSError("Error terminate")

        proc_audio_err.terminate.side_effect = detener_en_term
        rtsp._bucle_captura_audio_rtsp()

    proc_ffplay_err = MagicMock()
    proc_ffplay_err.wait.side_effect = RuntimeError("Timeout")
    proc_ffplay_err.kill.side_effect = OSError("No se puede matar")
    rtsp.proceso_ffplay = proc_ffplay_err
    rtsp.cerrar()

    # 2. CamaraDVRIP: excepciones en cam.close() al reconectar (267-268), queue.Empty simulado (282-283, 293-294, 419-420),
    # excepción en sd.OutputStream (432-433) y excepción en _detener_procesos_ffmpeg (455-456)
    with patch("camaras.threading.Thread"):
        dvr = CamaraDVRIP(CFG_DVRIP, 1)

    cam_vieja = MagicMock()
    cam_vieja.start_monitor.side_effect = RuntimeError("Caída")
    cam_vieja.close.side_effect = RuntimeError("Fallo al cerrar socket viejo")
    cam_nueva = MagicMock()
    cam_nueva.login.side_effect = lambda: setattr(dvr, "detener", True) or False
    dvr.camaras_dvrip = {0: cam_vieja}
    with patch("camaras.DVRIPCam", return_value=cam_nueva), patch("camaras.time.sleep"):
        dvr._bucle_monitor_dvrip(0)

    # Simular cola llena que lanza queue.Empty en get_nowait() (race condition entre hilos)
    cola_race = MagicMock()
    cola_race.full.return_value = True
    cola_race.get_nowait.side_effect = queue.Empty()
    dvr.colas_video = {0: cola_race}
    dvr.cola_audio = cola_race
    dvr.detener = False
    dvr.escuchando_audio = True
    cb = dvr._crear_callback(0)
    with patch("camaras.alaw_a_pcm", return_value=b"\x00\x01"), \
         patch.object(dvr, "_procesar_nuevo_audio"):
        cb(b"frame", {"frame": "I"}, None)
        cb(b"audio", {"type": "g711a"}, None)

    # alternar_escuchar_audio cuando cola_audio.empty() es False pero get_nowait() lanza queue.Empty (419-420)
    cola_audio_race = MagicMock()
    cola_audio_race.empty.side_effect = [False, True]
    cola_audio_race.get_nowait.side_effect = queue.Empty()
    dvr.cola_audio = cola_audio_race
    dvr.escuchando_audio = False
    with patch("camaras.threading.Thread"):
        dvr.alternar_escuchar_audio()

    # _detener_procesos_ffmpeg cuando kill() también lanza excepción (455-456)
    proc_inmortal = MagicMock()
    proc_inmortal.wait.side_effect = RuntimeError("Timeout")
    proc_inmortal.kill.side_effect = OSError("Acceso denegado")
    dvr.procesos = {0: proc_inmortal}
    dvr._detener_procesos_ffmpeg()
