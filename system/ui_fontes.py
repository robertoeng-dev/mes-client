# =============================================================================
# ui_fontes.py — Tela "FONTES DESTE PC" (cliente 2.0)
# =============================================================================
#
# Substitui o antigo campo "Station ID" digitado à mão. O engenheiro escolhe a
# estação e a fonte nos combos que vêm do CADASTRO do servidor
# (Planta → Seção → Linha → Estação → Fonte) e só informa a pasta local onde
# o equipamento grava. Nada de digitar código: sem erro de grafia/maiúscula.
#
#   ADICIONAR        — novo vínculo (senha de engenharia)
#   REMOVER          — tira o vínculo deste PC (senha de engenharia)
#   TESTAR           — lê o arquivo mais novo da pasta e mostra 20 linhas
#                      interpretadas, SEM gravar nada
#   VINCULAR DE NOVO — depois que a engenharia liberou o vínculo no MES
#                      Cadastro (troca de PC), autoriza este PC a vincular
#
# Os vínculos ficam em config.yaml (chave "vinculos"); salvar reinicia o monitor.
# =============================================================================

import os
import tkinter as tk
from tkinter import filedialog, ttk

from config.column_mapper import load_mappings
from config.loader import load_config, load_raw_config, save_config
from database.db_writer import DBWriter, host_do_pc
from logs.logger_setup import get_logger
from parser import registry
from parser.campos import schema_hash
from state.app_context import runtime_status
from state.station_cache import StationCache

logger = get_logger()

NIVEIS = (("planta_codigo", "Planta"), ("secao_codigo", "Seção"), ("linha_codigo", "Linha"),
          ("estacao_codigo", "Estação"), ("fonte_codigo", "Fonte"))


def _arquivo_mais_novo(pasta, linha):
    from monitor.file_monitor import _list_files
    arquivos = _list_files(pasta, linha.get("padrao_arquivo"), linha.get("recursivo"))
    return max(arquivos, key=os.path.getmtime) if arquivos else None


def previa_vinculo(linha, pasta, max_linhas=20):
    """(arquivo, itens, rejeitadas) do arquivo mais novo da pasta. Não grava."""
    caminho = _arquivo_mais_novo(pasta, linha)
    if not caminho:
        raise FileNotFoundError("nenhum arquivo '%s' em %s" % (linha.get("padrao_arquivo"), pasta))
    ok, motivo = registry.formato_suportado(linha)
    if not ok:
        raise ValueError(motivo)
    p = registry.ler(linha, caminho, {"offset": 0, "line_no": 0, "file_size": 0})
    p["rows"] = p["rows"][:max_linhas]
    lote, _, _ = registry.montar_lote(linha, p, caminho, os.path.basename(caminho),
                                      schema_hash(p["schema"]["headers"]), load_mappings())
    return caminho, lote, p["skipped"]


