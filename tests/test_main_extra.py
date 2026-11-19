from unittest.mock import MagicMock, patch
import cv2
import numpy as np
import main


def _crear_camara_falsa(nombre="CamTest"):
    cam = MagicMock()
    cam.nombre = nombre
    cam.deteccion_activa = True
    cam.grabando = False
    cam.captura_auto_activa = False
    cam.escuchando_audio = False
    cam.hablando_micro = False
    cam.modo_luz_actual = "AUTO"
    cam.grabador_eventos.activa = True
    cam.obtener_imagen_ui.return_value = np.zeros((360, 640, 3), dtype=np.uint8)
    return cam


def test_dibujar_panel_e_iconos():
    cam = _crear_camara_falsa()
    mant = MagicMock()
    mant.obtener_estado_visual.return_value = "ARMADO 22:00-07:00"
    main.raton_panel = (120, 90)  # Simulamos hover sobre un botón

    panel = main.dibujar_panel(0, [cam], mant)
    assert panel.shape == (main.ALTO_TOTAL_BASE, main.ANCHO_PANEL, 3)


def test_clics_panel_y_mosaico():
    cam1 = _crear_camara_falsa("C1")
    cam2 = _crear_camara_falsa("C2")
    main.CAMARAS = [cam1, cam2]
    main.seleccionada = 0
    main.vista_ampliada = False
    main.salir_panel = False

    with patch("main.config.MODO_MOSAICO", 2):
        # Clic simple selecciona segunda cámara
        main.al_hacer_clic_camaras(cv2.EVENT_LBUTTONDOWN, 700, 100, main.CAMARAS)
        assert main.seleccionada == 1

        # Doble clic amplía y segundo doble clic vuelve al mosaico
        main.al_hacer_clic_camaras(cv2.EVENT_LBUTTONDBLCLK, 700, 100, main.CAMARAS)
        assert main.vista_ampliada is True
        main.al_hacer_clic_camaras(cv2.EVENT_LBUTTONDBLCLK, 700, 100, main.CAMARAS)
        assert main.vista_ampliada is False

    # Clic en todos los botones del panel
    for _, x1, y1, _, _, accion in main.BOTONES_PANEL:
        if accion != "salir":
            main.al_hacer_clic_panel(cv2.EVENT_LBUTTONDOWN, x1 + 5, y1 + 5, main.CAMARAS)

    assert cam2.mover_ptz.called
    assert cam2.alternar_deteccion.called

    # Clic en CERRAR
    _, x1, y1, _, _, _ = main.BOTONES_PANEL[-1]
    main.al_hacer_clic_panel(cv2.EVENT_LBUTTONDOWN, x1 + 5, y1 + 5, main.CAMARAS)
    assert main.salir_panel is True


def test_controles_teclado_y_flechas():
    cam = _crear_camara_falsa()
    main.CAMARAS = [cam]
    main.seleccionada = 0

    for tecla in [main.FLECHAS_IZQ[0], main.FLECHAS_ARR[0], main.FLECHAS_DER[0], main.FLECHAS_ABA[0]]:
        main.mover_ptz(cam, tecla)
    assert cam.mover_ptz.call_count == 4

    for ch in ["w", "m", "r", "f", " ", "v", "t", "+", "-", "1", "2", "3", "4", "7", "\t"]:
        main.controlar_camara(cam, ord(ch))
    assert cam.ir_a_preset.called
    assert cam.guardar_preset.called


def test_bucle_principal_main():
    cam = _crear_camara_falsa()

    with patch("main.preparar_carpetas"), \
         patch("main.iniciar_camaras", return_value=[cam]), \
         patch("main.notificaciones.iniciar_bot_comandos"), \
         patch("main.notificaciones.detener_bot"), \
         patch("main.WatchdogCamaras") as mock_wd, \
         patch("main.GestorMantenimiento") as mock_mant, \
         patch("main.cv2.namedWindow"), \
         patch("main.cv2.resizeWindow"), \
         patch("main.cv2.setMouseCallback"), \
         patch("main.cv2.imshow"), \
         patch("main.cv2.getWindowProperty", return_value=1.0), \
         patch("main.cv2.waitKeyEx", side_effect=[ord("m"), ord("q")]), \
         patch("main.cv2.destroyAllWindows"):
        mock_mant.return_value.obtener_estado_visual.return_value = "ARMADO"
        main.main()


    assert cam.alternar_deteccion.called
    assert cam.cerrar.called
    assert mock_wd.return_value.cerrar.called
    assert mock_mant.return_value.cerrar.called


