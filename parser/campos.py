# =============================================================================
# campos.py — Campos estruturados dos formatos com parser DEDICADO
# =============================================================================
#
# P2500S / PCM_TESTER / CYG: as regras são as mesmas do cliente v1.0.5
# (antes ficavam dentro de monitor/file_monitor.py). Mudança só no tipo da
# data: agora sai como TEXTO 'YYYY-MM-DD HH:MM:SS' (hora local da planta),
# porque o lote também vai para a fila offline em JSON — datetime não é
# serializável e derrubava o push_many — e o banco converte com o fuso da
# planta no INSERT (test_start_time é TIMESTAMPTZ).
# =============================================================================

import hashlib
from datetime import datetime

from config.column_mapper import resolve_field
from parser.configuravel import iso_flexivel
from logs.logger_setup import get_logger

logger = get_logger()

# Comparação por VALOR EXATO (PENDING/TESTING/WRONG não viram FAIL)
RESULTADO_PASS = {"PASS", "PASSED", "OK", "P", "1", "TRUE", "GOOD"}
RESULTADO_FAIL = {"FAIL", "FAILED", "NG", "F", "0", "FALSE", "BAD"}


def schema_hash(headers):
    """MD5 da lista de colunas: identifica a estrutura do arquivo."""
    return hashlib.md5("|".join(headers).encode("utf-8")).hexdigest()


def _normalize_result(value):
    if not value:
        return None
    v = str(value).strip().upper()
    if v in RESULTADO_PASS:
        return "PASS"
    if v in RESULTADO_FAIL:
        return "FAIL"
    return v


def _parse_test_time(raw, context=""):
    """Texto do equipamento → datetime (sem fuso) ou None. Nunca adivinha."""
    if not raw:
        return None
    raw = str(raw).strip()
    try:
        return datetime.strptime(raw, "%Y%m%d%H%M%S")
    except ValueError:
        pass
    dt = iso_flexivel(raw)          # inclui Z, fração curta e ISO compacto (Python 3.8)
    if dt is not None:
        return dt
    logger.warning("Formato de data/hora nao reconhecido"
                   + (" (%s)" % context if context else "")
                   + ": %r — gravado como NULL" % raw)
    return None


def data_texto(dt):
    """datetime → 'YYYY-MM-DD HH:MM:SS[.ffffff]' (o que vai para o banco/fila)."""
    if dt is None:
        return None
    return dt.replace(tzinfo=None).isoformat(sep=" ")


def _pcm_serial(row):
    """PCM_TESTER não tem serial único: machine|CH{canal}|device|tempo."""
    machine = row.get("machine_no") or ""
    channel = row.get("channel_no") or ""
    carrier = row.get("device_name") or row.get("barcode") or ""
    test_time = row.get("test_time") or ""
    return "%s|CH%s|%s|%s" % (machine, channel, carrier, test_time)


def _resolve_model_name(file_model, fallback_model, rows, mappings):
    """1º modelo no nome do arquivo, 2º coluna da linha, 3º modelo atual da estação."""
    if file_model:
        return file_model
    if rows:
        val = resolve_field("model_name", rows[0], "DEFAULT", mappings)
        if val:
            return val
    return fallback_model or "UNKNOWN_MODEL"


def _resolve_version_name(file_version, rows):
    if file_version:
        return file_version
    if rows:
        for key in ("bmu_MIX_FW_Version", "SC_ROM", "Version", "version"):
            value = rows[0].get(key)
            if value:
                return str(value).strip()
    return "UNKNOWN_VERSION"
