# =============================================================================
# test_wizard_helper_203.py — modo --wizard do cliente (2.0.3) contra o banco
# =============================================================================
#   .venv\Scripts\python.exe tests\test_wizard_helper_203.py
#   (opcional) MES_EXE_TESTE=dist\MES_Client.exe  -> roda também pelo exe
#
# Banco DESCARTÁVEL (mes_teste_wiz_<pid>) como no test_cliente_f2: aplica o
# 002, cadastra M13 (FT) e M2 (TAB/OCV) e chama o modo do instalador como o
# wizard chama (processo separado, entrada em arquivo, saída em arquivo).
# O nome do PC vem de COMPUTERNAME, fixado em cada chamada.
# =============================================================================

import os
import subprocess
import sys
import tempfile
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "tests"))

import test_cliente_f2 as base                        # noqa: E402  (cadastrar, conectar)
from system import wizard_helper as wh                # noqa: E402

TESTE_DB = "mes_teste_wiz_%d" % os.getpid()
EXE = os.environ.get("MES_EXE_TESTE")
SENHA_ERRADA = "senha-errada-de-teste"   # de proposito: o servidor tem que recusar
falhas = []


def checar(cond, msg):
    print("   %s %s" % ("ok   " if cond else "FALHA", msg))
    if not cond:
        falhas.append(msg)


def chamar(pasta, acao, pc, extra=None, **entrada):
    """Roda o modo --wizard num processo separado; devolve (linhas, entrada_existe)."""
    dados = {"host": base.HOST, "port": "5432", "name": TESTE_DB, "user": base.USER,
             "password": "", "set_role": "mes_grp_client"}
    dados.update(entrada)
    ent = os.path.join(pasta, "entrada_%s.txt" % acao)
    sai = os.path.join(pasta, "saida_%s.txt" % acao)
    with open(ent, "w", encoding="utf-8-sig") as f:      # o Inno grava UTF-8 com BOM
        f.write("".join("%s=%s\r\n" % kv for kv in dados.items()))
    if os.path.exists(sai):
        os.remove(sai)
    if EXE:
        cmd = [EXE]
    else:
        cmd = [sys.executable, os.path.join(RAIZ, "system", "ui_main.py")]
    cmd += ["--wizard", acao, ent, sai] + ([extra] if extra else [])
    env = dict(os.environ, COMPUTERNAME=pc)
    rc = subprocess.call(cmd, cwd=pasta, env=env, timeout=120)
    linhas = open(sai, "rb").read().decode("ascii").splitlines() if os.path.exists(sai) else []
    return rc, linhas, os.path.exists(ent)


def fontes(linhas):
    return {l.split("|")[7] + "/" + l.split("|")[11]: l.split("|") for l in linhas if l.startswith("F|")}