class FontesWindow:
    def __init__(self, app):
        self.app = app
        self.win = None
        self.tree = None
        self.cache = StationCache()

    # --------------------------------------------------------------- helpers
    def _vinculos(self):
        return list(load_raw_config().get("vinculos") or [])

    def _salvar_vinculos(self, vinculos):
        cfg = load_raw_config()
        cfg["vinculos"] = vinculos
        save_config(cfg)
        self.app._restart_monitor()

    def _selecionado(self):
        sel = self.tree.selection()
        if not sel:
            self.app._dark_msg("Fontes", "Selecione uma fonte na lista.", kind="warning", parent=self.win)
            return None
        return int(sel[0])

    def _catalogo(self):
        """Linhas de v_cadastro_fontes, ou None se o banco não responder."""
        db = None
        try:
            db = DBWriter(load_config())
            if db.conn is None:
                raise ConnectionError(runtime_status.snapshot().get("last_error") or "banco offline")
            return db.listar_catalogo()
        except Exception as e:
            self.app._dark_msg("Cadastro", "Não foi possível ler o cadastro do servidor:\n\n%s" % e,
                               kind="error", parent=self.win)
            return None
        finally:
            if db:
                db.close()

    # ------------------------------------------------------------------ tela
    def abrir(self):
        app = self.app
        if self.win and self.win.winfo_exists():
            self.win.lift()
            return
        if not app._try_open_window("FONTES DESTE PC"):
            return
        self.win = tk.Toplevel(app.root)
        app.fontes_window = self.win
        geo, _w, _h = app._dynamic_geometry(0.80, 0.62, 940, 480, max_w=1400, max_h=820)
        app._style_window(self.win, "Fontes deste PC", geo)
        app._register_window(self.win)

        try:
            cfg = load_config()
            host, banco = host_do_pc(cfg), cfg["database"]["name"]
        except Exception:
            host, banco = host_do_pc({}), "?"
        tk.Label(self.win, text="FONTES DESTE PC", bg=app.bg_main, fg=app.fg_main,
                 font=("Segoe UI", 16, "bold")).pack(pady=(16, 2))
        tk.Label(self.win, text="PC: %s   •   banco: %s   •   estações e fontes vêm do MES Cadastro"
                 % (host, banco), bg=app.bg_main, fg=app.fg_secondary, font=("Segoe UI", 9)).pack(pady=(0, 8))

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Fon.Treeview", background=app.bg_card, foreground=app.fg_main,
                        fieldbackground=app.bg_card, rowheight=26, font=("Segoe UI", 10))
        style.configure("Fon.Treeview.Heading", background=app.bg_input, foreground=app.fg_main,
                        font=("Segoe UI", 10, "bold"), relief="flat")
        style.map("Fon.Treeview", background=[("selected", "#3a4a3a")])

        frame = tk.Frame(self.win, bg=app.bg_main)
        frame.pack(fill="both", expand=True, padx=16, pady=(0, 4))
        cols = (("estacao", "Estação", 170), ("fonte", "Fonte", 70), ("pasta", "Pasta local", 230),
                ("status", "Status", 170), ("detalhe", "Detalhe", 420))
        self.tree = ttk.Treeview(frame, columns=[c[0] for c in cols], show="headings",
                                 style="Fon.Treeview", selectmode="browse")
        for cid, txt, w in cols:
            self.tree.heading(cid, text=txt)
            self.tree.column(cid, width=w, minwidth=60, anchor="w")
        self.tree.tag_configure("ok", foreground="#7bd88f")
        self.tree.tag_configure("ruim", foreground="#ff7b7b")
        vsb = tk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        footer = tk.Frame(self.win, bg=app.bg_main)
        footer.pack(fill="x", padx=16, pady=(6, 14))
        for txt, cmd in (("ADICIONAR", self.adicionar), ("REMOVER", self.remover),
                         ("TESTAR", self.testar), ("VINCULAR DE NOVO", self.revincular)):
            app._make_button(footer, txt, cmd, width=17 if len(txt) > 10 else 13).pack(side="left", padx=(0, 8))
        app._add_help_btn(footer, section="config").pack(side="left", padx=8)
        app._make_button(footer, "FECHAR", self.win.destroy, width=13).pack(side="right")
        self._atualizar()

    def _atualizar(self):
        if not self.win or not self.win.winfo_exists():
            return
        status = runtime_status.snapshot().get("fontes") or {}
        sel = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for i, v in enumerate(self._vinculos()):
            chave = StationCache.chave(v.get("estacao", ""), v.get("fonte", ""))
            st = status.get(chave, {})
            s = st.get("status") or "aguardando monitor"
            self.tree.insert("", "end", iid=str(i), tags=("ok" if s.startswith("OK") else "ruim",),
                             values=(v.get("estacao", ""), v.get("fonte", ""), v.get("pasta", ""), s,
                                     st.get("detalhe", "")))
        if sel and self.tree.exists(sel[0]):
            self.tree.selection_set(sel[0])
        self.win.after(1500, self._atualizar)

    # ----------------------------------------------------------------- ações
    def remover(self):
        i = self._selecionado()
        if i is None:
            return
        v = self._vinculos()[i]
        if not self.app._check_role(action_label="remover uma fonte", parent=self.win):
            return
        if not self.app._dark_msg("Remover fonte",
                                  "Parar de ler %s / %s neste PC?\n\nO que já foi gravado no banco continua lá. "
                                  "O vínculo da estação no servidor só é liberado pela engenharia no MES Cadastro."
                                  % (v.get("estacao"), v.get("fonte")), kind="yesno", parent=self.win):
            return
        vinculos = self._vinculos()
        vinculos.pop(i)
        self._salvar_vinculos(vinculos)

    def revincular(self):
        i = self._selecionado()
        if i is None:
            return
        v = self._vinculos()[i]
        linha = self.cache.buscar(v.get("estacao", ""), v.get("fonte", ""))
        if not linha:
            self.app._dark_msg("Vincular", "Esta fonte ainda não foi lida do cadastro.", kind="warning", parent=self.win)
            return
        if not self.app._check_role(action_label="vincular a estação a este PC", parent=self.win):
            return
        self.cache.desconfirmar(linha["station_pk"])
        self.app._restart_monitor()
        self.app._dark_msg("Vincular", "Pedido registrado. Se a estação estiver sem PC no cadastro, "
                           "ela será vinculada a este PC em alguns segundos (veja a coluna Status).",
                           kind="info", parent=self.win)

    def testar(self):
        i = self._selecionado()
        if i is None:
            return
        v = self._vinculos()[i]
        linha = self.cache.buscar(v.get("estacao", ""), v.get("fonte", ""))
        if not linha:
            cat = self._catalogo()
            if cat is None:
                return
            linha = next((r for r in cat if StationCache.chave(r["estacao_codigo"], r["fonte_codigo"])
                          == StationCache.chave(v.get("estacao", ""), v.get("fonte", ""))), None)
            if not linha:
                self.app._dark_msg("Testar", "Fonte não encontrada no cadastro.", kind="error", parent=self.win)
                return
        self._mostrar_previa(linha, v.get("pasta", ""))

    def _mostrar_previa(self, linha, pasta, parent=None):
        app = self.app
        parent = parent or self.win
        try:
            caminho, lote, rejeitadas = previa_vinculo(linha, pasta)
        except Exception as e:
            app._dark_msg("Testar", "Não foi possível ler a fonte:\n\n%s" % e, kind="error", parent=parent)
            return
        dlg = tk.Toplevel(parent)
        dlg.title("Prévia — nada é gravado")
        dlg.configure(bg=app.bg_main)
        dlg.transient(parent)
        tk.Label(dlg, text="%s  (formato %s)\n%d linha(s) mostradas • %d rejeitada(s) no arquivo"
                 % (caminho, linha.get("formato_codigo"), len(lote), len(rejeitadas)),
                 bg=app.bg_main, fg=app.fg_secondary, justify="left", font=("Segoe UI", 9)).pack(padx=12, pady=8, anchor="w")
        cols = (("source_line_no", "Linha", 60), ("serial_number", "Serial", 220), ("result_status", "Resultado", 90),
                ("test_start_time", "Data/hora (local)", 160), ("model_name", "Modelo", 90), ("defeito", "Defeito", 120))
        tv = ttk.Treeview(dlg, columns=[c[0] for c in cols], show="headings", style="Fon.Treeview", height=20)
        for cid, txt, w in cols:
            tv.heading(cid, text=txt)
            tv.column(cid, width=w, anchor="w")
        for it in lote:
            tv.insert("", "end", values=[it.get(c[0]) if it.get(c[0]) is not None else "-" for c in cols])
        tv.pack(fill="both", expand=True, padx=12)
        app._make_button(dlg, "FECHAR", dlg.destroy, width=13).pack(pady=10)
        dlg.grab_set()
        dlg.wait_window()
        if self.win and self.win.winfo_exists():
            self.win.grab_set()

    def adicionar(self):
        app = self.app
        if not app._check_role(action_label="adicionar uma fonte", parent=self.win):
            return
        catalogo = self._catalogo()
        if catalogo is None:
            return
        if not catalogo:
            app._dark_msg("Cadastro", "O cadastro deste domínio ainda não tem nenhuma fonte.\n"
                          "Cadastre a estação e a fonte no MES Cadastro primeiro.", kind="warning", parent=self.win)
            return

        dlg = tk.Toplevel(self.win)
        dlg.title("Adicionar fonte")
        dlg.configure(bg=app.bg_main)
        dlg.resizable(False, False)
        dlg.transient(self.win)
        vars_ = {}
        combos = {}
        for r, (campo, rotulo) in enumerate(NIVEIS):
            tk.Label(dlg, text=rotulo, bg=app.bg_main, fg=app.fg_secondary, font=("Segoe UI", 10)).grid(
                row=r, column=0, padx=(16, 8), pady=5, sticky="w")
            vars_[campo] = tk.StringVar()
            combos[campo] = ttk.Combobox(dlg, textvariable=vars_[campo], state="readonly", width=40,
                                         font=("Segoe UI", 10))
            combos[campo].grid(row=r, column=1, columnspan=2, padx=(0, 16), pady=5, sticky="ew")
        info = tk.Label(dlg, text="", bg=app.bg_main, fg=app.fg_secondary, justify="left",
                        font=("Segoe UI", 9), wraplength=520)
        info.grid(row=5, column=0, columnspan=3, padx=16, pady=(6, 4), sticky="w")

        tk.Label(dlg, text="Pasta local dos logs", bg=app.bg_main, fg=app.fg_secondary,
                 font=("Segoe UI", 10)).grid(row=6, column=0, padx=(16, 8), pady=5, sticky="w")
        pasta_var = tk.StringVar()
        tk.Entry(dlg, textvariable=pasta_var, bg=app.bg_input, fg=app.fg_main, insertbackground=app.fg_main,
                 width=40, relief="flat", bd=4).grid(row=6, column=1, pady=5, sticky="ew")
        app._make_button(dlg, "Selecionar", lambda: pasta_var.set(
            filedialog.askdirectory(parent=dlg) or pasta_var.get()), width=11).grid(row=6, column=2, padx=(6, 16))
        tk.Label(dlg, text="Cópia p/ rede (opcional)", bg=app.bg_main, fg=app.fg_secondary,
                 font=("Segoe UI", 10)).grid(row=7, column=0, padx=(16, 8), pady=5, sticky="w")
        sync_var = tk.StringVar()
        tk.Entry(dlg, textvariable=sync_var, bg=app.bg_input, fg=app.fg_main, insertbackground=app.fg_main,
                 width=40, relief="flat", bd=4).grid(row=7, column=1, columnspan=2, padx=(0, 16), pady=5, sticky="ew")

        def filtrar(ate):
            linhas = catalogo
            for campo, _ in NIVEIS[:ate]:
                linhas = [x for x in linhas if x[campo] == vars_[campo].get()]
            return linhas

        def escolhida():
            linhas = filtrar(len(NIVEIS))
            return linhas[0] if len(linhas) == 1 else None

        def cascata(nivel):
            for k in range(nivel, len(NIVEIS)):
                campo = NIVEIS[k][0]
                valores = sorted({x[campo] for x in filtrar(k)})
                combos[campo]["values"] = valores
                if vars_[campo].get() not in valores:
                    vars_[campo].set(valores[0] if len(valores) == 1 else "")
            l = escolhida()
            if not l:
                info.config(text="")
                return
            avisos = []
            if not (l["estacao_ativa"] and l["fonte_ativa"]):
                avisos.append("INATIVA no cadastro")
            if l["host_vinculado"] and l["host_vinculado"] != host_do_pc(load_config()):
                avisos.append("vinculada ao PC %s" % l["host_vinculado"])
            ok, motivo = registry.formato_suportado(l)
            if not ok:
                avisos.append(motivo)
            info.config(fg="#ff7b7b" if avisos else "#7bd88f", text=(
                "%s — %s\nformato %s (%s) • arquivos '%s'%s • modelo atual %s\n%s" % (
                    l["estacao_codigo"], l.get("estacao_descricao") or "", l["formato_codigo"], l["formato_tipo"],
                    l["padrao_arquivo"], " (com subpastas)" if l["recursivo"] else "", l["modelo_atual"] or "-",
                    ("ATENÇÃO: " + "; ".join(avisos)) if avisos else "pronta para vincular")))

        for k, (campo, _) in enumerate(NIVEIS):
            combos[campo].bind("<<ComboboxSelected>>", lambda e, k=k: cascata(k + 1))
        cascata(0)

        def testar():
            l = escolhida()
            if not l or not pasta_var.get().strip():
                app._dark_msg("Testar", "Escolha a fonte e a pasta.", kind="warning", parent=dlg)
                return
            self._mostrar_previa(l, pasta_var.get().strip(), parent=dlg)

        def ok():
            l = escolhida()
            pasta = pasta_var.get().strip()
            if not l:
                app._dark_msg("Adicionar", "Escolha Planta, Seção, Linha, Estação e Fonte.", kind="warning", parent=dlg)
                return
            if not pasta or not os.path.isdir(pasta):
                app._dark_msg("Adicionar", "Pasta não encontrada:\n%s" % pasta, kind="warning", parent=dlg)
                return
            chave = StationCache.chave(l["estacao_codigo"], l["fonte_codigo"])
            vinculos = self._vinculos()
            if any(StationCache.chave(v.get("estacao", ""), v.get("fonte", "")) == chave for v in vinculos):
                app._dark_msg("Adicionar", "%s já está nesta lista." % chave, kind="warning", parent=dlg)
                return
            if l["host_vinculado"] and l["host_vinculado"] != host_do_pc(load_config()):
                app._dark_msg("Adicionar", "A estação %s está vinculada ao PC %s.\n\nPeça à engenharia para "
                              "liberar o vínculo no MES Cadastro antes." % (l["estacao_codigo"], l["host_vinculado"]),
                              kind="error", parent=dlg)
                return
            novo = {"estacao": l["estacao_codigo"], "fonte": l["fonte_codigo"], "pasta": pasta}
            if sync_var.get().strip():
                novo["sync_destino"] = sync_var.get().strip()
            vinculos.append(novo)
            self._salvar_vinculos(vinculos)
            logger.info("Fonte adicionada neste PC: %s <- %s" % (chave, pasta))
            dlg.destroy()

        bf = tk.Frame(dlg, bg=app.bg_main)
        bf.grid(row=8, column=0, columnspan=3, pady=12)
        app._make_button(bf, "TESTAR", testar, width=12).pack(side="left", padx=8)
        app._make_button(bf, "SALVAR", ok, width=12).pack(side="left", padx=8)
        app._make_button(bf, "Cancelar", dlg.destroy, width=12).pack(side="left", padx=8)
        dlg.grab_set()
        dlg.wait_window()
        if self.win and self.win.winfo_exists():
            self.win.grab_set()
