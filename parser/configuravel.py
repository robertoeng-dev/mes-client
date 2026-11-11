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

import collections
import csv
import io
import os
import re
import time
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

# Registro quebrado (Guarani/Taruma/Apurinã, 10/11/2026): no FAIL "NO Data" o
# equipamento grava um LF solto no meio do registro. Se a ÚLTIMA linha lida é
# curta e o arquivo mudou há menos que isto, ela espera a próxima leitura (a
# outra metade pode estar sendo gravada). Arquivo parado: entra como está.
ESPERA_QUEBRA_S = 30

# Arquivo sem cabeçalho (M13 20260903_A08.csv): quantos arquivos vizinhos, na
# mesma pasta, são examinados à procura de um cabeçalho válido.
VIZINHOS_MAX = 30


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
    return next(csv.reader([linha.rstrip("\r\n")], delimiter=delimitador), [])


# -----------------------------------------------------------------------------
# PEÇAS COMUNS AOS PARSERS (também usadas pelo cyg_parser)
# -----------------------------------------------------------------------------

def montar_registros(linhas, n_colunas, delimitador=","):
    """Linhas físicas completas → [(passo, texto, n_fisicas)].

    passo é quanto o contador de linhas avança, igual ao csv.DictReader de
    antes: 0 para linha vazia (texto None), 1 para linha normal e N quando N
    pedaços de um registro quebrado por LF solto foram juntados. Assim as
    linhas boas mantêm o mesmo número (source_line_no) da versão anterior.
    n_fisicas = quantas linhas do arquivo o registro ocupa.

    Junta só quando (1) cada pedaço, menos o último, termina no delimitador
    (o equipamento quebra num campo vazio: "...,FAIL,,,<LF>"; uma linha de
    evento como "NULL,NG sub-scan failed,<data>,2" nunca é emendada) e (2) os
    pedaços somam EXATAMENTE n_colunas (o último campo de um pedaço e o
    primeiro do seguinte são o mesmo campo partido)."""
    contagens = [len(_split(l, delimitador)) for l in linhas]
    abertas = [l.rstrip("\r\n").endswith(delimitador) for l in linhas]
    saida = []
    i = 0
    while i < len(linhas):
        n = contagens[i]
        if n == 0:
            saida.append((0, None, 1))
            i += 1
            continue
        if n < n_colunas and abertas[i]:
            total, j = n, i + 1
            while (total < n_colunas and j < len(linhas) and contagens[j] > 0
                   and abertas[j - 1]):
                total += contagens[j] - 1
                j += 1
            if total == n_colunas and j - i > 1:
                texto = "".join(l.rstrip("\r\n") for l in linhas[i:j - 1]) + linhas[j - 1]
                saida.append((j - i, texto, j - i))
                i = j
                continue
        saida.append((1, linhas[i], 1))
        i += 1
    return saida


def segurar_quebra(caminho, linhas, n_colunas, delimitador=","):
    """Quantas linhas do fim devem esperar a próxima leitura.

    Se o arquivo acabou de mudar e termina numa sequência de pedaços curtos
    que ainda não fecharam um registro (o resto pode estar sendo gravado),
    segura essa sequência inteira — segurar só a última linha soltaria a 1ª
    metade sozinha. Arquivo parado há ESPERA_QUEBRA_S: entra como está."""
    segurar = 0
    for passo, texto, n_fis in reversed(montar_registros(linhas, n_colunas, delimitador)):
        if (texto is None or passo != 1 or len(_split(texto, delimitador)) >= n_colunas
                or not texto.rstrip("\r\n").endswith(delimitador)):
            break
        segurar += n_fis
    if not segurar:
        return 0
    try:
        recente = time.time() - os.path.getmtime(caminho) < ESPERA_QUEBRA_S
    except OSError:
        recente = False
    return segurar if recente else 0


_CACHE_VIZINHO = {}


