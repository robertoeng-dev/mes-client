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
# P2500S (BW P2500S, linha Caiapó / modelo A08):
#   Linha 1: 6 colunas fixas, depois triplas (Max, Min, MEDIÇÃO) e 'Station'
#   Linhas 2+: dados de teste — cada linha carrega o próprio Max/Min
#   (Max/Min viram MEDIÇÃO_Max / MEDIÇÃO_Min para não colidir no DictReader)
#
# parse_appended_rows() lê SOMENTE linhas novas desde a última leitura,
# usando o offset em bytes para posicionar o cursor (f.seek).
# =============================================================================

import os
import csv
import re

from parser.configuravel import (cabecalho_vizinho, colunas_mais_comuns,
                                 montar_registros, segurar_quebra)


def _parse_csv_line(line_text):
    """Parseia uma linha CSV usando o módulo csv do Python (lida com aspas, vírgulas etc.)."""
    return next(csv.reader([line_text]))


def _safe_strip(value):
    """Remove espaços. Retorna None se valor for None."""
    if value is None:
        return None
    return str(value).strip()


# -----------------------------------------------------------------------------
# VALIDAÇÃO DE LINHA (rejeita cabeçalho repetido e lixo binário antes do INSERT)
# -----------------------------------------------------------------------------

HEADER_REPEAT_RATIO = 0.6   # >=60% dos campos iguais ao próprio nome do header
MIN_POPULATED_ABS   = 3     # linha de dados precisa preencher pelo menos 3 campos...
MIN_POPULATED_RATIO = 0.25  # ...e pelo menos 25% do número de colunas do header
GARBAGE_CHAR_ABS    = 3     # >=3 chars U+FFFD/não-imprimíveis => lixo binário
GARBAGE_CHAR_RATIO  = 0.05  # ou >5% de todos os caracteres da linha


def _row_reject_reason(cleaned, headers, has_extra_columns, has_missing=True):
    """Retorna None se a linha parece dado real; senão um código curto do
    motivo da rejeição: 'header_repeat' | 'extra_columns' | 'too_few_fields'
    | 'garbage_chars'.

    Não pega o caso sistemático de UMA coluna com texto de cabeçalho em
    todas as linhas (ex.: Station='Station') — isso é desalinhamento de
    metadados do arquivo, tratado no lado do dashboard."""
    non_empty_headers = [h for h in headers if h]

    # 1) Linha de cabeçalho repetida (testador regravou o header no meio
    #    do arquivo ou em rotação)
    matches = sum(1 for h in non_empty_headers if cleaned.get(h) == h)
    if non_empty_headers and matches / len(non_empty_headers) >= HEADER_REPEAT_RATIO:
        return "header_repeat"

    # 2) Mais células que colunas no header (DictReader estaciona o excesso
    #    sob a chave None)
    if has_extra_columns:
        return "extra_columns"

    # 3) Poucos campos. O mínimo de 25% preenchido só vale para linha TRUNCADA
    #    (menos células que o header). Linha completa e esparsa é dado real: o
    #    PCM tem ~199 colunas e cada teste só preenche as etapas que rodou
    #    (Navajo A17: PASS com ~47 de 197; FAIL abortado no início, menos ainda).
    populated = [v for k, v in cleaned.items() if k and v]
    minimum = MIN_POPULATED_ABS
    if has_missing:
        minimum = max(minimum, int(MIN_POPULATED_RATIO * len(non_empty_headers)))
    if len(populated) < minimum:
        return "too_few_fields"

    # 4) Lixo binário: U+FFFD (de errors='replace') ou não-imprimíveis.
    #    Limiar >1 para não rejeitar um acento legítimo gravado em Latin-1.
    text = "".join(populated)
    junk = sum(1 for c in text if c == "�" or (not c.isprintable() and c != "\t"))
    if junk >= GARBAGE_CHAR_ABS or (text and junk / len(text) > GARBAGE_CHAR_RATIO):
        return "garbage_chars"

    return None


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


