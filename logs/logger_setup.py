# =============================================================================
# logger_setup.py — Configuração central de log do MES Client
# =============================================================================
#
# get_logger() devolve sempre o MESMO logger ("MES_CLIENT"), configurado uma
# única vez. Todos os módulos chamam esta função — não criam handlers próprios.
#
# Saídas:
#   logs/client.log  — arquivo rotativo (2 MB por arquivo, 5 backups)
#   console          — útil ao rodar pelo VSCode; inofensivo no .exe sem console
#
# NOTA DE EMPACOTAMENTO: 'logs' é um PACOTE Python, não só a pasta de saída.
# O .gitignore deve ignorar 'logs/*.log', NUNCA 'logs/' inteiro — senão este
# módulo some do repositório e o clone quebra com ModuleNotFoundError.
# =============================================================================

import os
import logging
from logging.handlers import RotatingFileHandler

from config.loader import get_base_path


def get_logger():
    logger = logging.getLogger("MES_CLIENT")

    # Já configurado por uma chamada anterior — devolve como está.
    # Sem esta guarda, cada import adicionaria handlers duplicados e cada
    # linha de log apareceria N vezes.
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    log_dir = os.path.join(get_base_path(), "logs")
    os.makedirs(log_dir, exist_ok=True)

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    file_handler = RotatingFileHandler(
        os.path.join(log_dir, "client.log"),
        maxBytes=2 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger
