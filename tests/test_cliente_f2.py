# =============================================================================
# test_cliente_f2.py — cliente 2.0 (monitor + db_writer) contra o PostgreSQL real
# =============================================================================
#   .venv\Scripts\python.exe tests\test_cliente_f2.py
#
# Como o test_cadastro_db.py: conecta como mes_homolog (pgpass.conf), cria um
# banco DESCARTÁVEL (mes_teste_cli_<pid>), aplica o 002, cadastra a M13 (fonte
# FT, P2500S dedicado) e a M2 (fonte OCV, formato configurável) e roda o
# MonitorFontes de verdade, gravando como mes_grp_client (SET ROLE).
# Pastas, offsets, fila e cache ficam numa pasta temporária. Apaga tudo no fim.
# =============================================================================

import json
import os
import shutil
import sys
import tempfile
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import psycopg2                                       # noqa: E402
from psycopg2.extras import Json                      # noqa: E402

from buffer.queue_buffer import OfflineQueue          # noqa: E402
from database.db_writer import DBWriter               # noqa: E402
from monitor import file_monitor as fm                # noqa: E402
from parser import registry                           # noqa: E402
from state.app_context import runtime_status          # noqa: E402
from state.offset_manager import OffsetManager        # noqa: E402
from state.station_cache import StationCache          # noqa: E402

HOST = os.environ.get("MES_TEST_HOST", "172.21.70.184")
USER = "mes_homolog"
BASE = "mes_nonalpha_homolog"
TESTE_DB = "mes_teste_cli_%d" % os.getpid()
SQL_002 = os.path.join(RAIZ, "database", "002_cadastro.sql")
AMOSTRAS = os.environ.get("MES_AMOSTRAS") or os.path.join(os.path.dirname(RAIZ), "Logs-Amostras", "CAIAPO")
M13_PEQ = os.path.join(AMOSTRAS, "M13 Station", "202609", "20260903_A08.csv")     # sem cabeçalho: usa o do vizinho (2.841 testes)
M13_GDE = os.path.join(AMOSTRAS, "M13 Station", "202609", "20260915_A08.csv")     # 3367 boas
M2_OCV = os.path.join(AMOSTRAS, "M2 Station", "202609", "20260911_A08 CELL 30% CAIAPO.csv")
OCV_DEF = json.load(open(os.path.join(RAIZ, "database", "formatos", "OCV_TABCUT.json"), encoding="utf-8"))

falhas = []


def checar(cond, msg):
    print("   %s %s" % ("ok   " if cond else "FALHA", msg))
    if not cond:
        falhas.append(msg)


def conectar(db, role=None, app="teste_cliente"):
    c = psycopg2.connect(host=HOST, port=5432, dbname=db, user=USER, application_name=app, connect_timeout=10)
    c.autocommit = True
    if role:
        c.cursor().execute("SET ROLE " + role)
    return c


def um(conn, sql, args=None):
    cur = conn.cursor()
    cur.execute(sql, args)
    return cur.fetchone()


def esperado(caminho, fonte):
    return len(registry.ler(fonte, caminho, {"offset": 0, "line_no": 0, "file_size": 0})["rows"])


class Ambiente:
    """Pastas e arquivos de estado de um 'PC' de teste."""

    def __init__(self, raiz, nome):
        self.dir = os.path.join(raiz, nome)
        self.m13 = os.path.join(self.dir, "battData")
        self.m2 = os.path.join(self.dir, "ocv")
        for p in (self.m13, self.m2):
            os.makedirs(p)
        self.cache = StationCache(os.path.join(self.dir, "cadastro_cache.json"))
        self.offsets = OffsetManager(os.path.join(self.dir, "offsets.json"))
        self.fila = OfflineQueue(os.path.join(self.dir, "offline_queue.jsonl"))

    def config(self, host, vinculos=None):
        return {
            "database": {"host": HOST, "port": 5432, "name": TESTE_DB, "user": USER,
                         "set_role": "mes_grp_client"},
            "cliente": {"host_id": host},
            "operation": {"mode": "database"},
            "spec_check": {"enabled": False},
            "vinculos": vinculos if vinculos is not None else [
                {"estacao": "caiapo-m13-ft", "fonte": "ft", "pasta": self.m13},   # minúsculas: normaliza
                {"estacao": "CAIAPO-M2-TAB", "fonte": "OCV", "pasta": self.m2},
            ],
        }

    def monitor(self, host, vinculos=None):
        cfg = self.config(host, vinculos)
        return fm.MonitorFontes(cfg, db=DBWriter(cfg), cache=self.cache, offsets=self.offsets, fila=self.fila)


