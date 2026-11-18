"""Módulo de registro estructurado con rotación automática en disco."""
from logging.handlers import RotatingFileHandler
import logging
import os
import sys

from config import DIR_DATOS

RUTA_LOG = os.path.join(DIR_DATOS, "sistema.log")


class _RedireccionadorPrint:
    """Redirige sys.stdout/stderr hacia el logger manteniendo la salida en consola."""

    def __init__(self, logger, nivel, stream_original):
        self.logger = logger
        self.nivel = nivel
        self.stream_original = stream_original

    def write(self, mensaje):
        if self.stream_original:
            try:
                self.stream_original.write(mensaje)
            except OSError:
                pass
        texto = mensaje.strip()
        if texto:
            self.logger.log(self.nivel, texto)

    def flush(self):
        if self.stream_original:
            try:
                self.stream_original.flush()
            except OSError:
                pass



def configurar_logs():
    """Inicializa el archivo rotativo sistema.log y captura todos los print()."""
    os.makedirs(DIR_DATOS, exist_ok=True)

    logger = logging.getLogger("StiViHome")
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        handler = RotatingFileHandler(
            RUTA_LOG, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        formato = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formato)
        logger.addHandler(handler)

    sys.stdout = _RedireccionadorPrint(logger, logging.INFO, sys.__stdout__)
    sys.stderr = _RedireccionadorPrint(logger, logging.ERROR, sys.__stderr__)
