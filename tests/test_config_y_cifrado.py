import json
import numpy as np
import pytest
import config


def test_cifrado_y_descifrado_secreto():
    secreto = "MiClaveSuperSecreta_2026!@#"
    cifrado = config.cifrar_secreto(secreto)

    assert cifrado.startswith("ENC:")
    assert secreto not in cifrado
    assert config.descifrar_secreto(cifrado) == secreto


def test_cifrado_ignora_placeholders_y_ya_cifrados():
    assert config.cifrar_secreto("") == ""
    assert config.cifrar_secreto("TU_PASSWORD") == "TU_PASSWORD"
    assert config.cifrar_secreto("TU_TOKEN_TELEGRAM") == "TU_TOKEN_TELEGRAM"

    ya_cifrado = config.cifrar_secreto("clave123")
    assert config.cifrar_secreto(ya_cifrado) == ya_cifrado


def test_integridad_hmac_detecta_manipulacion():
    cifrado = config.cifrar_secreto("password_intacta")
    # Alteramos el último carácter de la firma/carga cifrada
    corrupto = cifrado[:-1] + ("A" if cifrado[-1] != "A" else "B")
    assert config.descifrar_secreto(corrupto) == ""


def test_codec_audio_alaw_ida_y_vuelta():
    # Generamos una onda PCM int16 de prueba
    muestras_orig = np.array([-16000, -4000, -500, 0, 500, 4000, 16000], dtype=np.int16)
    alaw_bytes = config.pcm16_a_alaw(muestras_orig)
    assert isinstance(alaw_bytes, bytes)
    assert len(alaw_bytes) == len(muestras_orig)

    reconstruido = config.alaw_a_pcm(alaw_bytes)
    assert reconstruido.dtype == np.int16
    # G.711 A-Law es un códec logarítmico con pérdida leve; comprobamos tolerancia razonable
    assert np.allclose(muestras_orig, reconstruido, rtol=0.1, atol=50)


def test_recarga_configuracion_en_caliente(tmp_path, monkeypatch):
    archivo_json = tmp_path / "config_test.json"
    datos = {
        "telegram_token": config.cifrar_secreto("123456:ABC-TOKEN"),
        "telegram_chat_id": "987654321",
        "parametros": {
            "sensibilidad_movimiento": 2500,
            "minutos_por_bloque_video": 15,
            "modo_mosaico": 2,
        },
    }
    archivo_json.write_text(json.dumps(datos), encoding="utf-8")

    monkeypatch.setattr(config, "RUTA_CONFIG_JSON", str(archivo_json))
    assert config.recargar_configuracion() is True
    assert config.TELEGRAM_TOKEN == "123456:ABC-TOKEN"
    assert config.TELEGRAM_CHAT_ID == "987654321"
    assert config.SENSIBILIDAD_MOVIMIENTO == 2500
    assert config.MINUTOS_POR_BLOQUE_VIDEO == 15
    assert config.MODO_MOSAICO == 2