def status(mon, chave):
    v = [x for x in mon.vinculos if x["chave"] == chave][0]
    return v["status"], v["detalhe"]


def contar(dono, fonte_codigo=None):
    if fonte_codigo:
        return um(dono, "select count(*) from mes_test_results r join mes_fontes f using (fonte_id) "
                        "where f.codigo = %s", (fonte_codigo,))[0]
    return um(dono, "select count(*) from mes_test_results")[0]


def cadastrar(adm):
    cur = adm.cursor()
    cur.execute("set mes.usuario_app = 'teste_f2'")
    cur.execute("insert into mes_plantas (codigo, nome, fuso) values ('MAO','Manaus','America/Manaus') returning planta_id")
    planta = cur.fetchone()[0]
    cur.execute("insert into mes_secoes (planta_id, codigo, nome) values (%s,'SECAO_04','Secao 04') returning secao_id", (planta,))
    sec = cur.fetchone()[0]
    cur.execute("insert into mes_linhas (secao_id, codigo, nome) values (%s,'CAIAPO','Caiapo') returning linha_id", (sec,))
    linha = cur.fetchone()[0]
    cur.execute("insert into mes_tipos_estacao (codigo, sigla, nome) values ('FUNCIONAL','FT','Teste Funcional') returning tipo_id")
    ft = cur.fetchone()[0]
    cur.execute("insert into mes_tipos_estacao (codigo, sigla, nome) values ('TAB_CUTTING','TAB','Tab Cutting') returning tipo_id")
    tab = cur.fetchone()[0]
    cur.execute("insert into mes_projetos (codigo, nome) values ('CAIAPO','Caiapo') returning projeto_id")
    proj = cur.fetchone()[0]
    cur.execute("insert into mes_modelos (projeto_id, codigo) values (%s,'A08') returning modelo_id", (proj,))
    a08 = cur.fetchone()[0]
    cur.execute("select formato_id from mes_formatos where codigo = 'P2500S'")
    p2500s = cur.fetchone()[0]
    cur.execute("insert into mes_formatos (codigo, tipo, definicao) values ('OCV_TABCUT','CONFIGURAVEL',%s) returning formato_id",
                (Json(OCV_DEF),))
    ocv = cur.fetchone()[0]
    cur.execute("insert into mes_estacoes (codigo, linha_id, tipo_id, maquina, modelo_atual_id) "
                "values ('CAIAPO-M13-FT',%s,%s,'M13',%s) returning station_pk", (linha, ft, a08))
    m13 = cur.fetchone()[0]
    cur.execute("insert into mes_estacoes (codigo, linha_id, tipo_id, maquina, modelo_atual_id) "
                "values ('CAIAPO-M2-TAB',%s,%s,'M2',%s) returning station_pk", (linha, tab, a08))
    m2 = cur.fetchone()[0]
    cur.execute("insert into mes_fontes (station_pk, codigo, formato_id, padrao_arquivo) values (%s,'FT',%s,'*_A08.csv') returning fonte_id", (m13, p2500s))
    f_ft = cur.fetchone()[0]
    cur.execute("insert into mes_fontes (station_pk, codigo, formato_id, padrao_arquivo) values (%s,'OCV',%s,'*CELL*.csv') returning fonte_id", (m2, ocv))
    f_ocv = cur.fetchone()[0]
    return {"m13": m13, "m2": m2, "ft": f_ft, "ocv": f_ocv, "linha": linha, "proj": proj, "tab": tab}


