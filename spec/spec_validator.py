# =============================================================================
# spec_validator.py — Validação dos limites do testador contra spec_limits.csv
# =============================================================================
#
# Compara os limites que o testador usa (lidos do CSV de resultado) com os
# limites oficiais da engenharia (spec_limits.csv).
#
# Se houver divergência (LSL ou USL diferente), registra em mes_spec_mismatches.
# Isso permite auditoria: "o testador estava usando os limites corretos?"
#
# spec_limits.csv formato:
#   enabled, model, step_key, step_name, unit, lsl, usl
#   1,       A06,   V_PACK,   Pack Volt, V,    3.75, 3.85
# =============================================================================

import csv
import os
from config.loader import get_base_path


def _to_float(value):
    """Converte valor para float. Retorna None se vazio ou inválido."""
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(str(value).strip())
    except Exception:
        return None


def load_spec_limits(spec_file_name):
    """Lê spec_limits.csv e retorna lista de specs habilitadas.
    Ignora linhas com enabled=0 ou false."""
    spec_path = os.path.join(get_base_path(), spec_file_name)

    if not os.path.exists(spec_path):
        return []

    specs = []

    # utf-8-sig: lida com BOM do Excel (﻿ no início do arquivo)
    with open(spec_path, "r", encoding="utf-8-sig", errors="ignore", newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            enabled = str(row.get("enabled", "1")).strip()

            # Aceita "1", "true", "TRUE", "yes", "YES" como habilitado
            if enabled not in ("1", "true", "TRUE", "yes", "YES"):
                continue

            specs.append({
                "model":     str(row.get("model", "")).strip(),
                "step_key":  str(row.get("step_key", "")).strip(),
                "step_name": str(row.get("step_name", "")).strip(),
                "unit":      str(row.get("unit", "")).strip(),
                "lsl":       _to_float(row.get("lsl")),
                "usl":       _to_float(row.get("usl")),
            })

    return specs


def validate_schema_limits(model_name, schema, spec_file_name):
    """Compara limites detectados no CSV do testador com a spec oficial.

    schema: dicionário retornado pelo parser com:
        headers, upper_map, lower_map, unit_map, display_map

    Retorna lista de divergências (vazia se tudo ok).
    """
    specs = load_spec_limits(spec_file_name)

    if not specs:
        return []

    mismatches = []

    upper_map   = schema.get("upper_map", {})
    lower_map   = schema.get("lower_map", {})
    unit_map    = schema.get("unit_map", {})
    display_map = schema.get("display_map", {})

    for spec in specs:
        spec_model = spec["model"]
        step_key   = spec["step_key"]

        # Filtra por modelo — se spec tem modelo, só valida para esse modelo
        if spec_model and model_name and spec_model.upper() != model_name.upper():
            continue

        # Limites que o testador estava usando (vindos do CSV de resultado)
        tester_lsl  = _to_float(lower_map.get(step_key))
        tester_usl  = _to_float(upper_map.get(step_key))
        tester_unit = str(unit_map.get(step_key, "")).strip()

        # Limites oficiais (spec_limits.csv)
        expected_lsl = spec["lsl"]
        expected_usl = spec["usl"]

        mismatch_reasons = []

        # Compara com tolerância de 0.000001 para evitar falsos positivos de ponto flutuante
        if expected_lsl is not None and tester_lsl is not None:
            if abs(expected_lsl - tester_lsl) > 0.000001:
                mismatch_reasons.append("LSL diferente")

        if expected_usl is not None and tester_usl is not None:
            if abs(expected_usl - tester_usl) > 0.000001:
                mismatch_reasons.append("USL diferente")

        # Limite esperado existe mas o testador não reportou — pode ser teste ausente
        if expected_lsl is not None and tester_lsl is None:
            mismatch_reasons.append("LSL não encontrado no log")

        if expected_usl is not None and tester_usl is None:
            mismatch_reasons.append("USL não encontrado no log")

        if mismatch_reasons:
            mismatches.append({
                "model_name":   model_name,
                "step_key":     step_key,
                "step_name":    spec["step_name"] or display_map.get(step_key, ""),
                "unit":         spec["unit"] or tester_unit,
                "expected_lsl": expected_lsl,
                "expected_usl": expected_usl,
                "tester_lsl":   tester_lsl,
                "tester_usl":   tester_usl,
                "reason":       "; ".join(mismatch_reasons)
            })

    return mismatches