def main():
    inicio = time.time()
    conn_base = base.conectar(base.BASE)
    conn_base.cursor().execute('CREATE DATABASE "%s"' % TESTE_DB)
    print("banco descartável criado: %s  (%s)" % (TESTE_DB, "exe " + EXE if EXE else "python"))
    pasta = tempfile.mkdtemp(prefix="mes_wiz_")
    dono = adm = None
    try:
        dono = base.conectar(TESTE_DB)
        dono.cursor().execute(open(base.SQL_002, encoding="utf-8").read())
        adm = base.conectar(TESTE_DB, role="mes_grp_admin")
        ids = base.cadastrar(adm)
        adm.cursor().execute("update mes_linhas set nome = 'Caiapó | Montagem' where linha_id=%s", (ids["linha"],))

        print("\n[1] catálogo: duas estações livres")
        rc, ln, ent_existe = chamar(pasta, "catalogo", "PC-WIZ-A")
        checar(rc == 0, "código de saída 0")
        checar(ln and ln[0] == "OK|PC-WIZ-A|2", "cabeçalho OK|PC|schema: %r" % (ln[:1],))
        checar(not ent_existe, "arquivo de entrada (com a senha) apagado")
        f = fontes(ln)
        checar(set(f) == {"CAIAPO-M13-FT/FT", "CAIAPO-M2-TAB/OCV"}, "as 2 fontes ativas: %s" % sorted(f))
        m13 = f.get("CAIAPO-M13-FT/FT", [""] * 16)
        checar(m13[14] == "LIVRE", "M13 LIVRE")
        checar(m13[1:7] == ["MAO", "Manaus", "SECAO_04", "Secao 04", "CAIAPO", "Caiapo / Montagem"],
               "hierarquia em ASCII, sem acento e sem '|': %r" % (m13[1:7],))
        checar(m13[9:14] == ["FT", "A08", "FT", "P2500S", "*_A08.csv"], "tipo/modelo/fonte/formato/padrão: %r" % (m13[9:14],))

        print("\n[2] vincular reserva o slot")
        rc, ln, _ = chamar(pasta, "vincular", "PC-WIZ-A", "caiapo-m13-ft")
        checar(ln[:1] == ["OK|PC-WIZ-A|%d" % ids["m13"]], "OK com station_pk: %r" % ln[:1])
        checar(base.um(dono, "select host_vinculado from mes_estacoes where station_pk=%s", (ids["m13"],))[0] == "PC-WIZ-A",
               "banco: M13 vinculada ao PC-WIZ-A")
        rc, ln, _ = chamar(pasta, "catalogo", "PC-WIZ-A")
        checar(fontes(ln)["CAIAPO-M13-FT/FT"][14] == "ESTE_PC", "mesmo PC vê ESTE_PC (reinstalação)")
        rc, ln, _ = chamar(pasta, "vincular", "PC-WIZ-A", "CAIAPO-M13-FT")
        checar(ln[:1] == ["OK|PC-WIZ-A|%d" % ids["m13"]], "vincular de novo no mesmo PC: OK")

        print("\n[3] outro PC: slot ocupado")
        rc, ln, _ = chamar(pasta, "catalogo", "PC-WIZ-B")
        fb = fontes(ln)
        checar(fb["CAIAPO-M13-FT/FT"][14] == "OCUPADA" and fb["CAIAPO-M13-FT/FT"][15] == "PC-WIZ-A",
               "PC-WIZ-B vê OCUPADA pelo PC-WIZ-A")
        checar(fb["CAIAPO-M2-TAB/OCV"][14] == "LIVRE", "M2 continua LIVRE")
        rc, ln, _ = chamar(pasta, "vincular", "PC-WIZ-B", "CAIAPO-M13-FT")
        checar(ln and ln[0].startswith("RECUSADO|") and "PC-WIZ-A" in ln[0], "PC-WIZ-B recusado: %r" % ln[:1])
        checar(base.um(dono, "select host_vinculado from mes_estacoes where station_pk=%s", (ids["m13"],))[0] == "PC-WIZ-A",
               "vínculo continua no PC-WIZ-A")

        print("\n[4] painel libera: o slot volta a aparecer livre")
        adm.cursor().execute("update mes_estacoes set host_vinculado=null, vinculado_em=null where station_pk=%s", (ids["m13"],))
        rc, ln, _ = chamar(pasta, "catalogo", "PC-WIZ-B")
        checar(fontes(ln)["CAIAPO-M13-FT/FT"][14] == "LIVRE", "LIVRE depois de liberar")
        rc, ln, _ = chamar(pasta, "vincular", "PC-WIZ-B", "CAIAPO-M13-FT")
        checar(ln[:1] == ["OK|PC-WIZ-B|%d" % ids["m13"]], "PC-WIZ-B vincula depois da liberação")

        print("\n[5] inativos não aparecem; estação inativa recusada")
        adm.cursor().execute("update mes_estacoes set ativo=false where station_pk=%s", (ids["m2"],))
        rc, ln, _ = chamar(pasta, "catalogo", "PC-WIZ-C")
        checar("CAIAPO-M2-TAB/OCV" not in fontes(ln), "M2 inativa fora da lista")
        rc, ln, _ = chamar(pasta, "vincular", "PC-WIZ-C", "CAIAPO-M2-TAB")
        checar(ln and ln[0].startswith("RECUSADO|") and "INATIVA" in ln[0].upper(), "vincular inativa: RECUSADO")
        rc, ln, _ = chamar(pasta, "vincular", "PC-WIZ-C", "NAO-EXISTE-FT")
        checar(ln and ln[0].startswith("RECUSADO|"), "estação inexistente: RECUSADO")
        adm.cursor().execute("update mes_estacoes set ativo=true where station_pk=%s", (ids["m2"],))
        adm.cursor().execute("update mes_linhas set ativo=false where linha_id=%s", (ids["linha"],))
        rc, ln, _ = chamar(pasta, "catalogo", "PC-WIZ-C")
        checar(ln[:1] == ["OK|PC-WIZ-C|2"] and not fontes(ln), "linha inativa: nenhuma fonte")
        adm.cursor().execute("update mes_linhas set ativo=true where linha_id=%s", (ids["linha"],))

        print("\n[6] erros viram mensagem (nunca exceção)")
        rc, ln, ent_existe = chamar(pasta, "catalogo", "PC-WIZ-A", password=SENHA_ERRADA)
        checar(rc == 0 and ln and ln[0].startswith("ERRO|Sem conexao"), "senha errada: ERRO|Sem conexao... %r" % ln[:1])
        checar(not ent_existe, "entrada apagada também no erro")
        rc, ln, _ = chamar(pasta, "catalogo", "PC-WIZ-A", name="banco_que_nao_existe_wiz")
        checar(ln and ln[0].startswith("ERRO|"), "banco inexistente: ERRO")
        rc, ln, _ = chamar(pasta, "catalogo", "PC-WIZ-A", name="postgres", set_role="")
        checar(ln and ln[0].startswith("ERRO|") and "schema" in ln[0], "banco sem cadastro 2.0: ERRO de schema %r" % ln[:1])
        rc, ln, _ = chamar(pasta, "vincular", "PC-WIZ-A")
        checar(ln[:1] == ["ERRO|informe o codigo da estacao"], "vincular sem estação: ERRO")

        print("\n[7] funções puras")
        checar(wh.ascii_seguro("Seção 03 | Ação\nx") == "Secao 03 / Acao x", "ascii_seguro")
        checar(wh.status_slot(None, "A") == "LIVRE" and wh.status_slot("a ", "A") == "ESTE_PC"
               and wh.status_slot("B", "A") == "OCUPADA", "status_slot")
        checar(wh.main(["x", "--wizard"]) == 2, "argumentos faltando: código 2")
    except Exception as e:
        import traceback
        traceback.print_exc()
        falhas.append("erro inesperado: %r" % e)
    finally:
        for c in (adm, dono):
            if c:
                c.close()
        conn_base.cursor().execute('DROP DATABASE IF EXISTS "%s" WITH (FORCE)' % TESTE_DB)
        print("\nbanco descartável apagado: %s" % TESTE_DB)
        conn_base.close()

    print("\n%d falha(s) em %.1fs" % (len(falhas), time.time() - inicio))
    for f in falhas:
        print("  - " + f)
    sys.exit(1 if falhas else 0)


if __name__ == "__main__":
    main()
