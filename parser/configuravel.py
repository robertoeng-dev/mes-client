# =============================================================================
# configuravel.py — Parser de CSV/TXT definido pelo cadastro (sem código novo)
# =============================================================================
#
# Um formato CONFIGURAVEL do MES Cadastro (tabela mes_formatos, coluna
# "definicao" JSONB) descreve como ler o arquivo:
#
#   {
#     "delimitador":     ",",            # "," ";" "\t" "|" ...
#     "encoding":        "utf-8-sig",    # ou "latin-1", "cp1252"
#     "linha_cabecalho": 1,              # linha (1 = primeira) com os nomes
#     "linha_dados":     2,              # primeira linha de dados
#     "max_min":         "antes_da_medicao" | "nenhum",
#     "campos": {                        # coluna do arquivo para cada campo
#       "serial_number":   "BARCODE.1",
#       "result_status":   "TESTRESULT",
#       "test_start_time": "TESTTIME",
#       "test_stop_time":  null,
#       "model_name":      "MODELNAME",
#       "defeito":         null,
#       "anexo":           null           # nome/caminho da imagem (AOI)
#     },
#     "formato_data":    "%Y%m%d%H%M%S", # strptime; vazio = tenta ISO
#     "valores_pass":    ["PASS", "OK"], # opcional; padrão = lista do cliente
#     "valores_fail":    ["FAIL", "NG"],
#     "modelo_regex":    "^(A\\d+)"      # opcional; grupo 1 vira o modelo
#   }
#
# ESTE ARQUIVO É COMPARTILHADO com o gerenciador web (prévia do formato).
# Por isso: só biblioteca padrão, nenhum import do cliente, e Python 3.8
# (edição Win7). Qualquer mudança aqui vale para os dois lados.
# =============================================================================

import csv
import io
import os
import re
from datetime import datetime

VERSAO_DEFINICAO = 1

CAMPOS = ("serial_number", "result_status", "test_start_time", "test_stop_time",
          "model_name", "defeito", "anexo")

PASS_PADRAO = ("PASS", "PASSED", "OK", "P", "1", "TRUE", "GOOD")
FAIL_PADRAO = ("FAIL", "FAILED", "NG", "F", "0", "FALSE", "BAD")

# Mesmos limiares do cyg_parser (validação de linha antes do INSERT)
HEADER_REPEAT_RATIO = 0.6
MIN_POPULATED_ABS = 3
MIN_POPULATED_RATIO = 0.25
GARBAGE_CHAR_ABS = 3
GARBAGE_CHAR_RATIO = 0.05

_DELIMITADORES_VALIDOS = (",", ";", "\t", "|", " ")


# -----------------------------------------------------------------------------
# DEFINIÇÃO
# -----------------------------------------------------------------------------

def normalizar_definicao(definicao):
    """Completa a definição com os valores padrão. Não altera o dict original."""
    d = dict(definicao or {})
    d.setdefault("delimitador", ",")
    d.setdefault("encoding", "utf-8-sig")
    d.setdefault("linha_cabecalho", 1)
    d.setdefault("linha_dados", int(d["linha_cabecalho"]) + 1)
    d.setdefault("max_min", "nenhum")
    campos = dict(d.get("campos") or {})
    for c in CAMPOS:
        campos.setdefault(c, None)
    d["campos"] = campos
    d.setdefault("formato_data", "")
    d.setdefault("modelo_regex", "")
    return d


