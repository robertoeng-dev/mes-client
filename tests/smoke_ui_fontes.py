# =============================================================================
# smoke_ui_fontes.py — teste de fumaça da tela FONTES DESTE PC (UI real)
# =============================================================================
#   .venv\Scripts\python.exe tests\smoke_ui_fontes.py <pasta_temporaria>
#
# Copia o projeto para <pasta_temporaria>\app (o config.yaml, offsets e cache
# do teste ficam lá, nunca no repositório), cria um banco descartável no
# homolog com o cadastro da M13/M2, abre a UI real (bandeja falsa), adiciona a
# fonte CAIAPO-M13-FT/FT pelos combos, espera o monitor vincular e gravar,
# testa a prévia e tira prints em <pasta_temporaria>\prints. Apaga o banco.
# =============================================================================
import os
import shutil
import subprocess
import sys

ORIGEM = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if len(sys.argv) < 2:
    print("uso: smoke_ui_fontes.py <pasta_temporaria>")
    sys.exit(2)
TMP = os.path.abspath(sys.argv[1])

if os.environ.get("MES_SMOKE_FILHO") != "1":
    # 1) copia o projeto e roda este mesmo arquivo de dentro da cópia
    app = os.path.join(TMP, "app")
    shutil.rmtree(app, ignore_errors=True)
    shutil.copytree(ORIGEM, app, ignore=shutil.ignore_patterns(
        ".venv", "build", "dist", "__pycache__", "*.log", "offsets.json", "offline_queue.jsonl",
        "cadastro_cache.json", "config.yaml", ".env"))
    env = dict(os.environ, MES_SMOKE_FILHO="1",
               MES_AMOSTRAS=os.path.join(os.path.dirname(ORIGEM), "Logs-Amostras"))
    r = subprocess.run([sys.executable, "-u", os.path.join(app, "tests", "smoke_ui_fontes.py"), TMP], env=env)
    sys.exit(r.returncode)

# ---------------------------------------------------------------- processo filho
import threading   # noqa: E402
import time        # noqa: E402

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP)
PRINTS = os.path.join(TMP, "prints")
os.makedirs(PRINTS, exist_ok=True)

import yaml        # noqa: E402
import tests.test_cliente_f2 as base  # noqa: E402  (conectar, cadastrar, TESTE_DB...)

base.TESTE_DB = "mes_teste_ui_%d" % os.getpid()
PASTA = os.path.join(TMP, "battData")
shutil.rmtree(PASTA, ignore_errors=True)
os.makedirs(PASTA)
shutil.copy(base.M13_GDE, PASTA)

yaml.safe_dump({
    "database": {"enabled": True, "host": base.HOST, "port": 5432, "name": base.TESTE_DB,
                 "user": base.USER, "set_role": "mes_grp_client"},
    "cliente": {"host_id": "PC-TESTE-UI"},
    "operation": {"mode": "database"},
    "sync": {"enabled": False, "destination_folder": "", "mode": "diff"},
    "parser": {"scan_interval": 2},
    "spec_check": {"enabled": False},
    "auth": {"operador_password": "", "engenharia_password": "nao-usada-no-teste"},
    "vinculos": [],
}, open(os.path.join(APP, "config.yaml"), "w", encoding="utf-8"), allow_unicode=True, sort_keys=False)

import pystray as _pystray  # noqa: E402


class _FakeIcon:
    def __init__(self, *a, **k):
        self._message_handlers = {}
        self._on_notify = lambda *a: None
        self.icon = None

    def run(self):
        pass

    def stop(self):
        pass

    def notify(self, *a):
        pass


_pystray.Icon = _FakeIcon

import tkinter as tk  # noqa: E402
from PIL import ImageGrab  # noqa: E402

from system.ui_main import MESClientUI  # noqa: E402

falhas = []


def checar(cond, msg):
    print("   %s %s" % ("ok   " if cond else "FALHA", msg))
    if not cond:
        falhas.append(msg)


def pump(app, seg):
    fim = time.time() + seg
    while time.time() < fim:
        app.root.update()
        time.sleep(0.03)


def snap(app, win, nome):
    win.attributes("-topmost", True)
    win.lift()
    pump(app, 0.6)
    x, y = win.winfo_rootx(), win.winfo_rooty()
    ImageGrab.grab(bbox=(x, y, x + win.winfo_width(), y + win.winfo_height())).save(os.path.join(PRINTS, nome))
    print("   print " + nome)


def achar(app, titulo):
    def todos(w):
        for c in w.winfo_children():
            yield c
            yield from todos(c)
    for w in todos(app.root):
        if isinstance(w, tk.Toplevel) and titulo in w.title():
            return w
    return None


def widgets(w, tipo):
    out = []
    for c in w.winfo_children():
        if isinstance(c, tipo):
            out.append(c)
        out += widgets(c, tipo)
    return out


def threads_monitor():
    return [t for t in threading.enumerate() if "start_monitor" in t.name and t.is_alive()]