def test_preparar_iniciar_y_cerrar_camaras():
    # preparar_carpetas (57-58)
    with patch("main.os.makedirs") as mock_mkdir:
        main.preparar_carpetas()
        assert mock_mkdir.called

    # iniciar_camaras con éxito y con excepción (63-79)
    with patch("main.CONFIG_CAMARAS_RTSP", [{"nombre": "C1"}, {"nombre": "C2"}]), \
         patch("main.CamaraRTSP", side_effect=[MagicMock(), RuntimeError("Fallo RTSP")]), \
         patch("main.CamaraDVRIP", side_effect=RuntimeError("Fallo DVRIP")):
        cams = main.iniciar_camaras()
        assert len(cams) == 1

    # cerrar_camaras con error en una cámara (576-577, 581-582)
    cam_ok = _crear_camara_falsa("Ok")
    cam_err = _crear_camara_falsa("Err")
    cam_err.cerrar.side_effect = RuntimeError("No cierra")
    with patch("main.notificaciones.detener_bot"), \
         patch("main.cv2.destroyAllWindows", side_effect=RuntimeError("GUI")):
        main.cerrar_camaras([cam_ok, cam_err])
    assert cam_ok.cerrar.called


def test_dibujar_interfaz_modos_y_errores():
    cam_err = _crear_camara_falsa("Fallo")
    cam_err.obtener_imagen_ui.side_effect = RuntimeError("Sin frame")

    # Modo 1 cámara (vista_ampliada=True) con excepción en obtener_imagen_ui (90-106)
    main.vista_ampliada = True
    with patch("main.config.MODO_MOSAICO", 4):
        lienzo = main.dibujar_interfaz([cam_err], 0)
        assert lienzo.shape == (main.ALTO_TOTAL_BASE, main.ANCHO_TOTAL_BASE, 3)

    # Modo mosaico 2x2 con error en una cámara (118-120)
    main.vista_ampliada = False
    with patch("main.MODO_MOSAICO", 4), patch("main.config.MODO_MOSAICO", 4):
        lienzo_grid = main.dibujar_interfaz([cam_err], 0)
        assert lienzo_grid.shape == (main.ALTO_TOTAL_BASE, main.ANCHO_TOTAL_BASE, 3)


def test_abrir_configuracion_y_ejecutar_accion_edge_cases():
    # abrir_configuracion_proceso normal y con excepción (473, 476, 481-482)
    main.proceso_config = None
    with patch("main.subprocess.Popen", side_effect=OSError("No python")) as mock_popen:
        main.abrir_configuracion_proceso()
        assert mock_popen.called

    # Sin cámaras y con error dentro de una acción de panel (499, 524-525)
    assert main.ejecutar_accion_panel("foto", []) is True

    cam = _crear_camara_falsa()
    cam.capturar_fotograma_manual.side_effect = RuntimeError("Error foto")
    main.CAMARAS = [cam]
    main.seleccionada = 0
    assert main.ejecutar_accion_panel("foto", [cam]) is True


