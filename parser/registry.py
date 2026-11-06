# =============================================================================
# registry.py — Escolhe o parser de cada fonte de log pelo formato do cadastro
# =============================================================================
#
# mes_formatos.tipo:
#   DEDICADO     → código no cliente (DEDICADOS abaixo). Um formato dedicado que
#                  esta versão não conhece é recusado com aviso claro.
#   CONFIGURAVEL → parser/configuravel.py, guiado pela "definicao" JSONB.
#
# "fonte" é a linha da view v_cadastro_fontes (guardada no cache local):
# fonte_id, formato_codigo, formato_tipo, definicao, modelo_atual, fuso...
# =============================================================================

from config.column_mapper import resolve_field
from parser import configuravel
from parser.campos import (_normalize_result, _parse_test_time, _pcm_serial,
                           _resolve_model_name, _resolve_version_name, data_texto)
from parser.cyg_parser import detect_model_from_filename, parse_appended_rows

# codigo do formato no cadastro → station_type do cyg_parser
DEDICADOS = {
    "P2500S":     "P2500S",
    "PCM_TESTER": "PCM_TESTER",
    "CYG":        "CYG",
}


def formato_suportado(fonte):
    """(True, "") se esta versão do cliente sabe ler o formato da fonte;
    senão (False, motivo)."""
    tipo = (fonte.get("formato_tipo") or "").upper()
    codigo = fonte.get("formato_codigo") or ""
    if tipo == "DEDICADO":
        if codigo in DEDICADOS:
            return True, ""
        return False, "formato dedicado %s não existe nesta versão do cliente" % codigo
    if tipo == "CONFIGURAVEL":
        erros = configuravel.validar_definicao(fonte.get("definicao") or {})
        if erros:
            return False, "definição do formato %s inválida: %s" % (codigo, "; ".join(erros))
        return True, ""
    return False, "tipo de formato desconhecido: %r" % tipo


def ler(fonte, caminho, estado):
    """Lê as linhas novas do arquivo (mesmo contrato do cyg_parser)."""
    if (fonte.get("formato_tipo") or "").upper() == "DEDICADO":
        return parse_appended_rows(caminho, estado, station_type=DEDICADOS[fonte["formato_codigo"]])
    return configuravel.parse_appended_rows(caminho, estado, fonte.get("definicao") or {})


def montar_lote(fonte, parsed, caminho, source_key, schema_hash, mappings):
    """Linhas parseadas → (lote para o INSERT, modelo, versão).

    Cada item do lote é autossuficiente (vai para a fila offline em JSON):
    fonte_id e fuso viajam junto."""
    rows = parsed["rows"]
    modelo_atual = fonte.get("modelo_atual") or ""
    base = {
        "fonte_id":    fonte["fonte_id"],
        "fuso":        fonte.get("fuso") or "UTC",
        "source_file": source_key,
        "schema_hash": schema_hash,
        "anexo_path":  None,         # cópia de imagens (AOI) entra na F8
    }
    lote = []

    if (fonte.get("formato_tipo") or "").upper() == "DEDICADO":
        # Mesmas regras do cliente v1.0.5 (paridade testada nos CSVs da M13)
        file_model, file_version = detect_model_from_filename(caminho)
        modelo = _resolve_model_name(file_model, modelo_atual, rows, mappings)
        versao = _resolve_version_name(file_version, rows)
        pcm = fonte["formato_codigo"] == "PCM_TESTER"
        nome = source_key
        for row in rows:
            item = dict(base)
            item.update({
                "model_name":      modelo,
                "version_name":    versao,
                "serial_number":   _pcm_serial(row) if pcm
                                   else resolve_field("serial_number", row, modelo, mappings),
                "result_status":   _normalize_result(resolve_field("result_status", row, modelo, mappings)),
                "defeito":         None,
                "test_start_time": data_texto(_parse_test_time(
                                       resolve_field("test_start_time", row, modelo, mappings), nome)),
                "test_stop_time":  data_texto(_parse_test_time(
                                       resolve_field("test_stop_time", row, modelo, mappings), nome)),
                "source_line_no":  row["_line_no"],
                "row_data":        row,
            })
            lote.append(item)
        return lote, modelo, versao

    definicao = fonte.get("definicao") or {}
    versao = _resolve_version_name("", rows)
    modelo_lote = None
    for row in rows:
        c = configuravel.extrair_campos(row, definicao)
        modelo = c["model_name"] or modelo_atual or "UNKNOWN_MODEL"
        modelo_lote = modelo_lote or modelo
        item = dict(base)
        item.update({
            "model_name":      modelo,
            "version_name":    versao,
            "serial_number":   c["serial_number"],
            "result_status":   c["result_status"],
            "defeito":         c["defeito"],
            "test_start_time": c["test_start_time"],
            "test_stop_time":  c["test_stop_time"],
            "source_line_no":  row["_line_no"],
            "row_data":        row,
        })
        lote.append(item)
    return lote, modelo_lote or modelo_atual or "UNKNOWN_MODEL", versao
