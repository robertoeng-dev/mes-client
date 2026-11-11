# =============================================================================
# test_paridade.py — cliente 2.0 x cliente v1.0.5 nos logs reais (sem banco)
# =============================================================================
#   .venv\Scripts\python.exe tests\test_paridade.py <pasta_da_copia_v105>
#
# A cópia do v1.0.5 sai do backup _backup_pre-cadastro_2026-11-06 (copiar
# para uma pasta temporária: o import cria logs/ dentro dela).
#
#  [M13] P2500S dedicado: os 18 CSVs de Logs-Amostras\M13 Station\202609 têm
#        que dar EXATAMENTE o mesmo lote (linhas, nº de linha, serial,
#        resultado, data, modelo, versão, schema_hash, row_data), as mesmas
#        rejeitadas e o mesmo offset final.
#  [M2]  OCV pelo formato CONFIGURAVEL (database/formatos/OCV_TABCUT.json):
#        os 9 CSVs têm que dar as mesmas linhas/row_data/rejeitadas/offset que
#        o parser P2500S do v1.0.5 e os campos mapeados certos.
#  [INC] leitura incremental: o arquivo crescendo aos pedaços dá o mesmo
#        total que a leitura de uma vez (nos dois parsers).
# =============================================================================

import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from config.column_mapper import load_mappings          # noqa: E402
from parser import configuravel, registry                # noqa: E402
from parser.campos import schema_hash                    # noqa: E402

AMOSTRAS = os.environ.get("MES_AMOSTRAS") or os.path.join(os.path.dirname(RAIZ), "Logs-Amostras", "CAIAPO")
M13 = sorted(glob.glob(os.path.join(AMOSTRAS, "M13 Station", "202609", "*.csv")))
M2 = sorted(glob.glob(os.path.join(AMOSTRAS, "M2 Station", "202609", "*.csv")))
OCV_DEF = json.load(open(os.path.join(RAIZ, "database", "formatos", "OCV_TABCUT.json"), encoding="utf-8"))

# Amostras das outras estações (10/11/2026)
TODAS = os.path.dirname(AMOSTRAS)
def _g(*p):
    return sorted(glob.glob(os.path.join(TODAS, *p)))
GUARANI = _g("GUARANI", "TAB-OCV", "*.CSV")
APURINA = _g("APURINA", "FT", "*.CSV")
APURINA_QUEBRADO = next((f for f in APURINA if f.endswith("Pack 30_APURINA_1.CSV")), None)
TARUMA = _g("TARUMA", "*.CSV")
MURA = _g("MURA", "*.CSV")
PCM_CARAJAS = _g("CARAJAS", "PCM TESTER-01", "*", "*", "*.csv") + _g("CARAJAS", "PCM TESTER-02", "*", "*", "*", "*.csv")
PCM_NAVAJO = _g("NAVAJO", "A17", "2026-1*", "*", "*.csv")
AOI = _g("CAIAPO", "M2 Station", "FOTOS", "Config", "ProductData", "CCD", "*", "*.csv")
AOI_DEF = {"delimitador": ",", "linha_cabecalho": 1,
           "campos": {"serial_number": "Bar", "result_status": "Result", "test_start_time": "Time"},
           "valores_pass": ["OK"], "valores_fail": ["NG"]}

falhas = []


def checar(cond, msg):
    print("   %s %s" % ("ok   " if cond else "FALHA", msg))
    if not cond:
        falhas.append(msg)


