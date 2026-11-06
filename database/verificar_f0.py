"""verificar_f0.py — confere, SOMENTE LEITURA, se o 000_roles_bancos.sql foi aplicado.

Uso (do notebook):
    set MES_VERIFY_USER=mes_user
    set MES_VERIFY_PASSWORD=...        (ou --env C:\\Utility\\MES\\.env)
    python verificar_f0.py [--host 172.21.70.184] [--env caminho\\.env]

Qualquer role de login serve: pg_roles, pg_database e has_database_privilege()
sao visiveis a todos. Sai com codigo 0 se tudo OK, 1 se algo falhou.
"""
import argparse
import os
import sys

import psycopg2

ROLES = {
    # nome: (login, createdb)
    "mes_owner_nonalpha": (False, False), "mes_owner_alpha": (False, False),
    "mes_grp_admin": (False, False), "mes_grp_client": (False, False), "mes_grp_leitura": (False, False),
    "mes_web": (True, False), "mes_web_nonalpha": (True, False), "mes_web_alpha": (True, False),
    "mes_client_nonalpha": (True, False), "mes_client_alpha": (True, False),
    "mes_leitura_nonalpha": (True, False), "mes_leitura_alpha": (True, False),
    "mes_homolog": (True, True),
}
BANCOS = {
    "mes_nonalpha": "mes_owner_nonalpha", "mes_alpha": "mes_owner_alpha",
    "mes_nonalpha_homolog": "mes_homolog", "mes_cadastro_app": "mes_web",
}
# (role, banco, deve_conectar)
CONNECT = [
    ("mes_client_nonalpha", "mes_nonalpha", True), ("mes_client_nonalpha", "mes_alpha", False),
    ("mes_client_alpha", "mes_alpha", True), ("mes_client_alpha", "mes_nonalpha", False),
    ("mes_web_nonalpha", "mes_nonalpha", True), ("mes_web_nonalpha", "mes_alpha", False),
    ("mes_web_alpha", "mes_alpha", True), ("mes_web_alpha", "mes_nonalpha", False),
    ("mes_leitura_nonalpha", "mes_alpha", False), ("mes_leitura_alpha", "mes_nonalpha", False),
    ("mes_homolog", "mes_nonalpha_homolog", True),
    ("mes_homolog", "mes_nonalpha", False), ("mes_homolog", "mes_alpha", False),
    ("mes_web", "mes_cadastro_app", True), ("mes_web", "mes_nonalpha", False),
    ("mes_client_nonalpha", "mes_cadastro_app", False),
    ("mes_user", "mes_nonalpha", False), ("mes_user", "mes_alpha", False),
]


def senha_do_env(path):
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            if line.startswith("MES_DB_PASSWORD="):
                return line.split("=", 1)[1].strip()
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="172.21.70.184")
    ap.add_argument("--env", help=".env com MES_DB_PASSWORD (usuario mes_user)")
    a = ap.parse_args()
    user = os.environ.get("MES_VERIFY_USER", "mes_user")
    pw = os.environ.get("MES_VERIFY_PASSWORD") or (senha_do_env(a.env) if a.env else None)
    if not pw:
        sys.exit("informe MES_VERIFY_PASSWORD ou --env")

    c = psycopg2.connect(host=a.host, port=5432, dbname="postgres", user=user, password=pw,
                         connect_timeout=8, application_name="verificar_f0_readonly",
                         options="-c default_transaction_read_only=on")
    cur = c.cursor()
    falhas = 0

    def ok(cond, msg):
        nonlocal falhas
        print(("  OK    " if cond else "  FALHA ") + msg)
        if not cond:
            falhas += 1

    print("\n== Roles")
    cur.execute("select rolname, rolcanlogin, rolcreatedb, rolsuper, rolcreaterole from pg_roles")
    roles = {r[0]: r[1:] for r in cur.fetchall()}
    for nome, (login, createdb) in ROLES.items():
        if nome not in roles:
            ok(False, f"{nome} nao existe")
            continue
        rl, rc, rs, rcr = roles[nome]
        ok(rl == login and rc == createdb and not rs and not rcr,
           f"{nome}: login={rl} createdb={rc} super={rs} createrole={rcr}")

    print("\n== Bancos")
    cur.execute("select datname, pg_get_userbyid(datdba), pg_encoding_to_char(encoding) from pg_database")
    dbs = {r[0]: r[1:] for r in cur.fetchall()}
    for nome, dono in BANCOS.items():
        ok(nome in dbs and dbs[nome][0] == dono and dbs[nome][1] == "UTF8",
           f"{nome}: {dbs.get(nome, ('ausente',))}")
    ok("mes_db" in dbs, "mes_db continua existindo (arquivo, intocado)")

    print("\n== Segregacao (CONNECT)")
    for role, banco, deve in CONNECT:
        if role not in roles or banco not in dbs:
            ok(False, f"{role} -> {banco}: role ou banco ausente")
            continue
        cur.execute("select has_database_privilege(%s, %s, 'CONNECT')", (role, banco))
        tem = cur.fetchone()[0]
        ok(tem == deve, f"{role} -> {banco}: conecta={tem} (esperado {deve})")

    print("\n== Grupos")
    cur.execute("""select g.rolname, m.rolname from pg_auth_members am
                   join pg_roles g on g.oid = am.roleid join pg_roles m on m.oid = am.member""")
    membros = set(cur.fetchall())
    for g, m in [("mes_grp_admin", "mes_web_nonalpha"), ("mes_grp_admin", "mes_web_alpha"),
                 ("mes_grp_client", "mes_client_nonalpha"), ("mes_grp_client", "mes_client_alpha"),
                 ("mes_grp_leitura", "mes_leitura_nonalpha"), ("mes_grp_leitura", "mes_leitura_alpha"),
                 ("mes_grp_client", "mes_homolog")]:
        ok((g, m) in membros, f"{m} em {g}")

    print("\n== Senhas definidas (rolpassword nao e' legivel; checa pelo pg_hba depois)")
    print("        teste real de login fica para a F1, com a senha do mes_homolog")

    c.close()
    print(f"\n{'TUDO OK' if falhas == 0 else str(falhas) + ' FALHA(S)'}")
    sys.exit(0 if falhas == 0 else 1)


if __name__ == "__main__":
    main()
