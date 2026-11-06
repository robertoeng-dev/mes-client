"""verificar_login.py — teste REAL de login nos bancos novos (fecha a F0).

A senha NAO e' passada por argumento nem por variavel: o libpq/psycopg2 le
automaticamente o arquivo padrao do PostgreSQL no Windows:
    %APPDATA%\\postgresql\\pgpass.conf     (linha: host:porta:banco:usuario:senha)

Testa, com o role mes_homolog:
  1. login no mes_nonalpha_homolog (deve funcionar) e versao/fuso da sessao;
  2. login no mes_nonalpha e no mes_alpha (devem ser RECUSADOS: segregacao);
  3. SET ROLE para cada grupo dentro do homolog (usado pelos testes da F1).
Nao cria nem altera nada.
"""
import sys

import psycopg2

HOST = "172.21.70.184"
falhas = 0


def ok(cond, msg):
    global falhas
    print(("  OK    " if cond else "  FALHA ") + msg)
    if not cond:
        falhas += 1


def conectar(db, user="mes_homolog"):
    return psycopg2.connect(host=HOST, port=5432, dbname=db, user=user, connect_timeout=8,
                            application_name="verificar_login", sslmode="prefer")


print("== mes_homolog -> mes_nonalpha_homolog")
try:
    c = conectar("mes_nonalpha_homolog")
    cur = c.cursor()
    cur.execute("select current_user, current_database(), current_setting('TimeZone'), "
                "current_setting('idle_in_transaction_session_timeout'), "
                "(select ssl from pg_stat_ssl where pid = pg_backend_pid())")
    u, d, tz, idle, ssl = cur.fetchone()
    ok(u == "mes_homolog" and d == "mes_nonalpha_homolog", f"login OK como {u} em {d}")
    ok(tz == "UTC", f"fuso da sessao = {tz}")
    ok(idle == "5min", f"idle_in_transaction_session_timeout = {idle}")
    print(f"        conexao com SSL: {ssl}")
    for grupo in ("mes_grp_admin", "mes_grp_client", "mes_grp_leitura"):
        try:
            cur.execute(f"SET ROLE {grupo}")
            cur.execute("select current_user")
            ok(cur.fetchone()[0] == grupo, f"SET ROLE {grupo}")
            cur.execute("RESET ROLE")
        except Exception as e:
            c.rollback()
            ok(False, f"SET ROLE {grupo}: {str(e).strip()}")
    c.close()
except psycopg2.OperationalError as e:
    msg = str(e).strip().splitlines()[0]
    ok(False, f"login falhou: {msg}")
    if "no password supplied" in msg or "password authentication failed" in msg:
        print("        -> confira a linha do mes_homolog em %APPDATA%\\postgresql\\pgpass.conf")

for db in ("mes_nonalpha", "mes_alpha"):
    print(f"== mes_homolog -> {db} (deve ser recusado)")
    try:
        conectar(db).close()
        ok(False, f"conectou em {db} — segregacao QUEBRADA")
    except psycopg2.OperationalError as e:
        msg = str(e).strip().splitlines()[0]
        ok("permission denied" in msg or "not have CONNECT" in msg, f"recusado: {msg}")

# mes_db (antigo) nao foi alterado: o CONNECT dele continua liberado para PUBLIC
# (padrao do PostgreSQL). Informativo — conectar nao da' acesso as tabelas, que
# sao do mes_user sem GRANT para PUBLIC. Fechar isso exige mexer no mes_db.
print("== mes_homolog -> mes_db (informativo)")
try:
    c = conectar("mes_db")
    cur = c.cursor()
    try:
        cur.execute("select count(*) from mes_test_results")
        print(f"  AVISO conecta E LE mes_test_results ({cur.fetchone()[0]} linhas) — revisar privilegios do mes_db")
        falhas += 1
    except psycopg2.Error as e:
        print(f"  AVISO conecta no mes_db, mas nao le tabelas ({str(e).strip().splitlines()[0]})")
    c.close()
except psycopg2.OperationalError as e:
    print(f"  OK    recusado: {str(e).strip().splitlines()[0]}")

print(f"\n{'TUDO OK' if falhas == 0 else str(falhas) + ' FALHA(S)'}")
sys.exit(0 if falhas == 0 else 1)