def _is_p2500s_header(headers):
    """Cabeçalho do BW P2500S (linha Caiapó, modelo A08): 6 colunas fixas,
    depois triplas (Max, Min, NOME_DA_MEDIÇÃO) e, por último, 'Station'.
    A assinatura é 'Max' e 'Min' repetidos várias vezes no próprio header."""
    if not headers:
        return False
    n_max = sum(1 for h in headers if h.strip().lower() == "max")
    n_min = sum(1 for h in headers if h.strip().lower() == "min")
    return n_max >= 2 and n_max == n_min


def detect_csv_format(second_line_values, station_type="AUTO", headers=None):
    """Determina o formato do CSV.
    Se station.type está definido no config.yaml, respeita (não detecta).
    AUTO: detecta P2500S pelo header (Max/Min repetidos) e PCM_TESTER pelo
    padrão [lsl-usl] na segunda linha; caso contrário CYG."""
    if station_type and station_type.upper() == "PCM_TESTER":
        return "PCM_TESTER"

    if station_type and station_type.upper() == "CYG":
        return "CYG"

    if station_type and station_type.upper() == "FT":
        return "FT"

    if station_type and station_type.upper() == "P2500S":
        return "P2500S"

    # Heurística 1: header do P2500S repete Max/Min por medição
    if _is_p2500s_header(headers or []):
        return "P2500S"

    # Heurística 2: segunda linha de PCM contém padrão [número-número]
    joined = "|".join(second_line_values)

    if re.search(r"\[[\-0-9.]+\s*-\s*[\-0-9.]+\]", joined):
        return "PCM_TESTER"

    return "CYG"


def _p2500s_rename_headers(headers):
    """Dá nome único às colunas Max/Min do P2500S.

    O header vem como ..., Max, Min, OCV, Max, Min, IR, ... — 13 pares com o
    mesmo nome. csv.DictReader guardaria só o último par e os limites por
    medição se perderiam. Cada tripla vira (OCV_Max, OCV_Min, OCV): o
    row_data fica autodescritivo e nenhuma coluna colide.

    Retorna (headers_renomeados, [(nome_medicao, idx_max, idx_min), ...])."""
    renamed = list(headers)
    triples = []
    i = 0
    while i < len(headers) - 2:
        if (headers[i].strip().lower() == "max"
                and headers[i + 1].strip().lower() == "min"):
            name = headers[i + 2].strip()
            renamed[i]     = f"{name}_Max"
            renamed[i + 1] = f"{name}_Min"
            triples.append((name, i, i + 1))
            i += 3
        else:
            i += 1
    return renamed, triples


# -----------------------------------------------------------------------------
# LEITURA DO CABEÇALHO E METADADOS
# -----------------------------------------------------------------------------

