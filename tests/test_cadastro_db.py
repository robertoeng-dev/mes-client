# =============================================================================
# test_cadastro_db.py — testes do 002_cadastro.sql contra o PostgreSQL real
# =============================================================================
# Roda sem pytest:
#   .venv\Scripts\python.exe tests\test_cadastro_db.py
#
# Conecta como mes_homolog (senha lida do %APPDATA%\postgresql\pgpass.conf),
# cria um banco DESCARTAVEL (mes_teste_cad_<pid>), aplica o 002 duas vezes,
# testa e apaga o banco no final — mesmo se algum teste falhar.
# Os papeis sao exercitados com SET ROLE nos grupos reais:
#   mes_grp_admin (app web) / mes_grp_client (estacao) / mes_grp_leitura.
# =============================================================================

import os
import sys
import time

import psycopg2
import psycopg2.errors
from psycopg2.extras import Json

HOST = os.environ.get("MES_TEST_HOST", "172.21.70.184")
USER = "mes_homolog"
BASE = "mes_nonalpha_homolog"
SQL_002 = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "database", "002_cadastro.sql")
TESTE_DB = f"mes_teste_cad_{os.getpid()}"

falhas = []


def checar(condicao, descricao):
    print(f"   {'ok   ' if condicao else 'FALHA'} {descricao}")
    if not condicao:
        falhas.append(descricao)


def conectar(db, app="teste_cadastro", role=None, autocommit=True):
    c = psycopg2.connect(host=HOST, port=5432, dbname=db, user=USER,
                         application_name=app, connect_timeout=10)
    c.autocommit = autocommit
    if role:
        c.cursor().execute(f"SET ROLE {role}")
    return c


def erro(conn, sql, args=None):
    """Executa esperando erro; devolve (sqlstate, mensagem) ou None se nao falhou."""
    cur = conn.cursor()
    try:
        cur.execute(sql, args)
        if not conn.autocommit:
            conn.commit()
        return None
    except psycopg2.Error as e:
        if not conn.autocommit:
            conn.rollback()
        return (e.pgcode, (e.diag.message_primary or str(e)).strip())


def um(conn, sql, args=None):
    cur = conn.cursor()
    cur.execute(sql, args)
    return cur.fetchone()


# -----------------------------------------------------------------------------
def teste_aplicacao(dono):
    print("\n[1] aplicar o 002 duas vezes (idempotencia)")
    sql = open(SQL_002, encoding="utf-8").read()
    for vez in (1, 2):
        try:
            dono.cursor().execute(sql)
            checar(True, f"aplicacao {vez} sem erro")
        except psycopg2.Error as e:
            checar(False, f"aplicacao {vez}: {e}")
            raise
    checar(um(dono, "select max(versao) from mes_schema_version")[0] == 2, "schema_version = 2")
    n = um(dono, "select count(*) from mes_formatos where tipo='DEDICADO'")[0]
    checar(n == 3, f"3 formatos dedicados semeados uma vez so (achou {n})")


def teste_codigos(adm):
    print("\n[2] codigos: so' MAIUSCULAS, sem acento/espaco")
    for ruim in ("mao", "Mao", "MAÔ", "MA O", "-MAO", "MAO-", "MAO__X", "", "A" * 41):
        r = erro(adm, "insert into mes_plantas (codigo, nome) values (%s, 'x')", (ruim,))
        checar(r is not None and r[0] == "23514", f"recusa codigo {ruim!r}")
    for bom in ("MAO", "SECAO_04", "CAIAPO-M13-FT", "A08"):
        r = erro(adm, "insert into mes_projetos (codigo, nome) values (%s, 'teste')", (bom,))
        checar(r is None, f"aceita codigo {bom!r}")
    adm.cursor().execute("delete from mes_projetos")
    r = erro(adm, "insert into mes_plantas (codigo, nome, fuso) values ('XYZ', 'x', 'Manaus/Errado')")
    checar(r is not None and "Fuso" in r[1], "recusa fuso invalido")
    r = erro(adm, "insert into mes_plantas (codigo, nome) values ('DUP', ' ')")
    checar(r is not None, "recusa nome em branco")