def cabecalho_vizinho(caminho, eh_cabecalho, n_colunas, encoding="utf-8-sig",
                      delimitador=",", linha_cabecalho=1):
    """Arquivo sem cabeçalho: devolve (cabeçalho, nome_do_vizinho) tirado do
    arquivo mais próximo pelo nome na mesma pasta e com a mesma extensão,
    primeiro os anteriores e depois os seguintes, cuja linha de cabeçalho
    passe em eh_cabecalho(lista) e tenha n_colunas campos. Nenhum → (None, None)."""
    chave = (os.path.abspath(caminho), n_colunas)
    if chave in _CACHE_VIZINHO:
        return _CACHE_VIZINHO[chave]
    pasta, nome = os.path.split(os.path.abspath(caminho))
    ext = os.path.splitext(nome)[1].lower()
    try:
        irmaos = sorted(f for f in os.listdir(pasta)
                        if f != nome and os.path.splitext(f)[1].lower() == ext)
    except OSError:
        irmaos = []
    antes = [f for f in irmaos if f < nome][::-1]
    depois = [f for f in irmaos if f > nome]
    achado = (None, None)
    for f in (antes + depois)[:VIZINHOS_MAX]:
        try:
            with open(os.path.join(pasta, f), "r", encoding=encoding,
                      errors="replace", newline="") as h:
                linha = ""
                for _ in range(linha_cabecalho):
                    linha = h.readline()
        except OSError:
            continue
        cab = [c.strip() for c in _split(linha, delimitador)]
        if len(cab) == n_colunas and eh_cabecalho(cab):
            achado = (cab, f)
            break
    if achado[0] is not None:
        _CACHE_VIZINHO[chave] = achado
    return achado


def colunas_mais_comuns(caminho, encoding="utf-8-sig", delimitador=",", amostra=50):
    """Número de campos mais frequente nas primeiras linhas do arquivo."""
    cont = collections.Counter()
    with open(caminho, "r", encoding=encoding, errors="replace", newline="") as f:
        for _ in range(amostra):
            linha = f.readline()
            if not linha:
                break
            n = len(_split(linha, delimitador))
            if n:
                cont[n] += 1
    return cont.most_common(1)[0][0] if cont else 0


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

    # Arquivo sem cabeçalho: a linha de cabeçalho não tem as colunas mapeadas
    # (serial e resultado). Usa o cabeçalho do arquivo vizinho e lê desde a 1ª linha.
    emprestado = None
    obrigatorias = [d["campos"].get("serial_number"), d["campos"].get("result_status")]
    if not all(c in headers for c in obrigatorias if c):
        n = colunas_mais_comuns(caminho, d["encoding"], d["delimitador"])
        cab, emprestado = cabecalho_vizinho(
            caminho, lambda h: all(c in h for c in obrigatorias if c), n,
            d["encoding"], d["delimitador"], lc)
        if cab is not None:
            headers, inicio_dados = cab, 0
            with open(caminho, "r", encoding=d["encoding"], errors="replace", newline="") as f:
                primeira = f.readline()
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
        "cabecalho_de":      emprestado,      # None = o próprio arquivo
    }


# -----------------------------------------------------------------------------
# VALIDAÇÃO DE LINHA (mesma regra do cyg_parser._row_reject_reason)
# -----------------------------------------------------------------------------

def motivo_rejeicao(cleaned, headers, tem_colunas_extras, faltando=True):
    """faltando = a linha veio com MENOS células que o cabeçalho (truncada).
    O mínimo de 25% preenchido só vale para linha truncada: o PCM tem ~199
    colunas e cada teste preenche só as etapas que rodou (Navajo: PASS com
    ~47 de 197). Linha completa precisa só de MIN_POPULATED_ABS campos."""
    nao_vazios = [h for h in headers if h]
    iguais = sum(1 for h in nao_vazios if cleaned.get(h) == h)
    if nao_vazios and iguais / len(nao_vazios) >= HEADER_REPEAT_RATIO:
        return "header_repeat"
    if tem_colunas_extras:
        return "extra_columns"
    preenchidos = [v for k, v in cleaned.items() if k and v]
    minimo = MIN_POPULATED_ABS
    if faltando:
        minimo = max(minimo, int(MIN_POPULATED_RATIO * len(nao_vazios)))
    if len(preenchidos) < minimo:
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

    linhas, fins = [], []
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
            fins.append(f.tell())

    rows, skipped = [], []
    k = segurar_quebra(caminho, linhas, len(headers), d["delimitador"]) if max_linhas is None else 0
    if k:
        linhas, fins = linhas[:-k], fins[:-k]
    if fins:
        novo_offset = fins[-1]
    for passo, texto, _ in montar_registros(linhas, len(headers), d["delimitador"]):
        if texto is None:
            continue
        line_no += passo
        valores = _split(texto, d["delimitador"])
        cleaned = {_strip(h): _strip(v) for h, v in zip(headers, valores)}
        for h in headers[len(valores):]:
            cleaned[_strip(h)] = None
        motivo = motivo_rejeicao(cleaned, headers, len(valores) > len(headers),
                                 faltando=len(valores) < len(headers))
        if motivo:
            skipped.append((line_no - passo + 1, motivo))
            continue
        cleaned["_line_no"] = line_no - passo + 1
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
