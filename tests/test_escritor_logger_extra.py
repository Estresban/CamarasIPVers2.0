from unittest.mock import MagicMock, patch
import numpy as np
from escritor_video import EscritorVideoH264
from logger import _RedireccionadorPrint


def test_escritor_video_errores_pipe_y_cierre():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)

    # 1. Fallo en os.pipe() al pedir con_audio=True -> continúa sin audio (46-47)
    with patch("escritor_video.os.pipe", side_effect=OSError("Sin descriptores")), \
         patch("escritor_video.subprocess.Popen") as mock_popen:
        mock_proc = MagicMock()
        mock_popen.return_value = mock_proc
        escritor = EscritorVideoH264("salida.mp4", 25, 100, 100, con_audio=True)
        assert escritor.pipe_audio_w is None

        # 2. BrokenPipeError / OSError al escribir frame en stdin (78-79)
        mock_proc.stdin.write.side_effect = BrokenPipeError("Pipe roto")
        escritor.write(frame)

        # 3. OSError al cerrar stdin y Timeout en wait() -> llama a kill() (115-119)
        mock_proc.stdin.close.side_effect = OSError("Error cerrando stdin")
        mock_proc.wait.side_effect = RuntimeError("Timeout FFmpeg")
        escritor.release()
        assert mock_proc.kill.called

    # 4. Errores en os.write y os.close de pipe_audio_w (85-86, 93, 106-107)
    with patch("escritor_video.os.pipe", return_value=(10, 11)), \
         patch("escritor_video.os.set_inheritable"), \
         patch("escritor_video.os.close", side_effect=OSError("Descriptor inválido")), \
         patch("escritor_video.os.write", side_effect=OSError("Fallo escritura audio")), \
         patch("escritor_video.subprocess.Popen", return_value=MagicMock()):
        escritor_aud = EscritorVideoH264("audio.mp4", 25, 100, 100, con_audio=True)
        escritor_aud.write_audio(b"\x00\x01")
        escritor_aud.release()
        assert escritor_aud.pipe_audio_w is None


def test_logger_redireccionador_flush_y_oserror():
    mock_logger = MagicMock()
    stream_ok = MagicMock()

    redir = _RedireccionadorPrint(mock_logger, 20, stream_ok)
    redir.write("   \n")  # Mensaje vacío/espacios: escribe en stream pero no loguea
    assert not mock_logger.log.called

    redir.flush()
    assert stream_ok.flush.called

    # Simulamos OSError en write() y flush() (líneas 23-24 y 34-35)
    stream_ok.write.side_effect = OSError("Consola cerrada")
    stream_ok.flush.side_effect = OSError("Consola cerrada")
    redir.write("Mensaje importante\n")
    redir.flush()
    mock_logger.log.assert_called_once_with(20, "Mensaje importante")