def montar_cadastro(adm):
    """Cadastro de exemplo: MAO / SECAO_04 / CAIAPO / CAIAPO-M13-FT (fonte FT)
    e CAIAPO-M2-TAB (fontes OCV e AOI)."""
    cur = adm.cursor()
    cur.execute("set mes.usuario_app = 'teste_robo'")
    cur.execute("insert into mes_plantas (codigo, nome) values ('MAO', 'Manaus') returning planta_id")
    planta = cur.fetchone()[0]
    cur.execute("insert into mes_secoes (planta_id, codigo, nome) values (%s, 'SECAO_04', 'Secao 04') returning secao_id", (planta,))
    sec4 = cur.fetchone()[0]
    cur.execute("insert into mes_secoes (planta_id, codigo, nome) values (%s, 'SECAO_05', 'Secao 05') returning secao_id", (planta,))
    sec5 = cur.fetchone()[0]
    cur.execute("insert into mes_linhas (secao_id, codigo, nome) values (%s, 'CAIAPO', 'Caiapo') returning linha_id", (sec4,))
    caiapo = cur.fetchone()[0]
    cur.execute("insert into mes_linhas (secao_id, codigo, nome) values (%s, 'TARUMA', 'Taruma') returning linha_id", (sec5,))
    taruma = cur.fetchone()[0]
    cur.execute("insert into mes_tipos_estacao (codigo, sigla, nome) values ('FUNCIONAL','FT','Teste Funcional'), ('TAB_CUTTING','TAB','Tab Cutting')")
    cur.execute("insert into mes_projetos (codigo, nome) values ('PROJ_X', 'Projeto X') returning projeto_id")
    proj = cur.fetchone()[0]
    cur.execute("insert into mes_modelos (projeto_id, codigo) values (%s, 'A08') returning modelo_id", (proj,))
    a08 = cur.fetchone()[0]
    cur.execute("""insert into mes_formatos (codigo, tipo, definicao) values
                   ('OCV_TABCUT', 'CONFIGURAVEL', %s) returning formato_id""",
                (Json({"delimitador": ",", "linha_cabecalho": 1, "colunas": {"serial_number": "BARCODE.1"}}),))
    ocv_fmt = cur.fetchone()[0]
    p2500 = um(adm, "select formato_id from mes_formatos where codigo='P2500S'")[0]
    cur.execute("""insert into mes_estacoes (codigo, linha_id, tipo_id, maquina, modelo_atual_id)
                   select 'CAIAPO-M13-FT', %s, tipo_id, 'M13', %s from mes_tipos_estacao where codigo='FUNCIONAL'
                   returning station_pk""", (caiapo, a08))
    m13 = cur.fetchone()[0]
    cur.execute("""insert into mes_estacoes (codigo, linha_id, tipo_id, maquina)
                   select 'CAIAPO-M2-TAB', %s, tipo_id, 'M2' from mes_tipos_estacao where codigo='TAB_CUTTING'
                   returning station_pk""", (caiapo,))
    m2 = cur.fetchone()[0]
    cur.execute("insert into mes_fontes (station_pk, codigo, formato_id) values (%s, 'FT', %s) returning fonte_id", (m13, p2500))
    f_ft = cur.fetchone()[0]
    cur.execute("insert into mes_fontes (station_pk, codigo, formato_id) values (%s, 'OCV', %s) returning fonte_id", (m2, ocv_fmt))
    f_ocv = cur.fetchone()[0]
    cur.execute("""insert into mes_fontes (station_pk, codigo, formato_id, anexos) values
                   (%s, 'AOI', %s, %s) returning fonte_id""",
                (m2, ocv_fmt, Json({"padrao": "*.jpg", "so_ng": True, "destino": r"\\srv\aoi"})))
    f_aoi = cur.fetchone()[0]
    return dict(planta=planta, sec4=sec4, sec5=sec5, caiapo=caiapo, taruma=taruma, m13=m13, m2=m2,
                f_ft=f_ft, f_ocv=f_ocv, f_aoi=f_aoi, a08=a08)


