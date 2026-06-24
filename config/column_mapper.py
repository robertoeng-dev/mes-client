# =============================================================================
# column_mapper.py — Mapeamento configurável de colunas CSV para campos MES
# =============================================================================
#
# Problema resolvido:
#   Os nomes das colunas de cada CSV variam por modelo, linha e fabricante do
#   equipamento de teste. Este módulo elimina o hardcode dessas correspondências
#   movendo-as para column_mappings.json — editável pela tela MAPEAMENTO da UI.
#
# Prioridade de resolução para cada campo:
#   1. Mapeamento específico do modelo (ex: "A17")
#   2. Mapeamento "DEFAULT"
#   3. None → coluna inserida como NULL no banco (dado completo em row_data JSONB)
#
# Nota sobre PCM_TESTER:
#   O serial do PCM Tester é uma chave COMPOSTA (machine|channel|device|tempo)
#   gerada em file_monitor.py. Os outros campos (result, tempo) usam este módulo.
# =============================================================================

import os
import json

from logs.logger_setup import get_logger

logger = get_logger()

MAPPINGS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "column_mappings.json"
)

# Campos estruturados que podem ser mapeados.
# Chave = nome interno no banco | Valor = rótulo exibido na tela MAPEAMENTO.
STRUCTURED_FIELDS = {
    "serial_number":   "Serial / Rastreio",
    "result_status":   "Resultado (PASS/FAIL)",
    "model_name":      "Nome do Modelo",
    "test_start_time": "Tempo de Início",
    "test_stop_time":  "Tempo de Fim",
}

# Valores padrão — usados quando column_mappings.json não existe ou está inválido.
DEFAULT_MAPPINGS: dict = {
    "DEFAULT": {
        "serial_number":   ["SerialNumber", "serial_number", "barcode", "device_name"],
        "result_status":   ["test_result", "Test PASS/FAIL STATUS", "Result"],
        "model_name":      ["Model", "model", "proj_code"],
        "test_start_time": ["test_time", "Test Start Time"],
        "test_stop_time":  ["Test Stop Time", "stop_time"],
    }
}


def load_mappings() -> dict:
    """Carrega column_mappings.json do disco.
    Garante que DEFAULT existe. Usa DEFAULT_MAPPINGS se arquivo ausente ou inválido."""
    if not os.path.exists(MAPPINGS_FILE):
        return {k: dict(v) for k, v in DEFAULT_MAPPINGS.items()}
    try:
        with open(MAPPINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("JSON raiz deve ser um objeto")
        if "DEFAULT" not in data:
            data["DEFAULT"] = dict(DEFAULT_MAPPINGS["DEFAULT"])
        return data
    except Exception as e:
        logger.warning(f"Erro ao carregar column_mappings.json — usando defaults: {e}")
        return {k: dict(v) for k, v in DEFAULT_MAPPINGS.items()}


def save_mappings(mappings: dict) -> None:
    """Persiste dicionário de mapeamentos em column_mappings.json."""
    with open(MAPPINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(mappings, f, ensure_ascii=False, indent=2)
    logger.info("column_mappings.json atualizado.")


def resolve_field(field: str, row: dict, model_name: str, mappings: dict):
    """Extrai um campo estruturado da linha CSV usando a lista de colunas configurada.

    Retorna string com o valor encontrado, ou None se nenhuma coluna bater.
    """
    col_names = (
        mappings.get(model_name, {}).get(field)
        or mappings.get("DEFAULT", {}).get(field, [])
    )
    if isinstance(col_names, str):
        col_names = [col_names]

    for col in (col_names or []):
        val = row.get(col)
        if val is not None and str(val).strip():
            return str(val).strip()
    return None


def detect_unmapped_fields(row: dict, model_name: str, mappings: dict) -> list:
    """Retorna campos que não puderam ser resolvidos para este modelo.

    Usado para preparar a detecção de schemas não mapeados (Opção C — futura).
    Exclui model_name porque ele tem fallbacks alternativos (nome do arquivo, config.yaml).
    """
    unmapped = []
    for field in ("serial_number", "result_status", "test_start_time"):
        if resolve_field(field, row, model_name, mappings) is None:
            unmapped.append(STRUCTURED_FIELDS.get(field, field))
    return unmapped