def v105(pasta, station_type, modelo, arquivos):
    r = subprocess.run([sys.executable, os.path.join(RAIZ, "tests", "_paridade_v105.py"),
                        pasta, station_type, modelo] + arquivos,
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError("v1.0.5 falhou:\n" + r.stderr[-2000:])
    return json.loads(r.stdout)


def novo(fonte, caminho):
    p = registry.ler(fonte, caminho, {"offset": 0, "line_no": 0, "file_size": 0})
    h = schema_hash(p["schema"]["headers"])
    lote, _, _ = registry.montar_lote(fonte, p, caminho, os.path.basename(caminho), h, load_mappings())
    return p, lote


def comparar_lotes(nome, antigo, p, lote, campos):
    checar(len(lote) == len(antigo["lote"]), "%s: %d linhas (v1.0.5: %d)" % (nome, len(lote), len(antigo["lote"])))
    checar([list(x) for x in p["skipped"]] == antigo["skipped"],
           "%s: mesmas %d rejeitadas" % (nome, len(p["skipped"])))
    checar(p["new_offset"] == antigo["new_offset"] and p["new_line_no"] == antigo["new_line_no"],
           "%s: mesmo offset/linha final (%d / %d)" % (nome, p["new_offset"], p["new_line_no"]))
    dif = 0
    for a, b in zip(antigo["lote"], lote):
        for c in campos:
            if a[c] != b[c]:
                if dif < 5:
                    print("         linha %s campo %s: v1.0.5=%r novo=%r" % (a["source_line_no"], c, a[c], b[c]))
                dif += 1
    checar(dif == 0, "%s: campos idênticos (%s)" % (nome, ", ".join(campos)))


def teste_m13(pasta):
    print("\n[M13] P2500S dedicado x v1.0.5 (%d arquivos)" % len(M13))
    checar(len(M13) == 18, "18 CSVs de amostra encontrados")
    fonte = {"fonte_id": 1, "formato_tipo": "DEDICADO", "formato_codigo": "P2500S",
             "modelo_atual": "A08", "fuso": "America/Manaus"}
    antigos = v105(pasta, "P2500S", "A08", M13)
    auto = v105(pasta, "AUTO", "A08", M13[:2])
    campos = ("model_name", "version_name", "serial_number", "result_status",
              "test_start_time", "test_stop_time", "source_line_no", "schema_hash", "row_data")
    total = novas = 0
    for caminho in M13:
        nome = os.path.basename(caminho)
        p, lote = novo(fonte, caminho)
        total += len(lote)
        a = antigos[nome]
        # Correções de 10/11 (RELATORIO_2026-11-10_ABRANGENCIA_LOGS.md): o 2.0 lê
        # MAIS que a v1.0.5 (FAIL completo e esparso; arquivo sem cabeçalho), mas
        # toda linha que a v1.0.5 gravava tem que continuar IDÊNTICA.
        sem_cab = nome == "20260903_A08.csv"
        novo_por_linha = {x["source_line_no"]: x for x in lote}
        if sem_cab:
            checar(p["schema"]["cabecalho_de"] == "20260902_A08.csv",
                   "%s: sem cabeçalho, usa o do vizinho 20260902_A08.csv" % nome)
            checar(len(lote) >= 2841 and all(x["result_status"] in ("PASS", "FAIL") for x in lote),
                   "%s: %d testes recuperados (v1.0.5: %d linhas-lixo)" % (nome, len(lote), len(a["lote"])))
        else:
            dif = sum(1 for x in a["lote"]
                      if any(novo_por_linha.get(x["source_line_no"], {}).get(c) != x[c] for c in campos))
            checar(dif == 0, "%s: as %d linhas da v1.0.5 idênticas" % (nome, len(a["lote"])))
            checar(p["new_offset"] == a["new_offset"] and p["new_line_no"] == a["new_line_no"],
                   "%s: mesmo offset/linha final" % nome)
        antigas = {x["source_line_no"] for x in a["lote"]}
        extras = [x for x in lote if x["source_line_no"] not in antigas]
        novas += len(extras)
        checar(all(x["result_status"] in ("PASS", "FAIL") and x["test_start_time"] for x in extras),
               "%s: %d linhas novas, todas com resultado e data" % (nome, len(extras)))
    checar(all(auto[n]["lote"] == antigos[n]["lote"] for n in auto), "v1.0.5 com type AUTO = P2500S")
    print("   total M13: %d linhas (%d além da v1.0.5)" % (total, novas))


def teste_m2(pasta):
    print("\n[M2] OCV CONFIGURAVEL x parser P2500S do v1.0.5 (%d arquivos)" % len(M2))
    checar(len(M2) == 9, "9 CSVs de amostra encontrados")
    checar(configuravel.validar_definicao(OCV_DEF) == [], "definição OCV_TABCUT válida")
    fonte = {"fonte_id": 2, "formato_tipo": "CONFIGURAVEL", "formato_codigo": "OCV_TABCUT",
             "definicao": OCV_DEF, "modelo_atual": "A08", "fuso": "America/Manaus"}
    antigos = v105(pasta, "AUTO", "A08", M2)
    total = 0
    for caminho in M2:
        nome = os.path.basename(caminho)
        a = antigos[nome]
        checar(a["format"] == "P2500S", "%s: v1.0.5 detecta como P2500S" % nome)
        p, lote = novo(fonte, caminho)
        total += len(lote)
        comparar_lotes(nome, a, p, lote, ("serial_number", "result_status", "test_start_time",
                                           "source_line_no", "schema_hash", "row_data"))
        checar(p["schema"]["upper_map"] == a["upper"] and p["schema"]["lower_map"] == a["lower"],
               "%s: mesmos limites Max/Min no catálogo" % nome)
        checar(all(x["model_name"] == "A08" for x in lote), "%s: modelo A08 (regex sobre MODELNAME)" % nome)
    print("   total M2 OCV: %d linhas" % total)


def teste_incremental():
    print("\n[INC] arquivo crescendo aos pedaços = leitura de uma vez")
    casos = [({"fonte_id": 1, "formato_tipo": "DEDICADO", "formato_codigo": "P2500S"}, M13[-1]),
             ({"fonte_id": 2, "formato_tipo": "CONFIGURAVEL", "formato_codigo": "OCV_TABCUT",
               "definicao": OCV_DEF}, M2[0])]
    # registros quebrados por LF solto, lidos aos pedaços (a metade pendente espera)
    casos += [({"fonte_id": 3, "formato_tipo": "DEDICADO", "formato_codigo": "P2500S"}, f)
              for f in [GUARANI[0], APURINA_QUEBRADO] if f]
    casos += [({"fonte_id": 4, "formato_tipo": "CONFIGURAVEL", "formato_codigo": "OCV_TABCUT",
                "definicao": OCV_DEF}, GUARANI[0])]
    tmp = tempfile.mkdtemp(prefix="mes_inc_")
    try:
        for fonte, origem in casos:
            dados = open(origem, "rb").read()
            alvo = os.path.join(tmp, os.path.basename(origem))
            estado = {"offset": 0, "line_no": 0, "file_size": 0}
            linhas = []
            # corta em pedaços que partem linhas ao meio (linha incompleta tem que esperar)
            passo = max(1, len(dados) // 7) + 13
            for fim in list(range(passo, len(dados), passo)) + [len(dados)]:
                with open(alvo, "wb") as f:
                    f.write(dados[:fim])
                p = registry.ler(fonte, alvo, estado)
                linhas += [r["_line_no"] for r in p["rows"]]
                estado = {"offset": p["new_offset"], "line_no": p["new_line_no"], "file_size": p["file_size"]}
            inteiro = registry.ler(fonte, origem, {"offset": 0, "line_no": 0, "file_size": 0})
            esperado = [r["_line_no"] for r in inteiro["rows"]]
            checar(linhas == esperado, "%s %s: %d linhas, sem perder nem repetir"
                   % (fonte["formato_codigo"], os.path.basename(origem), len(linhas)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _ler_todos(fonte, arquivos):
    rows, skipped, sem = 0, 0, 0
    outros = set()
    for a in arquivos:
        p = registry.ler(fonte, a, {"offset": 0, "line_no": 0, "file_size": 0})
        rows += len(p["rows"])
        skipped += len(p["skipped"])
        lote, _, _ = registry.montar_lote(fonte, p, a, os.path.basename(a), "h", load_mappings())
        sem += sum(1 for x in lote if not x["result_status"] or not x["test_start_time"])
        outros.update(x["result_status"] for x in lote if x["result_status"] not in ("PASS", "FAIL"))
    return rows, skipped, sem, outros


def teste_abrangencia():
    print("\n[ABR] estações das amostras de 10/11 (RELATORIO_2026-11-10_ABRANGENCIA_LOGS.md)")
    p2500 = {"fonte_id": 9, "formato_tipo": "DEDICADO", "formato_codigo": "P2500S", "modelo_atual": "A08"}
    pcm = {"fonte_id": 9, "formato_tipo": "DEDICADO", "formato_codigo": "PCM_TESTER", "modelo_atual": "A08"}
    aoi = {"fonte_id": 9, "formato_tipo": "CONFIGURAVEL", "formato_codigo": "AOI", "definicao": AOI_DEF}
    casos = [("GUARANI", p2500, GUARANI, 2, 2423), ("TARUMA", p2500, TARUMA, 1, 900),
             ("APURINA", p2500, APURINA, 4, 1327), ("MURA", p2500, MURA, 1, 1102),
             ("PCM CARAJAS", pcm, PCM_CARAJAS, 14, 18420), ("PCM NAVAJO out-nov", pcm, PCM_NAVAJO, 0, None),
             ("AOI M2", aoi, AOI, 18, 117466)]
    for nome, fonte, arqs, n_arqs, n_rows in casos:
        if n_arqs:
            checar(len(arqs) == n_arqs, "%s: %d arquivos encontrados" % (nome, len(arqs)))
        rows, skipped, sem, outros = _ler_todos(fonte, arqs)
        if outros:
            print("   info  %s: status preservado como veio do equipamento: %s" % (nome, sorted(outros)))
        if n_rows is not None:
            checar(rows == n_rows, "%s: %d registros (esperado %d)" % (nome, rows, n_rows))
        checar(sem == 0, "%s: nenhum registro sem resultado/data (%d)" % (nome, sem))
        if fonte is pcm:
            checar(skipped == 0 and rows > 0, "%s: PCM sem descarte (%d lidos, %d rejeitados)" % (nome, rows, skipped))

    # Guarani: os 45 FAIL "NO Data" quebrados voltam inteiros
    p = registry.ler(p2500, GUARANI[0], {"offset": 0, "line_no": 0, "file_size": 0})
    nodata = [r for r in p["rows"] if r.get("INPUT OCV") == "NO Data"]
    checar(len(nodata) > 0 and all(r["TESTRESULT"] == "FAIL" and r["Cell Barcode"] == r["BARCODE.1"]
                                   for r in nodata),
           "GUARANI: %d FAIL 'NO Data' juntados com serial, resultado e medida alinhados" % len(nodata))

    # Unidade: junção só com campo vazio na fronteira e soma exata
    j = configuravel.montar_registros
    checar([x[:2] for x in j(["a,b,\n", "c,d\r\n"], 4)] == [(2, "a,b,c,d\r\n")], "junta 2 pedaços que somam as colunas")
    checar([x[:2] for x in j(["a,\n", "b,c,\n", "d,e\r\n"], 5)] == [(3, "a,b,c,d,e\r\n")], "junta 3 pedaços (Apurinã)")
    checar([x[0] for x in j(["NULL,NG,1\n", "NULL,NG,2\n"], 5)] == [1, 1],
           "não emenda linhas de evento (não terminam no delimitador)")
    checar([x[0] for x in j(["\r\n", "a,b,c\r\n"], 3)] == [0, 1], "linha vazia não conta")
    checar([x[0] for x in j(["a,\n", "b,c,d,e\r\n"], 3)] == [1, 1], "soma diferente não junta")


def teste_definicao():
    print("\n[DEF] validação da definição de formato")
    ruins = [({}, "sem serial/resultado"),
             (dict(OCV_DEF, delimitador="x"), "delimitador inválido"),
             (dict(OCV_DEF, linha_dados=1), "dados antes do cabeçalho"),
             (dict(OCV_DEF, encoding="nao-existe"), "encoding desconhecido"),
             (dict(OCV_DEF, modelo_regex="(A"), "regex inválida"),
             (dict(OCV_DEF, campos=dict(OCV_DEF["campos"], serial="X")), "campo desconhecido")]
    for d, desc in ruins:
        checar(configuravel.validar_definicao(d) != [], "recusa: " + desc)
    pv = configuravel.previa(M2[0], OCV_DEF, 20)
    checar(pv["erros"] == [] and len(pv["linhas"]) == 20, "prévia de 20 linhas sem erro")
    pv = configuravel.previa(M2[0], dict(OCV_DEF, campos=dict(OCV_DEF["campos"], defeito="NAO_EXISTE")), 5)
    checar(any("NAO_EXISTE" in e for e in pv["erros"]), "prévia avisa coluna inexistente")
    checar(configuravel.normalizar_resultado("PENDING") == "PENDING", "PENDING não vira FAIL")
    checar(configuravel.converter_data("03/09/2026", "") is None, "data ambígua vira None")
    ok, _ = registry.formato_suportado({"formato_tipo": "DEDICADO", "formato_codigo": "XPTO"})
    checar(not ok, "dedicado desconhecido é recusado")


def main():
    if len(sys.argv) < 2 or not os.path.isdir(os.path.join(sys.argv[1], "parser")):
        print("uso: test_paridade.py <pasta_da_copia_v105>")
        sys.exit(2)
    teste_m13(sys.argv[1])
    teste_m2(sys.argv[1])
    teste_incremental()
    teste_abrangencia()
    teste_definicao()
    print("\n%d falha(s)" % len(falhas))
    sys.exit(1 if falhas else 0)


if __name__ == "__main__":
    main()
