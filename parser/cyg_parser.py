# =============================================================================
# cyg_parser.py — Parser universal de arquivos CSV (CYG e PCM Tester)
# =============================================================================
#
# Suporta dois formatos de CSV gerados pelos testadores:
#
# CYG (bateria):
#   Linha 1: cabeçalho (nomes das colunas)
#   Linha 2: limites superiores (USL)
#   Linha 3: limites inferiores (LSL)
#   Linha 4: unidades
#   Linhas 5+: dados de teste
#
# PCM_TESTER:
#   Linha 1: chaves técnicas (nomes das colunas)
#   Linha 2: descrição + limites embutidos no texto: "Tensão(V)[3.75-3.85]"
#   Linhas 3+: dados de teste
#
# parse_appended_rows() lê SOMENTE linhas novas desde a última leitura,
# usando o offset em bytes para posicionar o cursor (f.seek).
# =============================================================================

import os
import io
import csv
import re


def _parse_csv_line(line_text):
    """Parseia uma linha CSV usando o módulo csv do Python (lida com aspas, vírgulas etc.)."""
    return next(csv.reader([line_text]))


def _safe_strip(value):
    """Remove espaços. Retorna None se valor for None."""
    if value is None:
        return None
    return str(value).strip()


def _parse_limit_from_step(step_text):
    """Extrai limites e unidade embutidos no texto de passo do PCM Tester.

    Exemplo de entrada:
        "PACK Voltage(V)[3.75-3.85]"

    Retorna:
        display_name="PACK Voltage", unit="V", lower="3.75", upper="3.85"
    """
    if not step_text:
        return "", None, None, None

    text  = str(step_text).strip()
    unit  = None
    lower = None
    upper = None

    # Extrai unidade entre parênteses: (V), (A), (mΩ) etc.
    unit_match = re.search(r"\((.*?)\)", text)
    if unit_match:
        unit = unit_match.group(1).strip()

    # Extrai limites entre colchetes: [3.75-3.85] ou [-0.5-0.5]
    limit_match = re.search(r"\[([\-0-9.]+)\s*-\s*([\-0-9.]+)\]", text)
    if limit_match:
        lower = limit_match.group(1).strip()
        upper = limit_match.group(2).strip()

    # Nome amigável: remove partes entre () e []
    display_name = re.sub(r"\(.*?\)", "", text)
    display_name = re.sub(r"\[.*?\]", "", display_name).strip()

    return display_name, unit, lower, upper


# -----------------------------------------------------------------------------
# DETECÇÃO DE FORMATO
# -----------------------------------------------------------------------------

def detect_model_from_filename(file_path):
    """Tenta extrair modelo e versão do nome do arquivo.
    CYG normalmente inclui o modelo (ex: CYG_X30_20260622.csv).
    PCM geralmente não inclui — usa coluna 'Model' ou config.yaml."""
    filename = os.path.basename(file_path)

    model_match   = re.search(r"_(X\d+)", filename, re.IGNORECASE)
    version_match = re.search(r"_(X\d+[-\w]+)_\d{8}\.csv$", filename, re.IGNORECASE)

    model_name   = model_match.group(1).upper()   if model_match   else ""
    version_name = version_match.group(1).upper() if version_match else ""

    return model_name, version_name


def detect_csv_format(second_line_values, station_type="AUTO"):
    """Determina o formato do CSV.
    Se station.type está definido no config.yaml, respeita (não detecta).
    AUTO: detecta pelo padrão [lsl-usl] na segunda linha."""
    if station_type and station_type.upper() == "PCM_TESTER":
        return "PCM_TESTER"

    if station_type and station_type.upper() == "CYG":
        return "CYG"

    if station_type and station_type.upper() == "FT":
        return "FT"

    # Heurística: segunda linha de PCM contém padrão [número-número]
    joined = "|".join(second_line_values)

    if re.search(r"\[[\-0-9.]+\s*-\s*[\-0-9.]+\]", joined):
        return "PCM_TESTER"

    return "CYG"


# -----------------------------------------------------------------------------
# LEITURA DO CABEÇALHO E METADADOS
# -----------------------------------------------------------------------------