def validar_definicao(definicao):
    """Devolve a lista de erros (vazia = definição válida)."""
    erros = []
    if not isinstance(definicao, dict):
        return ["a definição deve ser um objeto JSON"]
    d = normalizar_definicao(definicao)

    if d["delimitador"] not in _DELIMITADORES_VALIDOS:
        erros.append("delimitador inválido: %r (use , ; | espaço ou \\t)" % (d["delimitador"],))
    try:
        "x".encode(d["encoding"])
    except (LookupError, TypeError):
        erros.append("encoding desconhecido: %r" % (d["encoding"],))
    try:
        lc, ld = int(d["linha_cabecalho"]), int(d["linha_dados"])
        if lc < 1:
            erros.append("linha_cabecalho deve ser >= 1")
        if ld <= lc:
            erros.append("linha_dados deve ser maior que linha_cabecalho")
    except (TypeError, ValueError):
        erros.append("linha_cabecalho e linha_dados devem ser números inteiros")
    if d["max_min"] not in ("nenhum", "antes_da_medicao"):
        erros.append("max_min deve ser 'nenhum' ou 'antes_da_medicao'")
    desconhecidos = set(definicao.get("campos") or {}) - set(CAMPOS)
    if desconhecidos:
        erros.append("campos desconhecidos: " + ", ".join(sorted(desconhecidos)))
    if not d["campos"].get("serial_number"):
        erros.append("campos.serial_number é obrigatório")
    if not d["campos"].get("result_status"):
        erros.append("campos.result_status é obrigatório")
    if d["formato_data"]:
        try:
            datetime(2026, 1, 2, 3, 4, 5).strftime(d["formato_data"])
        except (ValueError, TypeError):
            erros.append("formato_data inválido: %r" % (d["formato_data"],))
    if d["modelo_regex"]:
        try:
            re.compile(d["modelo_regex"])
        except re.error as e:
            erros.append("modelo_regex inválido: %s" % e)
    for chave in ("valores_pass", "valores_fail"):
        v = definicao.get(chave)
        if v is not None and (not isinstance(v, list) or not all(isinstance(x, str) for x in v)):
            erros.append("%s deve ser uma lista de textos" % chave)
    return erros


# -----------------------------------------------------------------------------
# CABEÇALHO
# -----------------------------------------------------------------------------

def _strip(v):
    return None if v is None else str(v).strip()


def _renomear_max_min(headers):
    """..., Max, Min, OCV, ... → OCV_Max, OCV_Min, OCV (igual ao P2500S)."""
    renamed = list(headers)
    triplas = []
    i = 0
    while i < len(headers) - 2:
        if headers[i].strip().lower() == "max" and headers[i + 1].strip().lower() == "min":
            nome = headers[i + 2].strip()
            renamed[i] = nome + "_Max"
            renamed[i + 1] = nome + "_Min"
            triplas.append((nome, i, i + 1))
            i += 3
        else:
            i += 1
    return renamed, triplas


def _split(linha, delimitador):
    return next(csv.reader([linha.rstrip("\r\n")], delimiter=delimitador))


def ler_cabecalho(caminho, definicao):
    """Lê o cabeçalho e devolve o mesmo formato de schema do cyg_parser:
    format, headers, upper_map, lower_map, unit_map, display_map,
    data_start_offset."""
    d = normalizar_definicao(definicao)
    lc, ld = int(d["linha_cabecalho"]), int(d["linha_dados"])

    with open(caminho, "r", encoding=d["encoding"], errors="replace", newline="") as f:
        linha_cab = ""
        for _ in range(lc):
            linha_cab = f.readline()
            if not linha_cab:
                raise ValueError("Arquivo sem a linha de cabeçalho %d: %s" % (lc, caminho))
        for _ in range(ld - lc - 1):
            f.readline()
        inicio_dados = f.tell()
        primeira = f.readline()

    headers = [h.strip() for h in _split(linha_cab, d["delimitador"])]
    primeiros = _split(primeira, d["delimitador"]) if primeira.endswith("\n") else []

    upper, lower = {}, {}
    if d["max_min"] == "antes_da_medicao":
        headers, triplas = _renomear_max_min(headers)
        for nome, i_max, i_min in triplas:
            upper[nome] = (_strip(primeiros[i_max]) or None) if i_max < len(primeiros) else None
            lower[nome] = (_strip(primeiros[i_min]) or None) if i_min < len(primeiros) else None

    return {
        "format":            "CONFIGURAVEL",
        "headers":           headers,
        "upper_map":         upper,
        "lower_map":         lower,
        "unit_map":          {h: None for h in headers},
        "display_map":       {h: h for h in headers},
        "data_start_offset": inicio_dados,
    }