def teste_unicidade(adm, ids):
    print("\n[3] unicidade e hierarquia")
    r = erro(adm, "insert into mes_linhas (secao_id, codigo, nome) values (%s, 'CAIAPO', 'dup')", (ids["sec5"],))
    checar(r is not None and r[0] == "23505", "linha com mesmo codigo na mesma planta (outra secao) recusada")
    planta_linha = um(adm, "select planta_id from mes_linhas where linha_id=%s", (ids["caiapo"],))[0]
    checar(planta_linha == ids["planta"], "planta_id da linha preenchido pelo trigger")
    r = erro(adm, """insert into mes_estacoes (codigo, linha_id, tipo_id, maquina)
                     select 'OUTRO-CODIGO', %s, tipo_id, 'M13' from mes_tipos_estacao where codigo='FUNCIONAL'""",
             (ids["caiapo"],))
    checar(r is not None and r[0] == "23505", "mesma maquina+tipo na mesma linha com outro codigo recusada")
    r = erro(adm, "insert into mes_fontes (station_pk, codigo, formato_id) select %s, 'OCV', formato_id from mes_formatos where codigo='CYG'", (ids["m2"],))
    checar(r is not None and r[0] == "23505", "fonte duplicada na mesma estacao recusada")
    r = erro(adm, "insert into mes_formatos (codigo, tipo) values ('VAZIO', 'CONFIGURAVEL')")
    checar(r is not None and r[0] == "23514", "formato CONFIGURAVEL sem definicao recusado")
    # outra planta pode ter uma linha CAIAPO
    cur = adm.cursor()
    cur.execute("insert into mes_plantas (codigo, nome, fuso) values ('XYZ', 'Planta Asia', 'Asia/Kolkata') returning planta_id")
    p2 = cur.fetchone()[0]
    cur.execute("insert into mes_secoes (planta_id, codigo, nome) values (%s, 'SECAO_04', 's') returning secao_id", (p2,))
    s2 = cur.fetchone()[0]
    r = erro(adm, "insert into mes_linhas (secao_id, codigo, nome) values (%s, 'CAIAPO', 'outra planta')", (s2,))
    checar(r is None, "outra planta aceita linha com o mesmo codigo")
    r = erro(adm, "update mes_linhas set secao_id=%s where linha_id=%s", (s2, ids["taruma"]))
    checar(r is not None and "planta" in r[1], "linha nao muda de planta")
    r = erro(adm, "update mes_secoes set planta_id=%s where secao_id=%s", (p2, ids["sec5"]))
    checar(r is not None and "planta" in r[1], "secao nao muda de planta")


def teste_permissoes(dono, ids):
    print("\n[4] permissoes por grupo")
    cli = conectar(TESTE_DB, app="PC-M13", role="mes_grp_client")
    n = um(cli, "select count(*) from v_cadastro_fontes")[0]
    checar(n == 3, f"cliente le o catalogo (v_cadastro_fontes = {n} fontes)")
    for sql in ("insert into mes_plantas (codigo, nome) values ('HACK', 'x')",
                "update mes_linhas set nome='x'",
                "delete from mes_fontes",
                "update mes_estacoes set host_vinculado='PC-M13'",
                "select count(*) from mes_test_results",
                "select count(*) from mes_cadastro_log"):
        r = erro(cli, sql)
        checar(r is not None and r[0] == "42501", f"cliente NAO pode: {sql[:55]}")
    cli.close()

    lei = conectar(TESTE_DB, role="mes_grp_leitura")
    checar(um(lei, "select count(*) from v_mes_test_results")[0] >= 0, "leitura le v_mes_test_results")
    r = erro(lei, "insert into mes_plantas (codigo, nome) values ('HACK', 'x')")
    checar(r is not None and r[0] == "42501", "leitura NAO escreve no catalogo")
    r = erro(lei, "insert into mes_test_results (fonte_id, source_file, source_line_no) values (%s, 'a', 1)", (ids["f_ft"],))
    checar(r is not None and r[0] == "42501", "leitura NAO grava resultado")
    lei.close()

    adm = conectar(TESTE_DB, role="mes_grp_admin")
    r = erro(adm, "insert into mes_test_results (fonte_id, source_file, source_line_no) values (%s, 'a', 1)", (ids["f_ft"],))
    checar(r is not None and r[0] == "42501", "app web NAO grava resultado")
    r = erro(adm, "delete from mes_cadastro_log")
    checar(r is not None and r[0] == "42501", "app web NAO apaga a auditoria")
    adm.close()