def read_header_and_meta(file_path, station_type="AUTO"):
    """Lê cabeçalho, limites e unidades do arquivo CSV.
    Retorna dicionário com format, headers, upper_map, lower_map, unit_map,
    display_map e data_start_offset (posição em bytes onde os dados começam)."""
    with open(file_path, "r", encoding="utf-8-sig", errors="replace", newline="") as f:
        header_line  = f.readline()
        after_header = f.tell()          # P2500S: os dados começam aqui (linha 2)
        second_line  = f.readline()

        if not header_line:
            raise ValueError(f"Arquivo vazio: {file_path}")

        headers       = _parse_csv_line(header_line.rstrip("\n"))
        second_values = _parse_csv_line(second_line.rstrip("\n")) if second_line else []

        csv_format = detect_csv_format(second_values, station_type, headers)

        # P2500S sem cabeçalho (M13 20260903_A08.csv começa direto em
        # "NULL,NG sub-scan failed,..." e o BARCODE.1,... nunca é gravado):
        # usa o cabeçalho do arquivo vizinho da mesma pasta, e os dados
        # começam na linha 1.
        borrowed = None
        if csv_format == "P2500S" and not _is_p2500s_header(headers):
            n_cols = colunas_mais_comuns(file_path)
            cab, borrowed = cabecalho_vizinho(file_path, _is_p2500s_header, n_cols)
            if cab is not None:
                headers, after_header = cab, 0
                second_values = _parse_csv_line(header_line.rstrip("\n"))

        upper_map   = {}
        lower_map   = {}
        unit_map    = {}
        display_map = {}

        if csv_format == "P2500S":
            # P2500S: sem linhas de limite — cada linha de dados carrega o
            # próprio Max/Min ao lado do valor. Dados começam na linha 2.
            # Os limites do catálogo (mes_csv_schemas) saem da primeira linha
            # de dados; se ela estiver truncada, ficam vazios e o próximo
            # arquivo completo preenche.
            data_start_offset = after_header
            headers, triples  = _p2500s_rename_headers(headers)

            for name, i_max, i_min in triples:
                upper_map[name] = (_safe_strip(second_values[i_max]) or None) if i_max < len(second_values) else None
                lower_map[name] = (_safe_strip(second_values[i_min]) or None) if i_min < len(second_values) else None

            for col in headers:
                display_map[col] = col
                unit_map[col]    = None

        elif csv_format == "PCM_TESTER":
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
        "data_start_offset": data_start_offset,  # bytes — usado no f.seek()
        "cabecalho_de":      borrowed,           # None = o próprio arquivo
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
    line_ends      = []
    new_offset     = current_offset

    with open(file_path, "r", encoding="utf-8-sig", errors="replace", newline="") as f:
        f.seek(current_offset)

        while True:
            line = f.readline()

            if not line:
                break   # fim do arquivo

            if not line.endswith("\n"):
                break   # linha incompleta (testador ainda escrevendo) — para aqui

            # NUL vira U+FFFD: o csv do Python 3.8 (edição Win7) aborta o arquivo
            # inteiro com "line contains NUL"; os dois contam igual como lixo.
            complete_lines.append(line.replace("\x00", "\ufffd"))
            line_ends.append(f.tell())   # posição APÓS esta linha

    # Última linha curta num arquivo que acabou de mudar: pode ser a 1ª metade
    # de um registro quebrado por LF solto — espera a próxima leitura.
    hold = segurar_quebra(file_path, complete_lines, len(headers))
    if hold:
        complete_lines, line_ends = complete_lines[:-hold], line_ends[:-hold]
    if line_ends:
        new_offset = line_ends[-1]

    if not complete_lines:
        return {
            "rows":        [],
            "skipped":     [],
            "new_offset":  current_offset,
            "new_line_no": current_line_no,
            "file_size":   file_size,
            "schema":      meta
        }

    rows    = []
    skipped = []   # [(line_no, motivo), ...] — linhas rejeitadas pela validação

    # montar_registros junta os pedaços de um registro quebrado por LF solto e
    # devolve o passo do contador igual ao csv.DictReader de antes (linha vazia
    # não conta; registro de N pedaços conta N), então as linhas boas mantêm o
    # mesmo source_line_no da v1.0.5.
    for step, text, _ in montar_registros(complete_lines, len(headers)):
        if text is None:
            continue
        current_line_no += step
        line_no = current_line_no - step + 1

        values  = _parse_csv_line(text.rstrip("\r\n"))
        cleaned = {_safe_strip(h): _safe_strip(v) for h, v in zip(headers, values)}
        for h in headers[len(values):]:
            cleaned[_safe_strip(h)] = None   # célula ausente (linha truncada)

        reason = _row_reject_reason(cleaned, headers,
                                    has_extra_columns=len(values) > len(headers),
                                    has_missing=len(values) < len(headers))
        if reason:
            # O offset continua avançando (não reprocessar lixo para sempre) e
            # o contador conta a linha pulada.
            skipped.append((line_no, reason))
            continue

        cleaned["_line_no"] = line_no   # número de linha para source_line_no no banco
        rows.append(cleaned)

    return {
        "rows":        rows,
        "skipped":     skipped,
        "new_offset":  new_offset,
        "new_line_no": current_line_no,
        "file_size":   file_size,
        "schema":      meta
    }