# -----------------------------------------------------------------------------
# VALIDAÇÃO DE LINHA (mesma regra do cyg_parser._row_reject_reason)
# -----------------------------------------------------------------------------

def motivo_rejeicao(cleaned, headers, tem_colunas_extras):
    nao_vazios = [h for h in headers if h]
    iguais = sum(1 for h in nao_vazios if cleaned.get(h) == h)
    if nao_vazios and iguais / len(nao_vazios) >= HEADER_REPEAT_RATIO:
        return "header_repeat"
    if tem_colunas_extras:
        return "extra_columns"
    preenchidos = [v for k, v in cleaned.items() if k and v]
    if len(preenchidos) < max(MIN_POPULATED_ABS, int(MIN_POPULATED_RATIO * len(nao_vazios))):
        return "too_few_fields"
    texto = "".join(preenchidos)
    lixo = sum(1 for c in texto if c == "�" or (not c.isprintable() and c != "\t"))
    if lixo >= GARBAGE_CHAR_ABS or (texto and lixo / len(texto) > GARBAGE_CHAR_RATIO):
        return "garbage_chars"
    return None


# -----------------------------------------------------------------------------
# LEITURA INCREMENTAL (mesmo contrato do cyg_parser.parse_appended_rows)
# -----------------------------------------------------------------------------

def parse_appended_rows(caminho, last_state, definicao, max_linhas=None):
    """Lê só as linhas novas desde last_state {offset, line_no, file_size}.
    Só conta linhas completas (terminadas em \\n). Arquivo que encolheu
    (rotação) recomeça do início. max_linhas limita a leitura (prévia)."""
    d = normalizar_definicao(definicao)
    meta = ler_cabecalho(caminho, d)
    headers = meta["headers"]
    tamanho = os.path.getsize(caminho)

    if tamanho < last_state.get("file_size", 0):
        offset, line_no = meta["data_start_offset"], 0
    else:
        offset = last_state.get("offset") or meta["data_start_offset"]
        line_no = last_state.get("line_no", 0)
        if offset < meta["data_start_offset"]:
            offset = meta["data_start_offset"]

    linhas = []
    novo_offset = offset
    with open(caminho, "r", encoding=d["encoding"], errors="replace", newline="") as f:
        f.seek(offset)
        while max_linhas is None or len(linhas) < max_linhas:
            linha = f.readline()
            if not linha or not linha.endswith("\n"):
                break
            # NUL vira U+FFFD: o csv do Python 3.8 aborta o arquivo inteiro com
            # "line contains NUL"; os dois contam igual como lixo (garbage_chars).
            linhas.append(linha.replace("\x00", "\ufffd"))
            novo_offset = f.tell()

    rows, skipped = [], []
    if linhas:
        reader = csv.DictReader(io.StringIO("".join(linhas)), fieldnames=headers,
                                delimiter=d["delimitador"])
        for row in reader:
            line_no += 1
            extra = row.pop(None, None)
            cleaned = {_strip(k): _strip(v) for k, v in row.items()}
            motivo = motivo_rejeicao(cleaned, headers, extra is not None)
            if motivo:
                skipped.append((line_no, motivo))
                continue
            cleaned["_line_no"] = line_no
            rows.append(cleaned)

    return {
        "rows":        rows,
        "skipped":     skipped,
        "new_offset":  novo_offset,
        "new_line_no": line_no,
        "file_size":   tamanho,
        "schema":      meta,
    }


# -----------------------------------------------------------------------------
# CAMPOS ESTRUTURADOS
# -----------------------------------------------------------------------------

def normalizar_resultado(valor, definicao=None):
    """PASS / FAIL por valor exato; valor desconhecido é preservado (maiúsculo)."""
    if not valor:
        return None
    d = definicao or {}
    v = str(valor).strip().upper()
    passa = set(x.strip().upper() for x in (d.get("valores_pass") or PASS_PADRAO))
    falha = set(x.strip().upper() for x in (d.get("valores_fail") or FAIL_PADRAO))
    if v in passa:
        return "PASS"
    if v in falha:
        return "FAIL"
    return v