# -----------------------------------------------------------------------------
def teste_gravacao(dono, ids, a):
    print("\n[1] primeira rodada: vínculo automático e gravação das duas fontes")
    shutil.copy(M13_PEQ, a.m13)
    shutil.copy(M13_GDE, a.m13)
    shutil.copy(M2_OCV, a.m2)
    open(os.path.join(a.m13, "ignorar.txt"), "w").write("nao casa com o padrao")
    fonte_ft = {"formato_tipo": "DEDICADO", "formato_codigo": "P2500S"}
    fonte_ocv = {"formato_tipo": "CONFIGURAVEL", "formato_codigo": "OCV_TABCUT", "definicao": OCV_DEF}
    n_ft = esperado(M13_PEQ, fonte_ft) + esperado(M13_GDE, fonte_ft)
    n_ocv = esperado(M2_OCV, fonte_ocv)

    mon = a.monitor("PC-TESTE-A")
    cor = mon.ciclo()
    checar(cor == "green", "bandeja verde (cor=%s)" % cor)
    for chave in ("CAIAPO-M13-FT/FT", "CAIAPO-M2-TAB/OCV"):
        checar(status(mon, chave)[0] == fm.OK, "%s = OK (%s)" % (chave, status(mon, chave)))
    cur = dono.cursor()
    cur.execute("select codigo, host_vinculado from mes_estacoes order by codigo")
    hosts = dict(cur.fetchall())
    checar(hosts == {"CAIAPO-M13-FT": "PC-TESTE-A", "CAIAPO-M2-TAB": "PC-TESTE-A"}, "as 2 estações vinculadas ao PC-TESTE-A")
    checar(contar(dono, "FT") == n_ft, "FT: %d linhas gravadas (parser: %d)" % (contar(dono, "FT"), n_ft))
    checar(contar(dono, "OCV") == n_ocv, "OCV: %d linhas gravadas (parser: %d)" % (contar(dono, "OCV"), n_ocv))

    r = um(dono, """select model_name, serial_number, result_status,
                           r.test_start_time at time zone 'UTC', r.station_pk, r.linha_id, r.source_file
                      from mes_test_results r join mes_fontes f using (fonte_id)
                     where f.codigo='FT' and r.source_file='20260915_A08.csv' order by r.source_line_no limit 1""")
    checar(r[0] == "A08" and r[1] == "Y422622AB04860C385L" and r[2] == "PASS", "FT linha 1: A08 / serial / PASS")
    checar(str(r[3]) == "2026-09-15 10:03:23", "hora local 06:03:23 Manaus gravada como 10:03:23 UTC (%s)" % r[3])
    checar(r[4] == ids["m13"] and r[5] == ids["linha"], "station_pk e linha_id preenchidos pelo trigger")
    r = um(dono, "select count(distinct model_name), min(model_name) from mes_test_results r join mes_fontes f using (fonte_id) where f.codigo='OCV'")
    checar(r == (1, "A08"), "OCV: modelo A08 tirado do MODELNAME pela regex")
    r = um(dono, "select count(*) from mes_csv_schemas")[0]
    checar(r >= 2, "schemas registrados em mes_csv_schemas (%d)" % r)
    snap = runtime_status.snapshot()
    checar(snap["fontes"]["CAIAPO-M13-FT/FT"]["total_sessao"] == n_ft, "STATUS por fonte: total da sessão da FT")

    cur.execute("select state from pg_stat_activity where application_name = 'PC-TESTE-A' and datname = %s", (TESTE_DB,))
    estados = [x[0] for x in cur.fetchall()]
    checar(estados and all(e == "idle" for e in estados),
           "sessão do cliente 'idle', não 'idle in transaction' (pendência 21): %s" % estados)
    return mon, n_ft, n_ocv