def inserir_resultado(conn, fonte, linha_no, serial="S1", res="PASS", arquivo="20261105_A08.csv"):
    cur = conn.cursor()
    cur.execute("""insert into mes_test_results (fonte_id, model_name, serial_number, result_status,
                   test_start_time, source_file, source_line_no, row_data)
                   values (%s, 'A08', %s, %s, '2026-11-05 10:00:00+00', %s, %s, %s)
                   on conflict do nothing""",
                (fonte, serial, res, arquivo, linha_no, Json({"BARCODE.1": serial})))
    return cur.rowcount


def teste_vinculo_e_gravacao(ids):
    print("\n[5] vinculo da estacao ao PC e gravacao")
    m13 = conectar(TESTE_DB, app="PC-M13", role="mes_grp_client")
    r = erro(m13, "select 1")  # aquece
    r = erro(m13, "insert into mes_test_results (fonte_id, source_file, source_line_no) values (%s, 'a', 1)", (ids["f_ft"],))
    checar(r is not None and r[0] == "MS004", "estacao nao vinculada: gravacao recusada (MS004)")

    pk = um(m13, "select mes_vincular_estacao('caiapo-m13-ft ')")[0]
    checar(pk == ids["m13"], "vincular (codigo em minusculas/espaco e' normalizado) devolve o station_pk")
    pk2 = um(m13, "select mes_vincular_estacao('CAIAPO-M13-FT')")[0]
    checar(pk2 == ids["m13"], "vincular de novo do mesmo PC: OK (idempotente)")
    host = um(m13, "select host_vinculado from mes_estacoes where station_pk=%s", (ids["m13"],))[0]
    checar(host == "PC-M13", f"host_vinculado = {host}")

    clone = conectar(TESTE_DB, app="PC-CLONADO", role="mes_grp_client")
    r = erro(clone, "select mes_vincular_estacao('CAIAPO-M13-FT')")
    checar(r is not None and r[0] == "MS013" and "PC-M13" in r[1], "outro PC nao consegue vincular (MS013)")
    r = erro(clone, "insert into mes_test_results (fonte_id, source_file, source_line_no) values (%s, 'a', 1)", (ids["f_ft"],))
    checar(r is not None and r[0] == "MS005", "PC clonado: gravacao recusada (MS005)")
    r = erro(clone, "select mes_vincular_estacao('NAO-EXISTE')")
    checar(r is not None and r[0] == "MS011", "estacao inexistente (MS011)")
    clone.close()

    n = inserir_resultado(m13, ids["f_ft"], 1)
    checar(n == 1, "PC vinculado grava resultado")
    n = inserir_resultado(m13, ids["f_ft"], 1)
    checar(n == 0, "mesma linha de novo: ignorada (ON CONFLICT DO NOTHING)")
    r = erro(m13, """insert into mes_test_results (fonte_id, station_pk, source_file, source_line_no)
                     values (%s, %s, 'x', 9)""", (ids["f_ft"], ids["m2"]))
    checar(r is not None and r[0] == "42501", "cliente NAO consegue informar station_pk (column grant)")
    r = erro(m13, "insert into mes_test_results (fonte_id, source_file, source_line_no) values (%s, 'x', 9)", (ids["f_ocv"],))
    checar(r is not None and r[0] == "MS004", "PC da M13 nao grava na fonte da M2 (nao vinculada)")

    # schema do CSV e divergencias de spec, como o cliente faz hoje
    cur = m13.cursor()
    for _ in range(2):
        cur.execute("""insert into mes_csv_schemas (schema_hash, model_name, columns_json) values ('h1','A08', '["a"]')
                       on conflict (schema_hash) do update set last_seen = now(), model_name = excluded.model_name""")
    checar(True, "cliente faz upsert em mes_csv_schemas")
    cur.execute("insert into mes_spec_mismatches (fonte_id, step_key) values (%s, 'OCV')", (ids["f_ft"],))
    checar(True, "cliente grava mes_spec_mismatches")
    m13.close()
    return True


