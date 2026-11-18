from unittest.mock import MagicMock
import notificaciones


def _crear_camara_falsa(nombre):
    cam = MagicMock()
    cam.nombre = nombre
    cam.grabando = False
    cam.deteccion_activa = False
    cam.modo_luz_actual = "Auto"
    cam.zoom_digital = 1.0
    cam.frame = None
    cam.grabador_eventos = MagicMock(activa=False)
    return cam


def test_comandos_telegram_ptz_y_presets(monkeypatch):
    mensajes_enviados = []
    monkeypatch.setattr(
        notificaciones,
        "enviar_mensaje_telegram",
        lambda texto, incluir_teclado=True: mensajes_enviados.append(texto),
    )

    cam1 = _crear_camara_falsa("Entrada")
    cam2 = _crear_camara_falsa("Jardin")
    camaras = [cam1, cam2]

    # Seleccionar cámara 2 usando el texto del botón táctil
    notificaciones._procesar_comando("📹 Cám 2", camaras)
    assert notificaciones.camara_telegram_idx == 1

    # Mover PTZ hacia arriba debe afectar a cam2
    notificaciones._procesar_comando("⬆️ Arriba", camaras)
    cam2.mover_ptz.assert_called_once_with(0.0, 0.5, 0.0)
    cam1.mover_ptz.assert_not_called()

    # Guardar preset 1 en cam2
    notificaciones._procesar_comando("/setpreset1", camaras)
    cam2.guardar_preset.assert_called_once_with(1)


def test_guardar_historial_movimiento(tmp_path, monkeypatch):
    archivo_hist = tmp_path / "historial.txt"
    monkeypatch.setattr(notificaciones, "ARCHIVO_HISTORIAL", str(archivo_hist))
    monkeypatch.setattr(notificaciones, "alertas_activas", False)  # Evita enviar HTTP real

    notificaciones.enviar_alerta_movimiento(None, "Garaje")

    contenido = archivo_hist.read_text(encoding="utf-8")
    assert "Garaje" in contenido