def teste_incremental(dono, a, mon, n_ft):
    print("\n[2] rodadas seguintes: só linhas novas; releitura não duplica")
    mon.ciclo()
    checar(contar(dono, "FT") == n_ft, "segunda rodada sem arquivo novo: nada gravado")
    alvo = os.path.join(a.m13, os.path.basename(M13_GDE))
    linha = open(M13_GDE, encoding="utf-8").readlines()[1]
    with open(alvo, "a", encoding="utf-8", newline="") as f:
        f.write(linha + linha)
    mon.ciclo()
    checar(contar(dono, "FT") == n_ft + 2, "2 linhas anexadas → 2 gravadas (%d)" % (contar(dono, "FT") - n_ft))
    chaves = list(json.load(open(a.offsets.file, encoding="utf-8")))
    checar(all("|" in k and k.split("|")[0].isdigit() for k in chaves), "offsets com chave fonte_id|caminho")
    a.offsets._save({})                    # perde os offsets: relê tudo
    mon.ciclo()
    checar(contar(dono, "FT") == n_ft + 2, "offsets perdidos: relê tudo, ON CONFLICT descarta (sem duplicar)")
    return n_ft + 2


def teste_outro_pc(dono, raiz, total):
    print("\n[3] PC clonado/trocado: outro host não grava")
    b = Ambiente(raiz, "pc_b")
    shutil.copy(M13_PEQ, b.m13)
    mon_b = b.monitor("PC-TESTE-B")
    cor = mon_b.ciclo()
    st, det = status(mon_b, "CAIAPO-M13-FT/FT")
    checar(st == fm.OUTRO_PC and "PC-TESTE-A" in det, "status OUTRO PC citando o PC-TESTE-A")
    checar(cor == "red", "bandeja vermelha no PC-TESTE-B")
    checar(contar(dono) == total, "nada gravado pelo PC-TESTE-B")
    checar(um(dono, "select host_vinculado from mes_estacoes where codigo='CAIAPO-M13-FT'")[0] == "PC-TESTE-A",
           "vínculo continua no PC-TESTE-A")
    mon_b.db.close()


def teste_liberar_vinculo(dono, adm, a, mon, ids):
    print("\n[4] engenharia libera o vínculo: o PC não revincula sozinho")
    adm.cursor().execute("update mes_estacoes set host_vinculado=null, vinculado_em=null where station_pk=%s", (ids["m13"],))
    mon.atualizar_cadastro(forcar=True)
    checar(status(mon, "CAIAPO-M13-FT/FT")[0] == fm.LIBERADO, "status VÍNCULO LIBERADO")
    checar(um(dono, "select host_vinculado from mes_estacoes where station_pk=%s", (ids["m13"],))[0] is None,
           "estação continua sem PC")
    a.cache.desconfirmar(ids["m13"])                     # "Vincular de novo" na tela
    mon.atualizar_cadastro(forcar=True)
    checar(status(mon, "CAIAPO-M13-FT/FT")[0] == fm.OK, "depois de 'vincular de novo': OK")
    checar(um(dono, "select host_vinculado from mes_estacoes where station_pk=%s", (ids["m13"],))[0] == "PC-TESTE-A",
           "estação vinculada de novo ao PC-TESTE-A")


def teste_inativa(dono, adm, a, mon, ids, total):
    print("\n[5] fonte desativada no meio da produção: para, sem fila e sem perder linha")
    adm.cursor().execute("update mes_fontes set ativo=false where fonte_id=%s", (ids["ocv"],))
    alvo = os.path.join(a.m2, os.path.basename(M2_OCV))
    linha = open(M2_OCV, encoding="utf-8").readlines()[1]
    with open(alvo, "a", encoding="utf-8", newline="") as f:
        f.write(linha)
    fila_antes = a.fila.count()
    mon.ciclo()          # cadastro ainda em cache (10 min): o banco recusa no INSERT
    st, det = status(mon, "CAIAPO-M2-TAB/OCV")
    checar(st == fm.RECUSADA and "MS003" in det, "INSERT recusado pelo banco (MS003): %s" % det[:70])
    checar(a.fila.count() == fila_antes, "nada foi para a fila offline")
    mon.ciclo()          # relê o cadastro logo depois da recusa
    checar(status(mon, "CAIAPO-M2-TAB/OCV")[0] == fm.INATIVA, "na rodada seguinte: INATIVA (pelo cadastro)")
    checar(status(mon, "CAIAPO-M13-FT/FT")[0] == fm.OK, "a outra fonte do PC continua OK")
    adm.cursor().execute("update mes_fontes set ativo=true where fonte_id=%s", (ids["ocv"],))
    mon.atualizar_cadastro(forcar=True)
    mon.ciclo()
    checar(status(mon, "CAIAPO-M2-TAB/OCV")[0] == fm.OK, "reativada: OK")
    checar(contar(dono) == total + 1, "a linha anexada enquanto inativa entrou depois (nada perdido)")
    return total + 1