def teste_retrato_e_inativacao(dono, ids):
    print("\n[6] retrato da linha, inativacao, codigo imutavel, FK")
    adm = conectar(TESTE_DB, role="mes_grp_admin")
    m13 = conectar(TESTE_DB, app="PC-M13", role="mes_grp_client")
    # estacao muda de linha: historico fica na linha antiga
    adm.cursor().execute("update mes_estacoes set linha_id=%s where station_pk=%s", (ids["taruma"], ids["m13"]))
    inserir_resultado(m13, ids["f_ft"], 2)
    adm.cursor().execute("update mes_estacoes set linha_id=%s where station_pk=%s", (ids["caiapo"], ids["m13"]))
    linhas = dict(um(dono, """select jsonb_object_agg(source_line_no, linha_id) from mes_test_results
                              where fonte_id=%s""", (ids["f_ft"],))[0])
    checar(linhas.get("1") == ids["caiapo"] and linhas.get("2") == ids["taruma"],
           f"retrato da linha por teste ({linhas})")

    r = erro(adm, "update mes_estacoes set codigo='CAIAPO-M13-XX' where station_pk=%s", (ids["m13"],))
    checar(r is not None and "em uso" in r[1], "codigo de estacao com testes nao muda")
    r = erro(adm, "update mes_estacoes set descricao='ok' where station_pk=%s", (ids["m13"],))
    checar(r is None, "descricao da estacao pode mudar")
    r = erro(adm, "update mes_linhas set codigo='CAIAPO2' where linha_id=%s", (ids["caiapo"],))
    checar(r is not None and "em uso" in r[1], "codigo de linha em uso nao muda")
    r = erro(adm, "update mes_linhas set nome='Caiapo (renomeada)' where linha_id=%s", (ids["caiapo"],))
    checar(r is None, "nome da linha pode mudar")
    r = erro(adm, "update mes_modelos set codigo='A08X' where modelo_id=%s", (ids["a08"],))
    checar(r is not None and "em uso" in r[1], "codigo de modelo em uso nao muda")
    cur = adm.cursor()
    cur.execute("insert into mes_projetos (codigo, nome) values ('LIVRE', 'sem uso') returning projeto_id")
    livre = cur.fetchone()[0]
    r = erro(adm, "update mes_projetos set codigo='LIVRE2' where projeto_id=%s", (livre,))
    checar(r is None, "codigo ainda sem uso pode ser corrigido")
    r = erro(adm, "delete from mes_linhas where linha_id=%s", (ids["caiapo"],))
    checar(r is not None and r[0] in ("23001", "23503"), "linha em uso nao pode ser apagada (FK RESTRICT)")
    r = erro(adm, "delete from mes_projetos where projeto_id=%s", (livre,))
    checar(r is None, "item sem uso pode ser apagado")

    adm.cursor().execute("update mes_fontes set ativo=false where fonte_id=%s", (ids["f_ft"],))
    r = erro(m13, "insert into mes_test_results (fonte_id, source_file, source_line_no) values (%s, 'z', 1)", (ids["f_ft"],))
    checar(r is not None and r[0] == "MS003", "fonte inativa: gravacao recusada (MS003)")
    adm.cursor().execute("update mes_fontes set ativo=true where fonte_id=%s", (ids["f_ft"],))
    adm.cursor().execute("update mes_estacoes set ativo=false where station_pk=%s", (ids["m13"],))
    r = erro(m13, "insert into mes_test_results (fonte_id, source_file, source_line_no) values (%s, 'z', 1)", (ids["f_ft"],))
    checar(r is not None and r[0] == "MS002", "estacao inativa: gravacao recusada (MS002)")
    adm.cursor().execute("update mes_estacoes set ativo=true where station_pk=%s", (ids["m13"],))

    # liberar vinculo (troca de PC) pelo app web
    adm.cursor().execute("update mes_estacoes set host_vinculado=null, vinculado_em=null where station_pk=%s", (ids["m13"],))
    novo = conectar(TESTE_DB, app="PC-M13-NOVO", role="mes_grp_client")
    checar(um(novo, "select mes_vincular_estacao('CAIAPO-M13-FT')")[0] == ids["m13"], "depois de liberar, o PC novo vincula")
    r = erro(m13, "insert into mes_test_results (fonte_id, source_file, source_line_no) values (%s, 'z', 1)", (ids["f_ft"],))
    checar(r is not None and r[0] == "MS005", "PC antigo deixa de gravar")
    novo.close(); m13.close(); adm.close()