def test_main_sin_camaras_y_eventos_teclado_raton():
    # main() sale inmediatamente si no hay cámaras (592-593)
    with patch("main.preparar_carpetas"), patch("main.iniciar_camaras", return_value=[]):
        main.main()

    # main() probando ratón en panel y cámaras, Enter, ESC ampliado, flechas y KeyboardInterrupt (612-672)
    cam = _crear_camara_falsa()
    callback_raton = {}

    def capturar_callback(_win, cb, params):
        callback_raton["fn"] = cb
        callback_raton["params"] = params

    teclas = [
        -1,                   # Sin tecla
        13,                   # Enter -> activa vista_ampliada
        27,                   # ESC -> sale de vista_ampliada sin cerrar app
        2555904,  # Flecha derecha -> mover_ptz
    ]

    def simular_waitkey(_ms):
        if teclas:
            return teclas.pop(0)
        # Antes de lanzar KeyboardInterrupt probamos el callback de ratón
        callback_raton["fn"](cv2.EVENT_LBUTTONDOWN, main.ANCHO_TOTAL_BASE + 20, 90, 0, callback_raton["params"])
        callback_raton["fn"](cv2.EVENT_LBUTTONDOWN, 100, 100, 0, callback_raton["params"])
        raise KeyboardInterrupt()

    with patch("main.preparar_carpetas"), \
         patch("main.iniciar_camaras", return_value=[cam]), \
         patch("main.notificaciones.iniciar_bot_comandos"), \
         patch("main.notificaciones.detener_bot"), \
         patch("main.WatchdogCamaras"), \
         patch("main.GestorMantenimiento") as mock_mant, \
         patch("main.cv2.namedWindow"), \
         patch("main.cv2.resizeWindow"), \
         patch("main.cv2.setMouseCallback", side_effect=capturar_callback), \
         patch("main.cv2.imshow"), \
         patch("main.cv2.getWindowProperty", return_value=1.0), \
         patch("main.cv2.waitKeyEx", side_effect=simular_waitkey), \
         patch("main.cv2.destroyAllWindows"):
        mock_mant.return_value.obtener_estado_visual.return_value = None
        main.main()

    assert cam.mover_ptz.called
    assert cam.cerrar.called

def test_main_ramas_residuales_99_por_ciento():
    # 1. Icono zoom_menos (291-292)
    panel = np.zeros((100, 100, 3), dtype=np.uint8)
    main.dibujar_icono(panel, "zoom_menos", 50, 50, False)

    # 2. abrir_configuracion_proceso ya abierto (473) y en modo congelado .exe (476)
    proc_activo = MagicMock()
    proc_activo.poll.return_value = None
    main.proceso_config = proc_activo
    main.abrir_configuracion_proceso()  # Retorna sin lanzar otro proceso

    main.proceso_config = None
    with patch.object(main.sys, "frozen", True, create=True), \
         patch("main.subprocess.Popen") as mock_popen:
        main.abrir_configuracion_proceso()
        mock_popen.assert_called_once_with([main.sys.executable, "--config"])

    # 3. Doble clic en modo mosaico=1 (535) y clic fuera de botones en panel (560)
    main.vista_ampliada = False
    with patch("main.config.MODO_MOSAICO", 1):
        main.al_hacer_clic_camaras(cv2.EVENT_LBUTTONDBLCLK, 50, 50, [_crear_camara_falsa()])
    main.al_hacer_clic_panel(cv2.EVENT_LBUTTONDOWN, 5, 5, [])

    # 4. Pantalla completa en Linux (612-616) y cierre por botón X de la ventana (647-649)
    cam = _crear_camara_falsa()
    with patch("main.sys.platform", "linux"), \
         patch("main.preparar_carpetas"), \
         patch("main.iniciar_camaras", return_value=[cam]), \
         patch("main.notificaciones.iniciar_bot_comandos"), \
         patch("main.notificaciones.detener_bot"), \
         patch("main.WatchdogCamaras"), \
         patch("main.GestorMantenimiento") as mock_mant, \
         patch("main.cv2.namedWindow"), \
         patch("main.cv2.resizeWindow"), \
         patch("main.cv2.setWindowProperty") as mock_prop, \
         patch("main.cv2.setMouseCallback"), \
         patch("main.cv2.imshow"), \
         patch("main.cv2.waitKeyEx", return_value=-1), \
         patch("main.cv2.getWindowProperty", return_value=0.0), \
         patch("main.cv2.destroyAllWindows"):
        mock_mant.return_value.obtener_estado_visual.return_value = None
        main.main()
        assert mock_prop.called