def read_header_and_meta(file_path, station_type="AUTO"):
    """Lê cabeçalho, limites e unidades do arquivo CSV.
    Retorna dicionário com format, headers, upper_map, lower_map, unit_map,
    display_map e data_start_offset (posição em bytes onde os dados começam)."""
    with open(file_path, "r", encoding="utf-8-sig", errors="ignore", newline="") as f:
        header_line = f.readline()
        second_line = f.readline()

        if not header_line:
            raise ValueError(f"Arquivo vazio: {file_path}")

        headers       = _parse_csv_line(header_line.rstrip("\n"))
        second_values = _parse_csv_line(second_line.rstrip("\n")) if second_line else []

        csv_format = detect_csv_format(second_values, station_type)

        upper_map   = {}
        lower_map   = {}
        unit_map    = {}
        display_map = {}

        if csv_format == "PCM_TESTER":
            # PCM: limites embutidos na segunda linha — dados começam na linha 3
            data_start_offset = f.tell()

            for i, col in enumerate(headers):
                step_text = second_values[i] if i < len(second_values) else ""
                display_name, unit, lower, upper = _parse_limit_from_step(step_text)

                display_map[col] = display_name or col
                unit_map[col]    = unit
                lower_map[col]   = lower
                upper_map[col]   = upper

        else:
            # CYG: linhas 2=upper, 3=lower, 4=units — dados começam na linha 5
            lower_line = f.readline()
            units_line = f.readline()
            data_start_offset = f.tell()

            upper_values = second_values
            lower_values = _parse_csv_line(lower_line.rstrip("\n")) if lower_line else []
            unit_values  = _parse_csv_line(units_line.rstrip("\n")) if units_line else []

            for i, col in enumerate(headers):
                upper_map[col]   = upper_values[i] if i < len(upper_values) else None
                lower_map[col]   = lower_values[i] if i < len(lower_values) else None
                unit_map[col]    = unit_values[i]  if i < len(unit_values)  else None
                display_map[col] = col

    return {
        "format":            csv_format,
        "headers":           headers,
        "upper_map":         upper_map,
        "lower_map":         lower_map,
        "unit_map":          unit_map,
        "display_map":       display_map,
        "data_start_offset": data_start_offset   # bytes — usado no f.seek()
    }


# -----------------------------------------------------------------------------
# LEITURA INCREMENTAL
# -----------------------------------------------------------------------------

def parse_appended_rows(file_path, last_state, station_type="AUTO"):
    """Lê somente as linhas novas desde a última leitura.

    last_state: dict com offset, line_no, file_size (vem do OffsetManager)

    Estratégia de offset:
    - f.seek(offset) posiciona o cursor em bytes — lê apenas o que é novo
    - Se o arquivo encolheu (file_size diminuiu), reinicia do início
      (o testador pode ter rotacionado/criado um novo arquivo)
    - Só conta linhas completas (terminadas em \\n) — ignora linha parcial
      que o testador ainda está escrevendo

    Retorna dict com rows, new_offset, new_line_no, file_size, schema.
    """
    meta    = read_header_and_meta(file_path, station_type)
    headers = meta["headers"]

    file_size = os.path.getsize(file_path)

    # Arquivo encolheu = rotacionado → reinicia leitura desde o início dos dados
    if file_size < last_state["file_size"]:
        current_offset  = meta["data_start_offset"]
        current_line_no = 0
    else:
        current_offset  = last_state["offset"] or meta["data_start_offset"]
        current_line_no = last_state["line_no"]

        # Garante que nunca começa antes do cabeçalho
        if current_offset < meta["data_start_offset"]:
            current_offset = meta["data_start_offset"]

    complete_lines = []
    new_offset     = current_offset

    with open(file_path, "r", encoding="utf-8-sig", errors="ignore", newline="") as f:
        f.seek(current_offset)

        while True:
            line = f.readline()

            if not line:
                break   # fim do arquivo

            if not line.endswith("\n"):
                break   # linha incompleta (testador ainda escrevendo) — para aqui

            complete_lines.append(line)
            new_offset = f.tell()   # posição APÓS esta linha — próximo ponto de início

    if not complete_lines:
        return {
            "rows":        [],
            "new_offset":  current_offset,
            "new_line_no": current_line_no,
            "file_size":   file_size,
            "schema":      meta
        }

    # csv.DictReader com io.StringIO: parseia linhas em memória sem abrir arquivo novamente
    reader = csv.DictReader(
        io.StringIO("".join(complete_lines)),
        fieldnames=headers
    )

    rows = []

    for row in reader:
        current_line_no += 1

        # Limpa espaços em todas as chaves e valores
        cleaned = {_safe_strip(k): _safe_strip(v) for k, v in row.items()}
        cleaned["_line_no"] = current_line_no   # número de linha para source_line_no no banco
        rows.append(cleaned)

    return {
        "rows":        rows,
        "new_offset":  new_offset,
        "new_line_no": current_line_no,
        "file_size":   file_size,
        "schema":      meta
    }