def teste_auditoria_e_views(dono, ids):
    print("\n[7] auditoria e views")
    n, app = um(dono, """select count(*), max(usuario_app) from mes_cadastro_log
                         where tabela='mes_plantas' and operacao='INSERT' and chave=%s""", (str(ids["planta"]),))
    checar(n == 1 and app == "teste_robo", f"INSERT auditado com usuario do app ({app})")
    n = um(dono, "select count(*) from mes_cadastro_log where tabela='mes_estacoes' and operacao='UPDATE'")[0]
    checar(n >= 5, f"UPDATEs de estacao auditados ({n})")
    vin = um(dono, """select usuario_db from mes_cadastro_log where tabela='mes_estacoes'
                      and depois->>'host_vinculado' = 'PC-M13' order by id limit 1""")
    checar(vin is not None and vin[0] == USER, "vinculo feito pelo cliente aparece na auditoria")
    linha = um(dono, """select planta, secao, linha, estacao, tipo, fonte, projeto,
                               to_char(test_start_local, 'HH24:MI') from v_mes_test_results where source_line_no=1""")
    checar(linha == ("MAO", "SECAO_04", "CAIAPO", "CAIAPO-M13-FT", "FT", "FT", "PROJ_X", "06:00"),
           f"v_mes_test_results com hierarquia e hora local de Manaus ({linha})")
    n = um(dono, "select count(*) from v_rastreabilidade_serial where serial_number='S1'")[0]
    checar(n == 2, f"rastreabilidade do serial S1 ({n} testes)")
    at = um(dono, "select testes_24h from v_atividade_fontes where fonte_id=%s", (ids["f_ft"],))[0]
    checar(at == 2, f"atividade: {at} testes nas ultimas 24h na fonte FT")


# -----------------------------------------------------------------------------
def main():
    inicio = time.time()
    base = conectar(BASE)
    base.cursor().execute(f'CREATE DATABASE "{TESTE_DB}"')
    print(f"banco descartavel criado: {TESTE_DB}")
    dono = None
    try:
        dono = conectar(TESTE_DB)
        teste_aplicacao(dono)
        adm = conectar(TESTE_DB, role="mes_grp_admin")
        teste_codigos(adm)
        ids = montar_cadastro(adm)
        adm_ok = True
        teste_unicidade(adm, ids)
        adm.close()
        teste_permissoes(dono, ids)
        teste_vinculo_e_gravacao(ids)
        teste_retrato_e_inativacao(dono, ids)
        teste_auditoria_e_views(dono, ids)
    except Exception as e:
        falhas.append(f"erro inesperado: {e!r}")
        print(f"\n   ERRO INESPERADO: {e!r}")
    finally:
        if dono:
            dono.close()
        base.cursor().execute(f'DROP DATABASE IF EXISTS "{TESTE_DB}" WITH (FORCE)')
        print(f"\nbanco descartavel apagado: {TESTE_DB}")
        base.close()

    print(f"\n{len(falhas)} falha(s) em {time.time() - inicio:.1f}s")
    for f in falhas:
        print(f"  - {f}")
    sys.exit(1 if falhas else 0)


if __name__ == "__main__":
    main()