def teste_offline(dono, a, mon, total):
    print("\n[6] banco fora e queda no meio do lote")
    porta = mon.db.db["port"]
    mon.db.close()
    mon.db.db["port"] = 1                       # simula servidor fora
    mon.db.db["connect_timeout"] = 2
    alvo = os.path.join(a.m13, os.path.basename(M13_GDE))
    linha = open(M13_GDE, encoding="utf-8").readlines()[3]
    with open(alvo, "a", encoding="utf-8", newline="") as f:
        f.write(linha)
    for _ in range(3):
        cor = mon.ciclo()
    checar(cor == "red" and not mon.db_ok, "banco fora: bandeja vermelha")
    checar(a.fila.count() == 0, "banco fora: não lê e não empilha na fila (3 rodadas)")
    mon.db.db["port"] = porta
    mon.ciclo()
    checar(contar(dono) == total + 1 and mon.db_ok, "banco voltou: a linha pendente entrou")

    original = mon.db.insert_rows
    chamadas = {"n": 0}

    def cai_uma_vez(rows):
        chamadas["n"] += 1
        if chamadas["n"] == 1:
            raise ConnectionError("simulado: conexão caiu no meio do lote")
        return original(rows)
    mon.db.insert_rows = cai_uma_vez
    with open(alvo, "a", encoding="utf-8", newline="") as f:
        f.write(open(M13_GDE, encoding="utf-8").readlines()[4])
    mon.ciclo()
    checar(a.fila.count() == 1, "queda no meio do lote: 1 linha na fila offline")
    item = a.fila.peek_all()[0]
    checar(item.get("fonte_id") and item.get("fuso") == "America/Manaus", "item da fila leva fonte_id e fuso")
    a.fila.push_many([{"station_id": "PCM_A17_X", "source_file": "x.csv", "source_line_no": 1}])
    mon.ciclo()
    checar(a.fila.count() == 0, "reenvio esvaziou a fila (item antigo sem fonte_id descartado)")
    checar(contar(dono) == total + 2, "linha da fila gravada no banco")
    mon.db.insert_rows = original
    return total + 2


def teste_versoes(dono, adm, a, mon, ids):
    print("\n[7] schema, formato e versão do cliente")
    dono.cursor().execute("insert into mes_schema_version (versao, descricao) values (3, 'teste')")
    mon.atualizar_cadastro(forcar=True)
    checar(all(v["status"] == fm.SCHEMA for v in mon.vinculos), "schema v3 no banco: cliente para (SCHEMA INCOMPATÍVEL)")
    dono.cursor().execute("delete from mes_schema_version where versao = 3")
    mon.atualizar_cadastro(forcar=True)
    checar(all(v["status"] == fm.OK for v in mon.vinculos), "schema v2 de volta: OK")

    cur = adm.cursor()
    cur.execute("insert into mes_formatos (codigo, tipo, versao_min_cliente) values ('XPTO','DEDICADO','2.0.0') returning formato_id")
    xpto = cur.fetchone()[0]
    cur.execute("insert into mes_formatos (codigo, tipo, definicao, versao_min_cliente) values ('OCV_V9','CONFIGURAVEL',%s,'9.0.0') returning formato_id",
                (Json(OCV_DEF),))
    v9 = cur.fetchone()[0]
    cur.execute("insert into mes_fontes (station_pk, codigo, formato_id) values (%s,'AOI',%s)", (ids["m2"], xpto))
    cur.execute("insert into mes_fontes (station_pk, codigo, formato_id) values (%s,'EXTRA',%s)", (ids["m2"], v9))
    vinc = a.config("PC-TESTE-A")["vinculos"] + [
        {"estacao": "CAIAPO-M2-TAB", "fonte": "AOI", "pasta": a.m2},
        {"estacao": "CAIAPO-M2-TAB", "fonte": "EXTRA", "pasta": a.m2},
        {"estacao": "CAIAPO-M99-FT", "fonte": "FT", "pasta": a.m13},
        {"estacao": "SEM-FONTE"},
    ]
    mon2 = a.monitor("PC-TESTE-A", vinc)
    mon2.ciclo()
    checar(len(mon2.vinculos) == 5, "vínculo incompleto no config é ignorado (5 de 6)")
    checar(status(mon2, "CAIAPO-M2-TAB/AOI")[0] == fm.FORMATO, "formato dedicado desconhecido: FORMATO NÃO SUPORTADO")
    checar(status(mon2, "CAIAPO-M2-TAB/EXTRA")[0] == fm.ATUALIZAR, "versao_min_cliente 9.0.0: ATUALIZE O CLIENTE")
    checar(status(mon2, "CAIAPO-M99-FT/FT")[0] == fm.NAO_CADASTRADA, "estação inexistente: NÃO CADASTRADA")
    checar(status(mon2, "CAIAPO-M13-FT/FT")[0] == fm.OK, "as fontes boas continuam OK")
    mon2.db.close()