def main():
    import faulthandler
    # trava? despeja a pilha de todas as threads e encerra (não fica pendurado)
    faulthandler.dump_traceback_later(150, exit=True)
    bconn = base.conectar(base.BASE)
    bconn.cursor().execute('CREATE DATABASE "%s"' % base.TESTE_DB)
    print("banco descartável criado: %s" % base.TESTE_DB)
    app = None
    try:
        dono = base.conectar(base.TESTE_DB)
        dono.cursor().execute(open(base.SQL_002, encoding="utf-8").read())
        adm = base.conectar(base.TESTE_DB, role="mes_grp_admin")
        base.cadastrar(adm)
        adm.close()

        app = MESClientUI()
        app.current_role = "engenharia"
        app.ensure_monitor_running()
        app.fontes_clicked()
        pump(app, 2)
        fw = app.fontes_window
        checar(fw is not None and fw.winfo_exists(), "tela FONTES DESTE PC abriu")
        snap(app, fw, "1_fontes_vazia.png")

        estado = {}

        def preencher():
            dlg = achar(app, "Adicionar fonte")
            if dlg is None:
                app.root.after(200, preencher)
                return
            from tkinter import ttk
            combos = widgets(dlg, ttk.Combobox)
            alvo = ["MAO", "SECAO_04", "CAIAPO", "CAIAPO-M13-FT", "FT"]
            for cb, valor in zip(combos, alvo):
                estado.setdefault("opcoes", []).append(list(cb["values"]))
                cb.set(valor)
                cb.event_generate("<<ComboboxSelected>>")
                app.root.update()
            [e for e in widgets(dlg, tk.Entry) if type(e) is tk.Entry][0].insert(0, PASTA)
            pump(app, 0.5)
            snap(app, dlg, "2_adicionar_fonte.png")
            info = [l.cget("text") for l in widgets(dlg, tk.Label) if "formato" in l.cget("text")]
            estado["info"] = info[0] if info else ""
            [b for b in widgets(dlg, tk.Button) if b.cget("text") == "SALVAR"][0].invoke()

        app.root.after(300, preencher)
        app._fontes.adicionar()          # bloqueia até o diálogo fechar
        checar(estado.get("opcoes", [[]])[3] == ["CAIAPO-M13-FT", "CAIAPO-M2-TAB"],
               "combo Estação veio do cadastro: %s" % estado.get("opcoes", [[], [], [], []])[3])
        checar("P2500S" in estado.get("info", "") and "pronta para vincular" in estado.get("info", ""),
               "resumo da fonte: formato P2500S, pronta para vincular")
        cfg = yaml.safe_load(open(os.path.join(APP, "config.yaml"), encoding="utf-8"))
        checar(cfg["vinculos"] == [{"estacao": "CAIAPO-M13-FT", "fonte": "FT", "pasta": PASTA}],
               "vínculo salvo no config.yaml")

        # espera o monitor reiniciar, vincular e gravar
        fim = time.time() + 40
        n = 0
        while time.time() < fim:
            pump(app, 1)
            n = base.um(dono, "select count(*) from mes_test_results")[0]
            if n >= 3367:
                break
        checar(n == 3367, "monitor gravou as 3367 linhas do arquivo (%d)" % n)
        host = base.um(dono, "select host_vinculado from mes_estacoes where codigo='CAIAPO-M13-FT'")[0]
        checar(host == "PC-TESTE-UI", "estação vinculada ao PC-TESTE-UI pela tela")
        pump(app, 2)
        linhas = [app._fontes.tree.item(i, "values") for i in app._fontes.tree.get_children()]
        checar(len(linhas) == 1 and linhas[0][3] == "OK", "lista mostra a fonte com status OK: %s" % (linhas,))
        snap(app, fw, "3_fontes_ok.png")
        checar(len(threads_monitor()) == 1, "só UMA thread de monitor depois do reinício (%d)" % len(threads_monitor()))

        prev = {}

        def ver_previa():
            dlg = achar(app, "Prévia")
            if dlg is None:
                app.root.after(200, ver_previa)
                return
            from tkinter import ttk
            tv = widgets(dlg, ttk.Treeview)[0]
            prev["linhas"] = [tv.item(i, "values") for i in tv.get_children()]
            snap(app, dlg, "4_previa.png")
            dlg.destroy()

        app._fontes.tree.selection_set("0")
        app.root.after(300, ver_previa)
        app._fontes.testar()
        pv = prev.get("linhas") or []
        checar(len(pv) == 20 and pv[0][1] == "Y422622AB04860C385L" and pv[0][2] == "PASS",
               "TESTAR: prévia de 20 linhas (1ª: %s)" % (pv[0] if pv else None,))
        checar(base.um(dono, "select count(*) from mes_test_results")[0] == 3367, "prévia não gravou nada")

        fw.destroy()
        app.status_clicked()
        pump(app, 2.5)
        snap(app, app.status_window, "5_status.png")
        txt = app.status_labels["fontes"].cget("text")
        checar("CAIAPO-M13-FT/FT  [OK]" in txt and "3367" in txt, "STATUS mostra a fonte OK e o total")
        checar(app.status_labels["host_id"].cget("text") == "PC-TESTE-UI", "STATUS mostra o nome do PC")
        app.status_window.destroy()

        app._restart_monitor()
        pump(app, 4)
        checar(len(threads_monitor()) == 1, "segundo reinício: continua UMA thread de monitor")
        app._encerrar_monitor.set()
        pump(app, 2)
        dono.close()
    except Exception as e:
        import traceback
        traceback.print_exc()
        falhas.append("erro inesperado: %r" % e)
    finally:
        if app:
            try:
                app._encerrar_monitor.set()
                time.sleep(1.5)
                app.root.destroy()
            except Exception:
                pass
        bconn.cursor().execute('DROP DATABASE IF EXISTS "%s" WITH (FORCE)' % base.TESTE_DB)
        print("banco descartável apagado: %s" % base.TESTE_DB)
        bconn.close()
    print("\n%d falha(s)" % len(falhas))
    os._exit(1 if falhas else 0)


main()