def iso_flexivel(texto):
    """fromisoformat que aceita no Python 3.8 (edição Win7) o mesmo que o 3.11+:
    sufixo Z, fração com 1 a 6 dígitos e ISO compacto (YYYYMMDDTHHMMSS).
    Devolve datetime, ou None se o texto não for ISO 8601."""
    texto = str(texto).strip()
    try:
        return datetime.strptime(texto, "%Y%m%dT%H%M%S")
    except ValueError:
        pass
    iso = texto[:-1] + "+00:00" if texto.endswith("Z") else texto
    m = re.match(r"^(.*[T ]\d{2}:\d{2}:\d{2})\.(\d{1,6})(.*)$", iso)
    if m:
        iso = "%s.%s%s" % (m.group(1), m.group(2).ljust(6, "0"), m.group(3))
    try:
        return datetime.fromisoformat(iso)
    except ValueError:
        return None


def converter_data(valor, formato=""):
    """Texto → 'YYYY-MM-DD HH:MM:SS' (hora local da planta), ou None.
    Nunca adivinha: formato desconhecido vira None."""
    if not valor:
        return None
    texto = str(valor).strip()
    formatos = [formato] if formato else []
    formatos.append("%Y%m%d%H%M%S")
    for fmt in formatos:
        try:
            return datetime.strptime(texto, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    dt = iso_flexivel(texto)
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else None


def extrair_campos(row, definicao):
    """Linha já parseada → dict com os campos estruturados do banco.
    test_*_time voltam como texto 'YYYY-MM-DD HH:MM:SS' (sem fuso)."""
    d = normalizar_definicao(definicao)
    c = d["campos"]

    def col(nome):
        coluna = c.get(nome)
        if not coluna:
            return None
        v = row.get(coluna)
        return v if v not in ("", None) else None

    modelo = col("model_name")
    if modelo and d["modelo_regex"]:
        m = re.search(d["modelo_regex"], modelo)
        modelo = (m.group(1) if m and m.groups() else (m.group(0) if m else modelo)).strip()

    bruto_ini, bruto_fim = col("test_start_time"), col("test_stop_time")
    return {
        "serial_number":   col("serial_number"),
        "result_status":   normalizar_resultado(col("result_status"), d),
        "test_start_time": converter_data(bruto_ini, d["formato_data"]),
        "test_stop_time":  converter_data(bruto_fim, d["formato_data"]),
        "model_name":      modelo,
        "defeito":         col("defeito"),
        "anexo":           col("anexo"),
        "_data_invalida":  bool((bruto_ini and not converter_data(bruto_ini, d["formato_data"]))
                                or (bruto_fim and not converter_data(bruto_fim, d["formato_data"]))),
    }


def previa(caminho, definicao, max_linhas=20):
    """Prévia para o gerenciador/cliente: lê até max_linhas sem gravar nada.
    Devolve {erros, headers, linhas: [{line_no, campos, row}], rejeitadas}."""
    erros = validar_definicao(definicao)
    if erros:
        return {"erros": erros, "headers": [], "linhas": [], "rejeitadas": []}
    try:
        r = parse_appended_rows(caminho, {"offset": 0, "line_no": 0, "file_size": 0},
                                definicao, max_linhas=max_linhas)
    except (OSError, ValueError, csv.Error) as e:
        return {"erros": [str(e)], "headers": [], "linhas": [], "rejeitadas": []}
    headers = r["schema"]["headers"]
    d = normalizar_definicao(definicao)
    faltando = [v for v in d["campos"].values() if v and v not in headers]
    erros = ["coluna não existe no arquivo: %s" % v for v in faltando]
    linhas = [{"line_no": row["_line_no"], "campos": extrair_campos(row, d), "row": row}
              for row in r["rows"]]
    return {"erros": erros, "headers": headers, "linhas": linhas, "rejeitadas": r["skipped"]}