def teste_cache_sem_banco(raiz, a):
    print("\n[8] partida sem banco: usa o cadastro local")
    cfg = a.config("PC-TESTE-A")
    cfg["database"]["port"] = 1
    cfg["database"]["connect_timeout"] = 2
    mon = fm.MonitorFontes(cfg, db=DBWriter(cfg), cache=a.cache, offsets=a.offsets, fila=a.fila)
    mon.ciclo()
    checar(status(mon, "CAIAPO-M13-FT/FT")[0] == fm.SEM_BANCO, "vínculo já confirmado: OK (CACHE)")
    c = Ambiente(raiz, "pc_novo")
    cfg = c.config("PC-NOVO")
    cfg["database"]["port"] = 1
    cfg["database"]["connect_timeout"] = 2
    mon = fm.MonitorFontes(cfg, db=DBWriter(cfg), cache=c.cache, offsets=c.offsets, fila=c.fila)
    mon.ciclo()
    checar(status(mon, "CAIAPO-M13-FT/FT")[0] == fm.NAO_VINCULADA, "PC novo sem banco e sem cache: NÃO VINCULADA")


def main():
    inicio = time.time()
    base = conectar(BASE)
    base.cursor().execute('CREATE DATABASE "%s"' % TESTE_DB)
    print("banco descartável criado: %s" % TESTE_DB)
    raiz = tempfile.mkdtemp(prefix="mes_f2_")
    dono = adm = None
    mons = []
    try:
        dono = conectar(TESTE_DB)
        dono.cursor().execute(open(SQL_002, encoding="utf-8").read())
        adm = conectar(TESTE_DB, role="mes_grp_admin")
        ids = cadastrar(adm)
        a = Ambiente(raiz, "pc_a")
        mon, n_ft, n_ocv = teste_gravacao(dono, ids, a)
        mons.append(mon)
        total = teste_incremental(dono, a, mon, n_ft) + n_ocv
        teste_outro_pc(dono, raiz, total)
        teste_liberar_vinculo(dono, adm, a, mon, ids)
        total = teste_inativa(dono, adm, a, mon, ids, total)
        total = teste_offline(dono, a, mon, total)
        teste_versoes(dono, adm, a, mon, ids)
        teste_cache_sem_banco(raiz, a)
    except Exception as e:
        import traceback
        traceback.print_exc()
        falhas.append("erro inesperado: %r" % e)
    finally:
        for m in mons:
            if m.db:
                m.db.close()
        for c in (adm, dono):
            if c:
                c.close()
        base.cursor().execute('DROP DATABASE IF EXISTS "%s" WITH (FORCE)' % TESTE_DB)
        print("\nbanco descartável apagado: %s" % TESTE_DB)
        base.close()
        shutil.rmtree(raiz, ignore_errors=True)

    print("\n%d falha(s) em %.1fs" % (len(falhas), time.time() - inicio))
    for f in falhas:
        print("  - " + f)
    sys.exit(1 if falhas else 0)


if __name__ == "__main__":
    main()
