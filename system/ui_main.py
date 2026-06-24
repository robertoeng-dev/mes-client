# =============================================================================
# ui_main.py — Interface gráfica principal do MES Client
# =============================================================================
#
# ARQUITETURA GERAL
# -----------------
# O app é um ícone na bandeja do sistema (system tray) usando pystray.
# A UI principal é Tkinter. Cada tela (STATUS, CONFIG, LIMITES, AJUDA)
# é um tk.Toplevel — janela filha da root oculta.
#
# THREADS
# -------
# - Main thread: Tkinter mainloop (única thread que pode tocar widgets)
# - Thread do pystray: roda o ícone/menu da bandeja
# - Thread do monitor: lê arquivos CSV e insere no banco
#
# REGRA CRÍTICA: pystray callbacks NÃO podem chamar Tkinter diretamente.
# Use root.after(0, func) para enviar trabalho para a main thread.
#
# MODAL SYSTEM
# ------------
# Só uma janela pode estar aberta por vez (exceto AJUDA, que é filha).
# _register_window() + grab_set() + _bind_focus_lock() garantem isso.
# =============================================================================

import os
import sys

# Garante que a raiz do projeto está no path ao rodar como script direto
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import threading
import csv as _csv
import tkinter as tk
from tkinter import messagebox, filedialog, ttk
from datetime import datetime

import ctypes
import ctypes.wintypes

import pystray
from PIL import Image, ImageDraw, ImageTk

from config.loader import load_config, load_raw_config, save_config, get_base_path
from monitor.file_monitor import start_monitor
from state.app_context import runtime_status
from system.single_instance import SingleInstance


# -----------------------------------------------------------------------------
# TOOLTIP
# Reutilizável: ToolTip(widget, "texto") em qualquer widget Tkinter
# -----------------------------------------------------------------------------
class ToolTip:
    """Tooltip flutuante dark-themed para qualquer widget Tkinter."""

    def __init__(self, widget, text, delay=500):
        self.widget = widget
        self.text   = text
        self.delay  = delay
        self._job   = None   # ID do after() agendado (para cancelar se o mouse sair)
        self._win   = None   # janela do tooltip (para destruir ao sair)
        # add="+" preserva bindings existentes no widget (não sobrescreve)
        widget.bind("<Enter>",       self._schedule, add="+")
        widget.bind("<Leave>",       self._cancel,   add="+")
        widget.bind("<ButtonPress>", self._cancel,   add="+")

    def _schedule(self, _=None):
        self._cancel()
        # after(delay, func): agenda exibição após 500ms — evita piscar ao passar o mouse
        self._job = self.widget.after(self.delay, self._show)

    def _cancel(self, _=None):
        if self._job:
            self.widget.after_cancel(self._job)
            self._job = None
        if self._win:
            self._win.destroy()
            self._win = None

    def _show(self):
        # winfo_rootx/y: coordenada absoluta na tela (não relativa à janela pai)
        x = self.widget.winfo_rootx() + 16
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self._win = tk.Toplevel(self.widget)
        # overrideredirect(True): remove barra de título e bordas do OS — visual limpo
        self._win.wm_overrideredirect(True)
        self._win.wm_geometry(f"+{x}+{y}")
        tk.Label(
            self._win, text=self.text, justify="left",
            bg="#2a2a2a", fg="#e8e8e8", relief="flat",
            font=("Segoe UI", 9), padx=10, pady=6,
            wraplength=320, bd=1
        ).pack()


# -----------------------------------------------------------------------------
# CLASSE PRINCIPAL
# -----------------------------------------------------------------------------
class MESClientUI:
    # -------------------------------------------------------------------------
    # INICIALIZAÇÃO
    # -------------------------------------------------------------------------
    def __init__(self):
        self.config = load_config()

        # stop_event: sinal para parar o thread do monitor
        # .set() → monitor para | .clear() → monitor pode rodar
        self.stop_event = threading.Event()
        self.stop_event.clear()

        self.monitor_thread = None

        # root é a janela mãe (oculta). Todo Toplevel é filho dela.
        # withdraw() esconde a root — o app vive na bandeja, não em janela.
        self.root = tk.Tk()
        self.root.withdraw()

        # iconphoto(True, ...) propaga o ícone da bateria para TODOS os Toplevels
        # futuros automaticamente — incluindo messageboxes.
        self._window_icon    = ImageTk.PhotoImage(self._create_icon("yellow", size=32))
        self._window_icon_lg = ImageTk.PhotoImage(self._create_icon("yellow", size=64))
        self.root.iconphoto(True, self._window_icon_lg, self._window_icon)

        # Referências às janelas abertas. None = fechada. Verificar .winfo_exists()
        # antes de usar — Tkinter não zera a referência quando a janela é destruída.
        self.about_window      = None
        self.config_window     = None
        self.status_window     = None
        self.limites_window    = None
        self.mapeamento_window = None
        self.ajuda_window      = None
        self.active_window  = None   # janela modal atualmente ativa (só uma por vez)
        self.auth_dialog    = None   # diálogo de autenticação (_check_role); pausa o focus lock

        # Perfil da sessão: "operador" ou "engenharia". Define o que o usuário pode fazer.
        self.current_role = None

        # Popup dark do system tray (custom menu que abre no clique esquerdo)
        self._tray_popup_win = None

        # Dicionário de Labels da tela STATUS (key → widget) para atualização em tempo real
        self.status_labels = {}

        # Paleta de cores dark — usada em todos os widgets para manter consistência
        self.bg_main      = "#121212"
        self.bg_card      = "#1e1e1e"
        self.bg_input     = "#252525"
        self.fg_main      = "#f2f2f2"
        self.fg_secondary = "#cfcfcf"
        self.btn_bg       = "#2d2d2d"
        self.btn_fg       = "#f2f2f2"
        self.btn_hover    = "#3a3a3a"

        # Menu da bandeja do sistema.
        # ATENÇÃO pystray: callbacks DEVEM ter assinatura (self, icon=None, item=None).
        # Qualquer parâmetro extra é rejeitado na criação do menu.
        # Sem menu nativo — clique direito → popup dark (via patch em _show_login_then_start)
        self.icon = pystray.Icon(
            "MES_Client",
            self._create_icon("yellow"),
            "MES Client",
        )

    # -------------------------------------------------------------------------
    # HELPERS DE JANELA — geometria, estilo, botões
    # -------------------------------------------------------------------------

    def _dynamic_geometry(self, w_ratio, h_ratio, min_w, min_h, max_w=None, max_h=None):
        """Calcula tamanho responsivo: % da tela com limites mínimo e máximo."""
        # winfo_screenwidth SEMPRE no self.root — Toplevel recém-criado retorna 0
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w = max(min_w, int(sw * w_ratio))
        h = max(min_h, int(sh * h_ratio))
        if max_w:
            w = min(w, max_w)
        if max_h:
            h = min(h, max_h)
        return f"{w}x{h}", w, h

    def _style_window(self, win, title, geometry):
        """Aplica tema dark, título, ícone e posição centralizada no topo da tela."""
        win.title(title)
        win.configure(bg=self.bg_main)
        win.resizable(False, False)
        win.iconphoto(False, self._window_icon)
        w, h = map(int, geometry.split("x"))
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - w) // 2           # centralizado horizontalmente
        y = max(30, int(sh * 0.04)) # próximo ao topo (4% da altura da tela)
        win.geometry(f"{w}x{h}+{x}+{y}")

    def _make_button(self, parent, text, command, width=14):
        return tk.Button(
            parent,
            text=text,
            width=width,
            command=command,
            bg=self.btn_bg,
            fg=self.btn_fg,
            activebackground=self.btn_hover,
            activeforeground=self.btn_fg,
            relief="flat",
            bd=0,
            padx=10,
            pady=7,
            cursor="hand2"
        )

    # -------------------------------------------------------------------------
    # DARK MSG — substitui messagebox com dialog dark consistente com o app
    # -------------------------------------------------------------------------

    def _bring_to_front(self, win):
        """Força janela ao primeiro plano mesmo com app em background.
        Windows 11 bloqueia SetForegroundWindow se o processo não tem foco —
        AttachThreadInput contorna isso temporariamente."""
        try:
            hwnd = win.winfo_id()
            fg_hwnd = ctypes.windll.user32.GetForegroundWindow()
            if fg_hwnd and fg_hwnd != hwnd:
                fg_tid = ctypes.windll.user32.GetWindowThreadProcessId(fg_hwnd, None)
                our_tid = ctypes.windll.kernel32.GetCurrentThreadId()
                if fg_tid and fg_tid != our_tid:
                    ctypes.windll.user32.AttachThreadInput(our_tid, fg_tid, True)
                    ctypes.windll.user32.SetForegroundWindow(hwnd)
                    ctypes.windll.user32.BringWindowToTop(hwnd)
                    ctypes.windll.user32.AttachThreadInput(our_tid, fg_tid, False)
                else:
                    ctypes.windll.user32.SetForegroundWindow(hwnd)
        except Exception:
            pass

    def _dark_msg(self, title, message, kind="info", parent=None):
        """Dialog dark que substitui todos os messagebox.
        kind: 'info' | 'warning' | 'error' | 'yesno'
        Retorna True/False para 'yesno', None para os demais.
        Restaura grab ao parent modal após fechar."""
        HDR_BG  = {"info": "#1a3250", "warning": "#3a2d00", "error": "#3a1010", "yesno": "#0d0d0d"}
        ICON_FG = {"info": "#4a9eff", "warning": "#ffbb33", "error": "#e05050", "yesno": "#b0b0b0"}
        ICONS   = {"info": "ℹ", "warning": "⚠", "error": "✖", "yesno": "?"}

        result = [None]

        dlg = tk.Toplevel(self.root)
        dlg.title(title)
        dlg.configure(bg="#141414")
        dlg.resizable(False, False)
        dlg.attributes("-topmost", True)
        try:
            dlg.iconphoto(False, self._window_icon)
        except Exception:
            pass
        if parent and parent is not self.root:
            dlg.transient(parent)

        # Header colorido por tipo
        hdr = tk.Frame(dlg, bg=HDR_BG.get(kind, "#0d0d0d"), height=38)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(
            hdr,
            text=f"  {ICONS.get(kind, 'ℹ')}   {title}",
            bg=HDR_BG.get(kind, "#0d0d0d"),
            fg=ICON_FG.get(kind, "#e2e2e2"),
            font=("Segoe UI", 10, "bold")
        ).pack(side="left", padx=8, pady=9)

        # Mensagem
        tk.Label(
            dlg,
            text=message,
            bg="#141414", fg="#e2e2e2",
            font=("Segoe UI", 10), justify="center", wraplength=390
        ).pack(padx=18, pady=(14, 8))

        # Botões
        btn_f = tk.Frame(dlg, bg="#141414")
        btn_f.pack(pady=(4, 18))

        if kind == "yesno":
            def _yes():
                result[0] = True
                dlg.destroy()
            def _no():
                result[0] = False
                dlg.destroy()
            tk.Button(btn_f, text="SIM", command=_yes,
                      bg="#1e3a5f", fg="white", font=("Segoe UI", 10, "bold"),
                      activebackground="#2a4f7a", activeforeground="white",
                      relief="flat", padx=22, pady=6, cursor="hand2", bd=0
                      ).pack(side="left", padx=8)
            tk.Button(btn_f, text="NÃO", command=_no,
                      bg="#2d2d2d", fg="#e2e2e2", font=("Segoe UI", 10),
                      activebackground="#3a3a3a", activeforeground="#e2e2e2",
                      relief="flat", padx=22, pady=6, cursor="hand2", bd=0
                      ).pack(side="left", padx=8)
            dlg.protocol("WM_DELETE_WINDOW", _no)
        else:
            def _ok():
                result[0] = True
                dlg.destroy()
            tk.Button(btn_f, text="OK", command=_ok,
                      bg="#2d2d2d", fg="#e2e2e2", font=("Segoe UI", 10),
                      activebackground="#3a3a3a", activeforeground="#e2e2e2",
                      relief="flat", padx=28, pady=6, cursor="hand2", bd=0
                      ).pack()
            dlg.protocol("WM_DELETE_WINDOW", _ok)

        # Auto-size: largura fixa 420, altura conforme conteúdo
        dlg.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w = 420
        h = dlg.winfo_reqheight()
        dlg.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

        self._bring_to_front(dlg)
        dlg.grab_set()
        dlg.focus_force()
        dlg.wait_window()

        # Restaura grab ao parent modal se ainda existir
        if parent and parent is not self.root:
            try:
                if parent.winfo_exists():
                    parent.grab_set()
                    parent.focus_force()
            except Exception:
                pass

        return result[0]

    # -------------------------------------------------------------------------
    # SISTEMA MODAL — controla qual janela está aberta e prende o foco
    # -------------------------------------------------------------------------

    def _try_open_window(self, name):
        """Impede abrir uma segunda janela enquanto outra está ativa.
        Levanta a janela atual e mostra aviso. Retorna True se pode abrir."""
        if self.active_window and self.active_window.winfo_exists():
            self.active_window.lift()
            self.active_window.focus_force()
            self._dark_msg(
                "Tela em uso",
                f"Feche a tela atual antes de abrir '{name}'.",
                kind="warning", parent=self.active_window
            )
            return False
        return True

    def _tooltip(self, widget, text):
        """Adiciona tooltip dark-themed ao widget."""
        ToolTip(widget, text)

    def _add_help_btn(self, parent, section="geral"):
        """Cria botão ? que abre a AJUDA diretamente na seção correta.
        lambda captura 'section' por valor (s=section) para evitar problema de closure em loop."""
        btn = tk.Button(
            parent, text=" ? ", font=("Segoe UI", 9, "bold"),
            bg="#2d2d2d", fg="#aaaaaa",
            activebackground="#3a3a3a", activeforeground="#f2f2f2",
            relief="flat", bd=0, cursor="hand2", padx=4, pady=2,
            command=lambda s=section: self._open_ajuda(s)
        )
        return btn

    def _bind_focus_lock(self, win):
        """Prende o foco na janela: se o OS tirar o foco (Alt+Tab, clique no desktop),
        a janela recaptura em 50ms.
        Exceção: AJUDA ou diálogo de autenticação podem roubar o foco legitimamente."""
        def _reclaim(event=None):
            if not win.winfo_exists():
                return
            try:
                ajuda_open = bool(self.ajuda_window and self.ajuda_window.winfo_exists())
            except Exception:
                ajuda_open = False
            try:
                # auth_dialog aberto = _check_role em andamento; não briga com ele
                auth_open = bool(self.auth_dialog and self.auth_dialog.winfo_exists())
            except Exception:
                auth_open = False
            if ajuda_open or auth_open:
                return
            win.lift()
            win.focus_force()
        win.bind("<FocusOut>", lambda e: win.after(50, _reclaim), add="+")

    def _register_window(self, win):
        """Registra janela como modal ativa: grab de eventos + focus lock + F1 para ajuda."""
        self.active_window = win
        # grab_set(): redireciona TODOS os cliques dentro do app para esta janela
        win.grab_set()
        win.focus_force()
        win.bind("<Destroy>", lambda e, w=win: self._on_window_destroyed(e, w))
        win.bind("<F1>", lambda e: self._open_ajuda())
        self._bind_focus_lock(win)

    def _on_window_destroyed(self, event, win):
        # event.widget é o widget que disparou o evento — pode ser um filho
        # verificamos se é exatamente 'win' para não limpar active_window prematuramente
        if event.widget is win and self.active_window is win:
            self.active_window = None

    def _create_icon(self, color, size=64):
        img = Image.new("RGB", (size, size), (28, 28, 28))
        d = ImageDraw.Draw(img)

        if color == "green":
            fill_color = (0, 200, 75)
            fill_ratio = 0.82
        elif color == "yellow":
            fill_color = (255, 185, 0)
            fill_ratio = 0.50
        else:
            fill_color = (210, 35, 35)
            fill_ratio = 0.18

        s = size / 64

        bx1, by1 = round(5 * s), round(20 * s)
        bx2, by2 = round(51 * s), round(44 * s)
        tx1, ty1 = round(51 * s), round(27 * s)
        tx2, ty2 = round(57 * s), round(37 * s)
        ix1 = bx1 + round(3 * s)
        iy1 = by1 + round(3 * s)
        ix2 = bx2 - round(3 * s)
        iy2 = by2 - round(3 * s)
        fill_x2 = ix1 + round((ix2 - ix1) * fill_ratio)

        if fill_x2 > ix1:
            d.rectangle((ix1, iy1, fill_x2, iy2), fill=fill_color)

        lw = max(1, round(2 * s))
        d.rectangle((bx1, by1, bx2, by2), outline=(210, 210, 210), width=lw)
        d.rectangle((tx1, ty1, tx2, ty2), fill=(210, 210, 210))

        return img

    def update_status_icon(self, color):
        self.icon.icon = self._create_icon(color)

    # -------------------------------------------------------------------------
    # POPUP DARK DO SYSTEM TRAY
    # Clique esquerdo no ícone → popup Tkinter dark premium (sem menu nativo).
    # Clique direito → menu nativo do pystray (fallback com todos os itens).
    # -------------------------------------------------------------------------

    def _show_tray_menu(self, icon=None, item=None):
        """Callback pystray (outra thread) → agenda abertura do popup na main thread."""
        self.root.after(0, self._open_tray_popup)

    def _close_tray_popup_win(self):
        if self._tray_popup_win:
            try:
                if self._tray_popup_win.winfo_exists():
                    self._tray_popup_win.destroy()
            except Exception:
                pass
            self._tray_popup_win = None

    def _open_tray_popup(self):
        # Toggle: se já está aberto, fecha
        if self._tray_popup_win:
            self._close_tray_popup_win()
            return

        # Posição do cursor via Win32
        pt = ctypes.wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        mx, my = pt.x, pt.y

        # Paleta dark premium
        BG       = "#141414"
        BG_HDR   = "#0d0d0d"
        BG_HOVER = "#1c1c1c"
        FG       = "#e2e2e2"
        FG_DIM   = "#4a4a4a"
        FG_EXIT  = "#ff4d4d"
        BORDER   = "#252525"
        SEP      = "#222222"

        snap = runtime_status.snapshot()
        client_status = snap.get("client_status", "-")
        status_color  = "#1db954" if client_status == "RUNNING" else "#e05050"

        popup = tk.Toplevel(self.root)
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        popup.configure(bg=BORDER)          # borda de 1px via bg do popup
        self._tray_popup_win = popup

        # Container interno com o fundo real
        inner = tk.Frame(popup, bg=BG)
        inner.pack(fill="both", expand=True, padx=1, pady=1)

        # ── Cabeçalho ─────────────────────────────────────────────────
        hdr = tk.Frame(inner, bg=BG_HDR)
        hdr.pack(fill="x")

        tk.Label(hdr, text="MES CLIENT", bg=BG_HDR, fg=FG,
                 font=("Segoe UI", 10, "bold")).pack(side="left", padx=14, pady=10)

        dot_frame = tk.Frame(hdr, bg=BG_HDR)
        dot_frame.pack(side="right", padx=12, pady=10)
        tk.Label(dot_frame, text="●", bg=BG_HDR, fg=status_color,
                 font=("Segoe UI", 8)).pack(side="left")
        tk.Label(dot_frame, text=f"  {client_status}", bg=BG_HDR, fg=status_color,
                 font=("Segoe UI", 9)).pack(side="left")

        tk.Frame(inner, bg=SEP, height=1).pack(fill="x")

        # ── Helper: linha de menu ──────────────────────────────────────
        def add_item(label, cb, symbol="", fg_color=FG):
            row = tk.Frame(inner, bg=BG, cursor="hand2")
            row.pack(fill="x")
            sym_lbl = tk.Label(row, text=symbol, bg=BG, fg=FG_DIM,
                               font=("Segoe UI", 10), width=3, anchor="center")
            sym_lbl.pack(side="left", padx=(8, 2), pady=7)
            txt_lbl = tk.Label(row, text=label, bg=BG, fg=fg_color,
                               font=("Segoe UI", 10), anchor="w")
            txt_lbl.pack(side="left", fill="x", expand=True, pady=7, padx=(2, 20))

            widgets = [row, sym_lbl, txt_lbl]

            def on_enter(e):
                for w in widgets:
                    w.configure(bg=BG_HOVER)
                sym_lbl.configure(fg="#888888")

            def on_leave(e):
                for w in widgets:
                    w.configure(bg=BG)
                sym_lbl.configure(fg=FG_DIM)

            def on_click(e):
                self._close_tray_popup_win()
                if cb:
                    cb()
                return "break"  # impede propagação ao <Button-1> do popup

            for w in widgets:
                w.bind("<Enter>",    on_enter)
                w.bind("<Leave>",    on_leave)
                w.bind("<Button-1>", on_click)

        def add_sep():
            tk.Frame(inner, bg=SEP, height=1).pack(fill="x", padx=14, pady=2)

        # ── Itens ─────────────────────────────────────────────────────
        add_item("START",        self.start_clicked,  symbol="▶")
        add_item("STOP",         self.stop_clicked,   symbol="⏹")
        add_sep()
        add_item("STATUS",       self.status_clicked,    symbol="◉")
        add_item("CONFIGURAÇÃO", self.config_clicked,    symbol="⚙")
        add_item("LIMITES",      self.limites_clicked,   symbol="◈")
        add_item("MAPEAMENTO",   self.mapeamento_clicked,symbol="⇄")
        add_sep()
        add_item("AJUDA",        self.ajuda_clicked,     symbol="?")
        add_item("ABOUT",        self.about_clicked,  symbol="ⓘ")
        add_sep()
        add_item("EXIT",         self.exit_clicked,   symbol="✕", fg_color=FG_EXIT)

        tk.Frame(inner, bg=BG, height=5).pack(fill="x")

        # ── Posicionar acima do cursor (tray fica no canto inferior) ──
        popup.update_idletasks()
        pw = popup.winfo_reqwidth()
        ph = popup.winfo_reqheight()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()

        x = mx - pw // 2
        y = my - ph - 12
        x = max(0, min(x, sw - pw))
        y = max(0, min(y, sh - ph))

        popup.geometry(f"+{x}+{y}")

        # grab_set: redireciona todos os cliques do app para este popup.
        # — Clique num item do menu → evento chega ao widget filho → on_click dispara.
        # — Clique fora do popup   → evento vai para o popup (via grab) → fecha.
        # — Alt+Tab / outra app   → FocusOut fecha via root.after (root nunca some).
        popup.grab_set()
        popup.focus_force()

        popup.bind("<Button-1>", lambda e: self._close_tray_popup_win())
        popup.bind("<FocusOut>", lambda e: self.root.after(100, self._close_tray_popup_win))
        popup.bind("<Escape>",   lambda e: self._close_tray_popup_win())

    # -------------------------------------------------------------------------
    # AUTH — login na inicialização + elevação pontual de ações restritas
    # -------------------------------------------------------------------------

    def _show_login_dialog(self):
        """Mostra tela de login e define self.current_role. Retorna True se logou."""
        cfg = load_raw_config()
        auth = cfg.get("auth", {})
        op_pwd = str(auth.get("operador_password", ""))
        eng_pwd = str(auth.get("engenharia_password", "engenharia"))

        win = tk.Toplevel(self.root)
        win.title("MES Client — Login")
        win.configure(bg=self.bg_main)
        win.resizable(False, False)
        win.iconphoto(False, self._window_icon)

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w, h = 380, 340
        win.geometry(f"{w}x{h}+{(sw-w)//2}+{max(30, sh//4)}")
        win.protocol("WM_DELETE_WINDOW", lambda: os._exit(0))

        # Lista mutável como "variável de retorno" para a closure interna.
        # Closures em Python não podem reatribuir variáveis externas com '=',
        # mas podem modificar o conteúdo de uma lista. result[0] = True funciona.
        result = [False]
        role_var = tk.StringVar(value="operador")

        tk.Label(win, text="MES CLIENT", bg=self.bg_main, fg=self.fg_main,
                 font=("Segoe UI", 16, "bold")).pack(pady=(28, 2))
        tk.Label(win, text="Selecione seu perfil e entre com a senha",
                 bg=self.bg_main, fg=self.fg_secondary, font=("Segoe UI", 9)).pack(pady=(0, 20))

        card = tk.Frame(win, bg=self.bg_card, padx=24, pady=20)
        card.pack(fill="x", padx=30)

        tk.Label(card, text="Perfil:", bg=self.bg_card, fg=self.fg_secondary,
                 font=("Segoe UI", 10)).grid(row=0, column=0, sticky="w", pady=(0, 8))

        radio_frame = tk.Frame(card, bg=self.bg_card)
        radio_frame.grid(row=0, column=1, sticky="w", pady=(0, 8))

        def _on_role_change():
            if role_var.get() == "operador" and not op_pwd:
                pwd_entry.configure(state="disabled")
                pwd_entry.delete(0, tk.END)
            else:
                pwd_entry.configure(state="normal")
                pwd_entry.focus_set()

        for val, lbl in (("operador", "OPERADOR"), ("engenharia", "ENGENHARIA")):
            tk.Radiobutton(radio_frame, text=lbl, variable=role_var, value=val,
                           bg=self.bg_card, fg=self.fg_main, selectcolor=self.bg_input,
                           activebackground=self.bg_card, activeforeground=self.fg_main,
                           font=("Segoe UI", 10), command=_on_role_change).pack(side="left", padx=(0, 16))

        tk.Label(card, text="Senha:", bg=self.bg_card, fg=self.fg_secondary,
                 font=("Segoe UI", 10)).grid(row=1, column=0, sticky="w", pady=(0, 4))

        pwd_entry = tk.Entry(card, show="●", bg=self.bg_input, fg=self.fg_main,
                             insertbackground=self.fg_main, font=("Segoe UI", 11), width=22,
                             relief="flat", bd=4)
        pwd_entry.grid(row=1, column=1, sticky="ew", pady=(0, 4))

        if not op_pwd:
            pwd_entry.configure(state="disabled")

        def _enter(event=None):
            role = role_var.get()
            pwd = pwd_entry.get()
            if role == "operador":
                if op_pwd and pwd != op_pwd:
                    self._dark_msg("Senha incorreta", "Senha de OPERADOR incorreta.", kind="error", parent=win)
                    return
                self.current_role = "operador"
            else:
                if pwd != eng_pwd:
                    self._dark_msg("Senha incorreta", "Senha de ENGENHARIA incorreta.", kind="error", parent=win)
                    pwd_entry.delete(0, tk.END)
                    pwd_entry.focus_set()
                    return
                self.current_role = "engenharia"
            result[0] = True
            win.destroy()

        pwd_entry.bind("<Return>", _enter)

        btn_frame = tk.Frame(win, bg=self.bg_main)
        btn_frame.pack(pady=20)
        self._make_button(btn_frame, "ENTRAR", _enter, width=16).pack()

        tk.Label(win, text=f"Perfil ENGENHARIA tem acesso completo de edição.",
                 bg=self.bg_main, fg=self.fg_secondary, font=("Segoe UI", 8)).pack(pady=(0, 8))

        win.grab_set()
        # wait_window(): bloqueia a execução aqui até win.destroy() ser chamado.
        # O mainloop continua rodando (eventos processados), só este código espera.
        win.wait_window()
        return result[0]

    def _check_role(self, required="engenharia", action_label="esta ação", parent=None):
        """Verifica se o perfil atual tem permissão para a ação.
        Se não tiver, pede senha de ENGENHARIA (elevação pontual — sessão não muda).
        Retorna True se autorizado, False se cancelado ou senha errada."""
        if self.current_role == "engenharia":
            return True

        cfg = load_raw_config()
        eng_pwd = str(cfg.get("auth", {}).get("engenharia_password", ""))

        # parent_win: janela modal real acima de self.root (withdrawn).
        # NUNCA usar self.root como parent_win — grab_set() numa janela oculta congela a UI.
        parent_win = parent or self.active_window  # pode ser None se chamado do tray

        dlg = tk.Toplevel(self.root)
        dlg.title("Autenticação necessária")
        dlg.configure(bg=self.bg_main)
        dlg.resizable(False, False)
        try:
            dlg.iconphoto(False, self._window_icon)
        except Exception:
            pass
        # -topmost sempre: root está withdrawn, sem isso o dialog pode sumir no .exe
        dlg.attributes("-topmost", True)
        if parent_win and parent_win is not self.root:
            dlg.transient(parent_win)

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w, h = 370, 270
        dlg.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

        result = [False]

        # Painel de cabeçalho com cor de destaque
        header = tk.Frame(dlg, bg="#1a2744", height=52)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="  Acesso restrito",
                 bg="#1a2744", fg="#ffffff",
                 font=("Segoe UI", 13, "bold")).pack(side="left", padx=16, pady=14)

        tk.Label(dlg,
                 text=f"Para {action_label},\ninforme a senha de ENGENHARIA:",
                 bg=self.bg_main, fg=self.fg_secondary,
                 font=("Segoe UI", 10), justify="center").pack(pady=(16, 10))

        pwd_entry = tk.Entry(dlg, show="●", bg=self.bg_input, fg=self.fg_main,
                             insertbackground=self.fg_main, font=("Segoe UI", 12),
                             width=22, relief="flat", bd=4, justify="center")
        pwd_entry.pack(pady=(0, 4))

        err_lbl = tk.Label(dlg, text="", bg=self.bg_main, fg="#e05050",
                           font=("Segoe UI", 9))
        err_lbl.pack()

        def _confirm(event=None):
            if pwd_entry.get() == eng_pwd:
                result[0] = True
                dlg.destroy()
            else:
                err_lbl.config(text="Senha incorreta. Tente novamente.")
                pwd_entry.delete(0, tk.END)
                pwd_entry.focus_set()

        def _close_auth():
            self.auth_dialog = None
            dlg.destroy()

        pwd_entry.bind("<Return>", _confirm)
        pwd_entry.bind("<Escape>", lambda e: _close_auth())

        btn_frame = tk.Frame(dlg, bg=self.bg_main)
        btn_frame.pack(pady=(8, 0))
        self._make_button(btn_frame, "CONFIRMAR", _confirm, width=13).pack(side="left", padx=6)
        self._make_button(btn_frame, "CANCELAR", _close_auth, width=13).pack(side="left", padx=6)

        # Registra antes do grab_set para que _bind_focus_lock pare de brigar pelo foco
        self.auth_dialog = dlg

        # Libera grab do parent_win SOMENTE se for uma janela modal real (não self.root)
        if parent_win and parent_win is not self.root:
            try:
                parent_win.grab_release()
            except Exception:
                pass

        dlg.update_idletasks()   # garante renderização de todos os widgets
        dlg.lift()
        self._bring_to_front(dlg)
        dlg.grab_set()
        dlg.focus_force()
        pwd_entry.focus_set()
        dlg.protocol("WM_DELETE_WINDOW", _close_auth)
        dlg.wait_window()

        # Restaura grab/foco do parent SOMENTE se for janela modal real visível
        self.auth_dialog = None
        if parent_win and parent_win is not self.root:
            try:
                if parent_win.winfo_exists():
                    parent_win.grab_set()
                    parent_win.lift()
                    parent_win.focus_force()
            except Exception:
                pass

        return result[0]

    def _show_login_then_start(self):
        if not self._show_login_dialog():
            # os._exit(0): termina o processo imediatamente.
            # sys.exit() lançaria SystemExit que poderia ser capturado — não queremos isso
            # aqui porque o mainloop ainda não iniciou completamente.
            os._exit(0)
        self.ensure_monitor_running()
        runtime_status.set("client_status", "RUNNING")
        self.update_status_icon("green")
        # Patch: direito → popup dark; esquerdo → nada.
        # _message_handlers é um dict de instância do pystray Win32Icon criado no __init__.
        # Substituímos a entrada WM_NOTIFY para interceptar cliques antes da thread iniciar.
        # WM_LBUTTONUP=0x0202, WM_RBUTTONUP=0x0205 (constantes Win32 imutáveis).
        _app = self
        def _tray_notify(wparam, lparam):
            if lparam == 0x0205:   # WM_RBUTTONUP → popup dark
                _app.root.after(0, _app._open_tray_popup)
            # WM_LBUTTONUP (0x0202) → nada
        _orig_notify = self.icon._on_notify
        for _k, _v in list(self.icon._message_handlers.items()):
            if _v == _orig_notify:
                self.icon._message_handlers[_k] = _tray_notify
                break

        # daemon=True: a thread morre automaticamente quando o processo principal termina
        tray_thread = threading.Thread(target=self.icon.run, daemon=True)
        tray_thread.start()
        self.root.after(1500, self._startup_feedback)

    def _startup_feedback(self):
        try:
            self.icon.notify("MES Client iniciado",
                             "Parser rodando. Monitorando logs, banco e sincronização.")
        except Exception:
            pass
        self.status_clicked()
        self.root.after(12000, self._auto_close_status)

    def _auto_close_status(self):
        try:
            if self.status_window and self.status_window.winfo_exists():
                self.status_window.destroy()
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # MONITOR — gerenciamento do thread de monitoramento de arquivos
    # -------------------------------------------------------------------------

    def ensure_monitor_running(self):
        """Inicia o monitor se não estiver rodando. Idempotente — seguro chamar várias vezes."""
        if self.monitor_thread and self.monitor_thread.is_alive():
            return

        self.monitor_thread = threading.Thread(
            target=start_monitor,
            kwargs={
                "stop_event": self.stop_event,
                "status_callback": self.update_status_icon
            },
            daemon=True
        )
        self.monitor_thread.start()

    def _restart_monitor(self):
        """Sinaliza parada e agenda reinício após 1s (dá tempo da thread parar)."""
        self.stop_event.set()
        # after(1000, func): agenda func para rodar em 1000ms na main thread
        self.root.after(1000, self._do_restart_monitor)

    def _do_restart_monitor(self):
        """Reinicia o monitor com configuração atualizada do disco."""
        self.stop_event.clear()
        self.config = load_config()   # relê config.yaml — pega o que foi salvo
        self.monitor_thread = threading.Thread(
            target=start_monitor,
            kwargs={"stop_event": self.stop_event, "status_callback": self.update_status_icon},
            daemon=True
        )
        self.monitor_thread.start()
        runtime_status.set("client_status", "RUNNING")
        self.update_status_icon("green")

    # -------------------------------------------------------------------------
    # CALLBACKS DO MENU DA BANDEJA
    # Todos têm assinatura (self, icon=None, item=None) — exigência do pystray.
    # Callbacks que tocam Tkinter usam root.after(0, func) porque pystray roda
    # em thread separada e Tkinter só aceita GUI na main thread.
    # -------------------------------------------------------------------------

    def start_clicked(self, icon=None, item=None):
        self.stop_event.clear()
        self.ensure_monitor_running()
        runtime_status.set("client_status", "RUNNING")
        self.update_status_icon("green")

    def stop_clicked(self, icon=None, item=None):
        # Não chamar messagebox direto aqui — pystray está em outra thread.
        # after(0, func) envia a função para a main thread do Tkinter.
        def _do_stop():
            if not self._check_role(action_label="parar o monitor"):
                return
            self.stop_event.set()
            runtime_status.set("client_status", "STOPPED")
            self.update_status_icon("yellow")
        self.root.after(0, _do_stop)

    def status_clicked(self, icon=None, item=None):
        def _open():
            if self.status_window and self.status_window.winfo_exists():
                self.status_window.lift()
                self.status_window.focus_force()
                return

            if not self._try_open_window("STATUS"):
                return

            self.status_window = tk.Toplevel(self.root)
            _geo, _sw, _sh = self._dynamic_geometry(0.62, 0.82, 700, 560, max_w=1100, max_h=920)
            self._style_window(self.status_window, "STATUS - MES Client", _geo)
            self.status_window.protocol("WM_DELETE_WINDOW", self.status_window.destroy)
            self._register_window(self.status_window)

            header = tk.Label(
                self.status_window,
                text="STATUS DO CLIENT",
                bg=self.bg_main,
                fg=self.fg_main,
                font=("Segoe UI", 16, "bold")
            )
            header.pack(pady=(16, 6))

            sub = tk.Label(
                self.status_window,
                text="Monitoramento em tempo real da estação de teste",
                bg=self.bg_main,
                fg=self.fg_secondary,
                font=("Segoe UI", 10)
            )
            sub.pack(pady=(0, 10))

            outer = tk.Frame(self.status_window, bg=self.bg_main)
            outer.pack(fill="both", expand=True, padx=16, pady=(0, 8))

            canvas = tk.Canvas(
                outer,
                bg=self.bg_main,
                highlightthickness=0
            )

            scrollbar = tk.Scrollbar(
                outer,
                orient="vertical",
                command=canvas.yview
            )

            scroll_frame = tk.Frame(canvas, bg=self.bg_main)
            scroll_frame.columnconfigure(0, weight=0, minsize=200)
            scroll_frame.columnconfigure(1, weight=1)

            scroll_frame.bind(
                "<Configure>",
                lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
            )

            _canvas_win = canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
            canvas.bind("<Configure>", lambda e: canvas.itemconfig(_canvas_win, width=e.width))
            canvas.configure(yscrollcommand=scrollbar.set)

            canvas.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")

            fields = [
                ("client_status", "Status do Client"),
                ("db_status", "Status do Banco"),
                ("station_name", "Station"),
                ("client_version", "Versão do Client"),
                ("operation_mode", "Modo de Operação"),

                ("sync_status", "Status Sync"),
                ("sync_checked", "Sync Verificados"),
                ("sync_copied", "Sync Copiados"),
                ("sync_deleted", "Sync Removidos"),
                ("sync_last_file", "Último Arquivo Sync"),
                ("sync_last_time", "Último Sync"),

                ("files_monitored", "Arquivos Monitorados"),
                ("current_file", "Arquivo Atual"),
                ("last_file", "Último Arquivo"),
                ("last_model", "Último Modelo Detectado"),
                ("last_version", "Última Versão Detectada"),
                ("spec_mismatch_count", "Divergências de Spec"),
                ("last_batch_inserted", "Último Lote Inserido"),
                ("session_total_inserted", "Total Inserido na Sessão"),
                ("last_insert_time", "Último Insert"),
                ("last_serial", "Último Trace/Serial"),
                ("last_result", "Último PASS/FAIL"),
                ("offline_queue_count", "Fila Offline"),
                ("startup_time", "Início do Client"),
                ("last_error", "Último Erro"),
            ]

            for idx, (key, title) in enumerate(fields):
                title_lbl = tk.Label(
                    scroll_frame,
                    text=title,
                    bg=self.bg_main,
                    fg=self.fg_main,
                    font=("Segoe UI", 10, "bold"),
                    anchor="w",
                    width=25
                )
                title_lbl.grid(row=idx, column=0, padx=(0, 12), pady=6, sticky="nw")

                value_lbl = tk.Label(
                    scroll_frame,
                    text="",
                    bg=self.bg_card,
                    fg=self.fg_secondary,
                    font=("Consolas", 10),
                    anchor="w",
                    justify="left",
                    wraplength=max(300, _sw - 280),
                    padx=10,
                    pady=8,
                    relief="flat",
                    bd=1,
                )
                value_lbl.grid(row=idx, column=1, padx=0, pady=6, sticky="we")

                self.status_labels[key] = value_lbl

            footer = tk.Frame(self.status_window, bg=self.bg_main)
            footer.pack(fill="x", padx=16, pady=(8, 14))

            self._add_help_btn(footer, section="status").pack(side="left", padx=(0, 4))

            open_log_btn = self._make_button(
                footer,
                text="ABRIR LOG",
                command=self.open_log_clicked,
                width=16
            )
            open_log_btn.pack(side="left", padx=8)

            open_log_folder_btn = self._make_button(
                footer,
                text="PASTA LOG",
                command=self.open_log_folder_clicked,
                width=16
            )
            open_log_folder_btn.pack(side="left", padx=8)

            def _on_close_status():
                if not self._dark_msg(
                    "Fechar",
                    "Deseja realmente fechar a tela de Status?",
                    kind="yesno", parent=self.status_window
                ):
                    return
                self.status_window.destroy()

            self.status_window.protocol("WM_DELETE_WINDOW", _on_close_status)

            close_btn = self._make_button(
                footer,
                text="FECHAR",
                command=_on_close_status,
                width=16
            )
            close_btn.pack(side="right", padx=8)

            self._refresh_status_window()

        self.root.after(0, _open)

    def _refresh_status_window(self):
        if not self.status_window or not self.status_window.winfo_exists():
            return

        snapshot = runtime_status.snapshot()

        for key, lbl in self.status_labels.items():
            value = snapshot.get(key, "")

            if key == "last_insert_time" and value:
                try:
                    last = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
                    delta = datetime.now() - last
                    seconds = int(delta.total_seconds())
                    value = f"{value}  ({seconds}s atrás)"
                except Exception:
                    pass

            if key == "startup_time" and value:
                try:
                    started = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
                    delta = datetime.now() - started
                    seconds = int(delta.total_seconds())
                    hours = seconds // 3600
                    minutes = (seconds % 3600) // 60
                    sec = seconds % 60
                    value = f"{value}  ({hours}h {minutes}m {sec}s em execução)"
                except Exception:
                    pass

            if value is None or str(value).strip() == "":
                value = "-"

            lbl.config(text=str(value))

        self.status_window.after(1000, self._refresh_status_window)

    def open_log_clicked(self):
        log_path = os.path.join(get_base_path(), "logs", "client.log")

        if not os.path.exists(log_path):
            self._dark_msg("Log", "Arquivo de log ainda não foi criado.", kind="warning")
            return

        try:
            os.startfile(log_path)
        except Exception as e:
            self._dark_msg("Log", f"Não foi possível abrir o log:\n{e}", kind="error")

    def open_log_folder_clicked(self):
        log_dir = os.path.join(get_base_path(), "logs")
        os.makedirs(log_dir, exist_ok=True)

        try:
            os.startfile(log_dir)
        except Exception as e:
            self._dark_msg("Log", f"Não foi possível abrir a pasta de logs:\n{e}", kind="error")

    def about_clicked(self, icon=None, item=None):
        def _open():
            if self.about_window and self.about_window.winfo_exists():
                self.about_window.lift()
                self.about_window.focus_force()
                return

            if not self._try_open_window("ABOUT"):
                return

            self.about_window = tk.Toplevel(self.root)
            self._style_window(self.about_window, "About", "440x340")
            self.about_window.attributes("-topmost", True)
            # update_idletasks garante que _style_window foi processado antes do override
            self.about_window.update_idletasks()
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            # Centraliza no meio exato da tela (não no topo)
            self.about_window.geometry(f"440x340+{(sw - 440) // 2}+{(sh - 340) // 2}")
            self.about_window.protocol("WM_DELETE_WINDOW", self.about_window.destroy)
            self._register_window(self.about_window)

            tk.Label(
                self.about_window,
                text="MES CLIENT",
                bg=self.bg_main,
                fg=self.fg_main,
                font=("Segoe UI", 18, "bold")
            ).pack(pady=(20, 8))

            tk.Label(
                self.about_window,
                text=(
                    "Versão 1.0\n\n"
                    "Criado: 03-2026\n\n"
                    "Autor: Roberto Parente\n"
                    "Engenharia de Teste - Manaus\n\n"
                    "Parser universal para logs CYG / PCM Tester\n"
                    "com detecção automática de modelo e schema"
                ),
                bg=self.bg_main,
                fg=self.fg_secondary,
                justify="center",
                font=("Segoe UI", 10)
            ).pack(padx=20, pady=10)

            self._make_button(
                self.about_window,
                text="OK",
                command=self.about_window.destroy,
                width=14
            ).pack(pady=14)

        self.root.after(0, _open)

    # -------------------------------------------------------------------------
    # TELA CONFIG
    # Formulário com lógica EDITAR → edita → SALVAR → readonly.
    # load_raw_config() preserva ${MES_DB_PASSWORD} — nunca usar load_config() aqui.
    # -------------------------------------------------------------------------
    def config_clicked(self, icon=None, item=None):
        def _open():
            if self.config_window and self.config_window.winfo_exists():
                self.config_window.lift()
                self.config_window.focus_force()
                return

            if not self._try_open_window("CONFIGURAÇÃO"):
                return

            # load_raw_config: lê o YAML sem resolver variáveis de ambiente.
            # Garante que ${MES_DB_PASSWORD} permaneça como placeholder ao salvar.
            cfg = load_raw_config()

            self.config_window = tk.Toplevel(self.root)
            _geo, _cw, _ch = self._dynamic_geometry(0.58, 0.88, 720, 640, max_w=980, max_h=920)
            self._style_window(self.config_window, "Configuração", _geo)
            self.config_window.protocol("WM_DELETE_WINDOW", self.config_window.destroy)
            self._register_window(self.config_window)

            tk.Label(
                self.config_window,
                text="CONFIGURAÇÃO DO CLIENT",
                bg=self.bg_main,
                fg=self.fg_main,
                font=("Segoe UI", 16, "bold")
            ).pack(pady=(16, 6))

            tk.Label(
                self.config_window,
                text="Clique em EDITAR para habilitar alterações nos campos.",
                bg=self.bg_main,
                fg=self.fg_secondary,
                font=("Segoe UI", 9)
            ).pack(pady=(0, 6))

            # Canvas scrollável: outer → canvas + scrollbar → form (conteúdo real)
            # O 'form' é colocado dentro do canvas via create_window.
            # bind("<Configure>") atualiza o scrollregion sempre que form muda de tamanho.
            outer = tk.Frame(self.config_window, bg=self.bg_main)
            outer.pack(fill="both", expand=True, padx=16, pady=(0, 4))

            canvas    = tk.Canvas(outer, bg=self.bg_main, highlightthickness=0)
            scrollbar = tk.Scrollbar(outer, orient="vertical", command=canvas.yview)
            form      = tk.Frame(canvas, bg=self.bg_main)
            form.columnconfigure(0, weight=1)
            form.columnconfigure(1, weight=0)

            form.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
            _cwin = canvas.create_window((0, 0), window=form, anchor="nw")
            # itemconfig(_cwin, width=...) faz o form preencher toda a largura do canvas
            canvas.bind("<Configure>", lambda e: canvas.itemconfig(_cwin, width=e.width))
            canvas.configure(yscrollcommand=scrollbar.set)
            canvas.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")

            def _on_mousewheel(event):
                # event.delta: múltiplo de 120 no Windows. Divide por 120 para get "cliques"
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            canvas.bind_all("<MouseWheel>", _on_mousewheel)
            # Desvincula o MouseWheel ao fechar para não afetar outras janelas
            self.config_window.bind(
                "<Destroy>",
                lambda e: canvas.unbind_all("<MouseWheel>") if e.widget == self.config_window else None
            )

            # is_editing: lista de um elemento usada como flag mutável dentro das closures
            is_editing = [False]
            # Listas de widgets para habilitar/desabilitar em massa no EDITAR/SALVAR
            all_entries    = []
            all_browse_btns = []
            all_radios     = []

            operation_mode_var = tk.StringVar(value=cfg.get("operation", {}).get("mode", "database"))
            sync_mode_var      = tk.StringVar(value=cfg.get("sync", {}).get("mode", "diff"))

            # state: dicionário compartilhado entre as closures (save_clicked, edit_clicked).
            # "orig_op" e "orig_sync" guardam o valor original para detectar mudanças.
            state = {
                "cfg": cfg,
                "orig_op":   operation_mode_var.get(),
                "orig_sync": sync_mode_var.get(),
            }

            def add_entry(row, label_text, default_value, browse=False):
                tk.Label(
                    form,
                    text=label_text,
                    bg=self.bg_main,
                    fg=self.fg_main,
                    font=("Segoe UI", 10, "bold"),
                    anchor="w"
                ).grid(row=row, column=0, sticky="w", pady=(10, 3), columnspan=2, padx=(4, 0))

                entry = tk.Entry(
                    form,
                    readonlybackground=self.bg_card,
                    bg=self.bg_input,
                    fg=self.fg_main,
                    insertbackground=self.fg_main,
                    relief="flat",
                    bd=1,
                )
                entry.insert(0, str(default_value))
                entry.configure(state="readonly")
                entry.grid(row=row + 1, column=0, sticky="we", pady=(0, 4), padx=(4, 8))
                all_entries.append(entry)

                if browse:
                    def _browse(e=entry):
                        selected = filedialog.askdirectory(parent=self.config_window)
                        if selected:
                            e.configure(state="normal")
                            e.delete(0, tk.END)
                            e.insert(0, selected)
                            if not is_editing[0]:
                                e.configure(state="readonly")

                    btn = self._make_button(form, "Selecionar", _browse, width=11)
                    btn.configure(state="disabled")
                    btn.grid(row=row + 1, column=1, sticky="w", pady=(0, 4))
                    all_browse_btns.append(btn)

                return entry

            source_entry = add_entry(0, "Pasta origem dos logs CSV", cfg["log"]["folder"], browse=True)
            self._tooltip(source_entry, "Pasta monitorada onde o testador grava os arquivos CSV de resultado.\nEx: D:\\Data_Info\\A06")

            destination_entry = add_entry(2, "Pasta destino para sincronizar logs CSV", cfg.get("sync", {}).get("destination_folder", ""), browse=True)
            self._tooltip(destination_entry, "Destino de rede para sincronização dos arquivos CSV.\nEx: E:\\servidor_salcomp")

            scan_entry = add_entry(4, "Intervalo de leitura (s)", cfg["parser"]["scan_interval"])
            self._tooltip(scan_entry, "Frequência com que o monitor verifica novos arquivos na pasta.\nValor em segundos (padrão: 5).")

            station_entry = add_entry(6, "Station ID", cfg["station"]["id"])
            self._tooltip(station_entry, "Identificador único desta estação de teste.\nUsado para rastreabilidade no banco de dados.")

            db_host_entry = add_entry(8, "DB Host", cfg["database"]["host"])
            self._tooltip(db_host_entry, "Endereço IP ou hostname do servidor PostgreSQL.\nEx: localhost  ou  192.168.1.100")

            db_name_entry = add_entry(10, "DB Name", cfg["database"]["name"])
            self._tooltip(db_name_entry, "Nome do banco de dados PostgreSQL.\nSerá criado automaticamente se não existir.")

            db_table_entry = add_entry(12, "Tabela de resultados (INSERT)", cfg["database"].get("table", "mes_test_results"))
            self._tooltip(db_table_entry, "Nome da tabela onde os resultados de teste serão inseridos.\nSomente letras, números e underscore.")

            op_frame = tk.Frame(form, bg=self.bg_main)
            op_frame.grid(row=14, column=0, columnspan=2, sticky="w", pady=(12, 4), padx=4)
            tk.Label(op_frame, text="Modo de operação", bg=self.bg_main, fg=self.fg_main, font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 4))
            for text, val in [
                ("Banco de dados", "database"),
                ("Banco de dados + sincronizar log CSV", "both"),
                ("Sincronizar log CSV", "sync"),
            ]:
                rb = tk.Radiobutton(
                    op_frame, text=text, variable=operation_mode_var, value=val,
                    state="disabled",
                    bg=self.bg_main, fg=self.fg_secondary, selectcolor=self.bg_card,
                    activebackground=self.bg_main, activeforeground=self.fg_main,
                    disabledforeground=self.fg_secondary
                )
                rb.pack(anchor="w")
                all_radios.append(rb)

            sync_frm = tk.Frame(form, bg=self.bg_main)
            sync_frm.grid(row=15, column=0, columnspan=2, sticky="w", pady=(12, 16), padx=4)
            tk.Label(sync_frm, text="Modo de sincronização de arquivos", bg=self.bg_main, fg=self.fg_main, font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 4))
            for text, val in [
                ("Diff - copia somente diferentes", "diff"),
                ("Copy overwrite - sobrescreve tudo", "copy_overwrite"),
                ("Sync - espelha origem no destino", "sync"),
            ]:
                rb = tk.Radiobutton(
                    sync_frm, text=text, variable=sync_mode_var, value=val,
                    state="disabled",
                    bg=self.bg_main, fg=self.fg_secondary, selectcolor=self.bg_card,
                    activebackground=self.bg_main, activeforeground=self.fg_main,
                    disabledforeground=self.fg_secondary
                )
                rb.pack(anchor="w")
                all_radios.append(rb)

            footer = tk.Frame(self.config_window, bg=self.bg_main)
            footer.pack(fill="x", padx=16, pady=(6, 16))

            edit_btn  = self._make_button(footer, "EDITAR", None, width=14)
            save_btn  = self._make_button(footer, "SALVAR", None, width=14)
            close_btn = self._make_button(footer, "FECHAR", None, width=14)
            help_btn  = self._add_help_btn(footer, section="config")
            edit_btn.pack(side="left", padx=(0, 8))
            save_btn.pack(side="left", padx=8)
            help_btn.pack(side="left", padx=12)
            close_btn.pack(side="right")

            save_btn.configure(state="disabled")

            def _on_close():
                if is_editing[0]:
                    msg = (
                        "Você está no modo de edição e há campos não salvos.\n\n"
                        "Para que as alterações tenham efeito, use o botão SALVAR antes de fechar.\n\n"
                        "Deseja fechar mesmo assim? (alterações serão descartadas)"
                    )
                    title = "Fechar sem salvar"
                else:
                    msg = "Deseja realmente fechar a tela de Configuração?"
                    title = "Fechar"
                if not self._dark_msg(title, msg, kind="yesno", parent=self.config_window):
                    return
                self.config_window.destroy()

            close_btn.configure(command=_on_close)
            self.config_window.protocol("WM_DELETE_WINDOW", _on_close)

            def _reset_to_readonly():
                """Volta todos os campos para readonly após salvar ou cancelar.
                Não recarrega valores — entries já têm o valor salvo correto."""
                is_editing[0] = False
                for e in all_entries:
                    e.configure(state="readonly")
                for b in all_browse_btns:
                    b.configure(state="disabled")
                for rb in all_radios:
                    rb.configure(state="disabled")
                edit_btn.configure(state="normal")
                save_btn.configure(state="disabled")

            def edit_clicked():
                # _check_role: se for OPERADOR, pede senha de ENGENHARIA antes de liberar
                if not self._check_role(action_label="editar configurações",
                                        parent=self.config_window):
                    return
                is_editing[0] = True
                for e in all_entries:
                    e.configure(state="normal")
                for btn in all_browse_btns:
                    btn.configure(state="normal")
                for rb in all_radios:
                    rb.configure(state="normal")
                edit_btn.configure(state="disabled")
                save_btn.configure(state="normal")

            edit_btn.configure(command=edit_clicked)

            def save_clicked():
                c = state["cfg"]
                field_map = [
                    ("Pasta origem dos logs", source_entry, str(c["log"]["folder"])),
                    ("Pasta destino sync", destination_entry, str(c.get("sync", {}).get("destination_folder", ""))),
                    ("Intervalo de leitura (s)", scan_entry, str(c["parser"]["scan_interval"])),
                    ("Station ID", station_entry, str(c["station"]["id"])),
                    ("DB Host", db_host_entry, str(c["database"]["host"])),
                    ("DB Name", db_name_entry, str(c["database"]["name"])),
                    ("Tabela de resultados", db_table_entry, str(c["database"].get("table", "mes_test_results"))),
                ]

                changed = [name for name, entry, orig in field_map if entry.get().strip() != orig.strip()]

                if operation_mode_var.get() != state["orig_op"]:
                    changed.append("Modo de operação")
                if sync_mode_var.get() != state["orig_sync"]:
                    changed.append("Modo de sincronização")

                if not changed:
                    self._dark_msg("Configuração", "Nenhuma alteração foi feita.",
                                   kind="info", parent=self.config_window)
                    _reset_to_readonly()
                    return

                fields_txt = "\n".join(f"  • {n}" for n in changed)
                if not self._dark_msg(
                    "Confirmar SALVAR",
                    f"Os seguintes campos foram alterados:\n\n{fields_txt}\n\n"
                    "Deseja SALVAR? O monitor será reiniciado para aplicar as alterações.",
                    kind="yesno", parent=self.config_window
                ):
                    return

                new_cfg = load_raw_config()
                new_cfg.setdefault("operation", {})
                new_cfg.setdefault("sync", {})
                new_cfg.setdefault("database", {})
                new_cfg.setdefault("log", {})
                new_cfg.setdefault("parser", {})
                new_cfg.setdefault("station", {})

                new_cfg["log"]["folder"] = source_entry.get().strip()
                new_cfg["parser"]["scan_interval"] = int(scan_entry.get().strip() or 5)
                new_cfg["station"]["id"] = station_entry.get().strip()
                new_cfg["database"]["host"] = db_host_entry.get().strip()
                new_cfg["database"]["name"] = db_name_entry.get().strip()
                new_cfg["database"]["table"] = db_table_entry.get().strip() or "mes_test_results"
                new_cfg["operation"]["mode"] = operation_mode_var.get()
                new_cfg["sync"]["destination_folder"] = destination_entry.get().strip()
                new_cfg["sync"]["mode"] = sync_mode_var.get()
                new_cfg["sync"]["enabled"] = operation_mode_var.get() in ("sync", "both")
                new_cfg["database"]["enabled"] = operation_mode_var.get() in ("database", "both")

                save_config(new_cfg)

                fields_saved_txt = "\n".join(f"  • {n}" for n in changed)
                self._dark_msg(
                    "Configuração salva",
                    f"Campos salvos com sucesso:\n\n{fields_saved_txt}\n\n"
                    "O monitor será reiniciado para aplicar as alterações.",
                    kind="info", parent=self.config_window
                )

                state["cfg"] = load_raw_config()
                state["orig_op"] = operation_mode_var.get()
                state["orig_sync"] = sync_mode_var.get()

                _reset_to_readonly()
                self._restart_monitor()

            save_btn.configure(command=save_clicked)

        self.root.after(0, _open)

    # -------------------------------------------------------------------------
    # TELA AJUDA
    # Split pattern: ajuda_clicked (pystray-compatible) → _open_ajuda (com parâmetros).
    # AJUDA não usa _register_window — gerencia seu próprio grab e foco.
    # -------------------------------------------------------------------------

    def ajuda_clicked(self, icon=None, item=None):
        # pystray exige assinatura exata — não pode ter 'section' aqui
        self._open_ajuda()

    def _open_ajuda(self, section="geral"):
        def _open():
            # Se já está aberta, só traz ao topo (não abre duas vezes)
            if self.ajuda_window and self.ajuda_window.winfo_exists():
                self.ajuda_window.lift()
                self.ajuda_window.focus_force()
                self.ajuda_window.grab_set()
                return

            # prev_win: janela pai que estava ativa (CONFIG, STATUS, LIMITES ou None)
            # Guardamos para devolver o grab quando AJUDA for fechada.
            prev_win = self.active_window if (
                self.active_window and self.active_window.winfo_exists()
            ) else None

            self.ajuda_window = tk.Toplevel(self.root)

            # transient(): informa ao gerenciador de janelas do Windows que AJUDA
            # é filha do pai. O WM garante que AJUDA fica sempre acima do pai,
            # mesmo quando o usuário acessa o pai via taskbar ou Alt+Tab.
            if prev_win:
                self.ajuda_window.transient(prev_win)
            else:
                self.ajuda_window.transient(self.root)

            _geo, _aw, _ah = self._dynamic_geometry(0.58, 0.85, 680, 580, max_w=860, max_h=920)
            self._style_window(self.ajuda_window, "Ajuda — MES Client", _geo)

            def _close_ajuda():
                self.ajuda_window.destroy()
                self.ajuda_window = None
                # Devolve o grab ao pai para ele voltar a ser modal
                if prev_win and prev_win.winfo_exists():
                    try:
                        prev_win.grab_set()
                        prev_win.lift()
                        prev_win.focus_force()
                    except Exception:
                        pass

            self.ajuda_window.protocol("WM_DELETE_WINDOW", _close_ajuda)

            # Cadeia de grab: libera o pai → AJUDA pega → ao fechar, pai retoma
            if prev_win:
                try:
                    prev_win.grab_release()
                except Exception:
                    pass
            self.ajuda_window.grab_set()

            # Focus lock para AJUDA: mesmo padrão do _bind_focus_lock
            def _reclaim_ajuda(event=None):
                if self.ajuda_window and self.ajuda_window.winfo_exists():
                    self.ajuda_window.lift()
                    self.ajuda_window.focus_force()
            self.ajuda_window.bind(
                "<FocusOut>",
                lambda e: self.ajuda_window.after(50, _reclaim_ajuda),
                add="+"
            )

            # ── Cabeçalho ─────────────────────────────────────────────────
            hdr = tk.Frame(self.ajuda_window, bg="#1A376C", pady=14)
            hdr.pack(fill="x")
            tk.Label(hdr, text="MES CLIENT — AJUDA", bg="#1A376C", fg="#FFFFFF",
                     font=("Segoe UI", 16, "bold")).pack()
            tk.Label(hdr, text="Manual do usuário integrado  •  Pressione F1 em qualquer tela",
                     bg="#1A376C", fg="#a8c4e8", font=("Segoe UI", 9)).pack(pady=(2, 0))

            # ── Área de scroll ────────────────────────────────────────────
            outer = tk.Frame(self.ajuda_window, bg=self.bg_main)
            outer.pack(fill="both", expand=True, padx=0, pady=0)

            canvas = tk.Canvas(outer, bg=self.bg_main, highlightthickness=0)
            vsb    = tk.Scrollbar(outer, orient="vertical", command=canvas.yview,
                                  bg=self.bg_card, troughcolor=self.bg_main)
            canvas.configure(yscrollcommand=vsb.set)
            vsb.pack(side="right", fill="y")
            canvas.pack(side="left", fill="both", expand=True)

            inner = tk.Frame(canvas, bg=self.bg_main)
            _cw   = canvas.create_window((0, 0), window=inner, anchor="nw")

            canvas.bind("<Configure>",
                        lambda e: canvas.itemconfig(_cw, width=e.width))
            inner.bind("<Configure>",
                       lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
            canvas.bind_all("<MouseWheel>",
                            lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))

            # ── Helpers de renderização ───────────────────────────────────
            def sec_title(text, emoji=""):
                f = tk.Frame(inner, bg="#1e1e1e")
                f.pack(fill="x", padx=0, pady=(18, 0))
                tk.Label(f, text=f"  {emoji}  {text}" if emoji else f"  {text}",
                         bg="#1e1e1e", fg="#5a9fd4",
                         font=("Segoe UI", 12, "bold"), anchor="w").pack(
                         fill="x", padx=12, pady=8)

            def body(text):
                tk.Label(inner, text=text, bg=self.bg_main, fg=self.fg_secondary,
                         font=("Segoe UI", 10), wraplength=580,
                         justify="left", anchor="w").pack(fill="x", padx=28, pady=(4, 2))

            def item_row(label, desc, label_color="#f2f2f2"):
                row = tk.Frame(inner, bg=self.bg_main)
                row.pack(fill="x", padx=28, pady=2)
                tk.Label(row, text=label, bg=self.bg_main, fg=label_color,
                         font=("Segoe UI", 10, "bold"), width=18, anchor="w").pack(side="left")
                tk.Label(row, text=desc, bg=self.bg_main, fg=self.fg_secondary,
                         font=("Segoe UI", 10), anchor="w", wraplength=420).pack(side="left", fill="x")

            def separator():
                tk.Frame(inner, bg="#2a2a2a", height=1).pack(fill="x", padx=20, pady=6)

            def code(text):
                f = tk.Frame(inner, bg="#1a1a1a")
                f.pack(fill="x", padx=28, pady=4)
                tk.Label(f, text=text, bg="#1a1a1a", fg="#7ec8a0",
                         font=("Courier New", 9), anchor="w",
                         justify="left", padx=10, pady=6).pack(fill="x")

            # ══════════════════════════════════════════════════════════════
            # SEÇÃO: Visão Geral
            # ══════════════════════════════════════════════════════════════
            sec_title("O que é o MES Client?", "📋")
            body(
                "O MES Client é uma aplicação Windows que roda 24h/7d em estações de teste "
                "industrial. Ele monitora automaticamente arquivos CSV gerados pelos testadores "
                "(PCM Tester / CYG), processa os resultados e envia ao banco de dados PostgreSQL "
                "para rastreabilidade e análise de qualidade de produção."
            )
            separator()

            # ══════════════════════════════════════════════════════════════
            # SEÇÃO: Login e Perfis
            # ══════════════════════════════════════════════════════════════
            sec_title("Login e Perfis de Acesso", "🔐")
            body("Ao iniciar, selecione seu perfil e informe a senha correspondente:")
            item_row("OPERADOR",    "Visualização de dados e inicialização do monitor. Sem acesso a edição.", "#7ec8a0")
            item_row("ENGENHARIA",  "Acesso completo: editar CONFIG, LIMITES, STOP e EXIT.", "#5a9fd4")
            body("Quando OPERADOR tenta uma ação restrita, o sistema solicita a senha de ENGENHARIA "
                 "pontualmente — sem alterar o perfil da sessão.")
            separator()

            # ══════════════════════════════════════════════════════════════
            # SEÇÃO: Menu da Bandeja
            # ══════════════════════════════════════════════════════════════
            sec_title("Menu da Bandeja do Sistema (System Tray)", "🖥️")
            body("Clique com o botão direito no ícone da bateria na bandeja para acessar:")
            item_row("START",        "Inicia o monitoramento de arquivos e envio ao banco.")
            item_row("STOP",         "Para o monitoramento. Requer senha de ENGENHARIA.")
            item_row("STATUS",       "Abre a tela de status em tempo real da estação.")
            item_row("CONFIGURAÇÃO", "Abre as configurações do sistema (pasta, banco, sync…)")
            item_row("LIMITES",      "Editor de limites LSL/USL por passo de teste.")
            item_row("MAPEAMENTO",   "Define quais colunas do CSV correspondem a cada campo do banco.")
            item_row("AJUDA",        "Este manual (também disponível pela tecla F1).")
            item_row("ABOUT",        "Versão do software e informações do sistema.")
            item_row("EXIT",         "Encerra o aplicativo. Requer senha de ENGENHARIA.")
            separator()

            # ══════════════════════════════════════════════════════════════
            # SEÇÃO: Tela STATUS
            # ══════════════════════════════════════════════════════════════
            sec_title("Tela STATUS", "📊")
            body("Exibe o estado atual da estação em tempo real, com atualização a cada 1 segundo:")
            item_row("Cliente",       "Estado geral: RUNNING / STOPPED")
            item_row("Banco DB",      "ONLINE quando conexão com PostgreSQL ativa, OFFLINE caso contrário")
            item_row("Sync",          "Estado da sincronização de arquivos para o servidor")
            item_row("ABRIR LOG",     "Abre o arquivo de log atual no editor padrão")
            item_row("PASTA LOG",     "Abre a pasta de logs no Explorer")
            body("Cor do ícone na bandeja:  🟡 Amarelo = normal   🟢 Verde = dados enviados   🔴 Vermelho = erro")
            separator()

            # ══════════════════════════════════════════════════════════════
            # SEÇÃO: Tela CONFIGURAÇÃO
            # ══════════════════════════════════════════════════════════════
            sec_title("Tela CONFIGURAÇÃO", "⚙️")
            body("Exibe e permite editar os parâmetros do arquivo config.yaml:")
            item_row("Pasta de logs",     "Pasta monitorada onde o testador grava os CSVs de resultado.")
            item_row("Pasta destino",     "Destino de rede para sincronização dos arquivos.")
            item_row("Intervalo (s)",     "Frequência de varredura da pasta em segundos (padrão: 5).")
            item_row("Station ID",        "Identificador único desta estação de teste.")
            item_row("DB Host / Name",    "Endereço e nome do banco de dados PostgreSQL.")
            item_row("Tabela resultados", "Nome da tabela onde os resultados são inseridos.")
            item_row("Modo operação",     "database = só banco,  sync = só sync,  both = ambos.")
            item_row("Modo sync",         "diff = apenas novos,  copy = copia tudo,  sync = espelha.")
            body("Clique em EDITAR para habilitar os campos. Após alterar, clique em SALVAR — "
                 "o monitor reinicia automaticamente com as novas configurações.")
            separator()

            # ══════════════════════════════════════════════════════════════
            # SEÇÃO: Tela LIMITES
            # ══════════════════════════════════════════════════════════════
            sec_title("Tela LIMITES", "📐")
            body(
                "Editor do arquivo spec_limits.csv. Define os limites de especificação (LSL/USL) "
                "para cada passo de teste. O monitor compara automaticamente os limites do testador "
                "com os valores aqui definidos e registra divergências no banco."
            )
            item_row("Ativo",       "1 = linha habilitada,  0 = linha ignorada.")
            item_row("Modelo",      "Modelo do produto (ex: A06). Vazio = aplica a todos os modelos.")
            item_row("Chave",       "Nome interno do passo no arquivo CSV do testador.")
            item_row("Nome",        "Nome legível do passo (para relatórios).")
            item_row("LSL / USL",   "Limites inferior e superior de especificação.")
            body("Duplo clique em uma linha (modo EDITAR) para editar seus valores.")
            separator()

            # ══════════════════════════════════════════════════════════════
            # SEÇÃO: Tela MAPEAMENTO
            # ══════════════════════════════════════════════════════════════
            sec_title("Tela MAPEAMENTO", "⇄")
            body(
                "Editor do arquivo column_mappings.json. Define quais colunas do CSV "
                "correspondem a cada campo estruturado do banco (serial, resultado, tempo...). "
                "Permite adicionar suporte a novos modelos ou equipamentos sem abrir código fonte."
            )
            item_row("Modelo",          "Nome do modelo (ex: A17) ou DEFAULT para todos.")
            item_row("Campo MES",       "Campo estruturado do banco: Serial, Resultado, Modelo, Tempo de Início/Fim.")
            item_row("Colunas no CSV",  "Nomes das colunas do CSV a tentar, em ordem de prioridade.")
            body(
                "Prioridade de resolução: 1º mapeamento do modelo específico, "
                "2º DEFAULT, 3º NULL (dado completo ainda disponível em row_data JSONB)."
            )
            body(
                "Nota: o serial do PCM Tester é composto automaticamente pelo sistema "
                "(machine_no|CH{channel_no}|device_name|test_time) — formato do equipamento."
            )
            body("Duplo clique em uma linha (modo EDITAR) para editar. Alterações entram em vigor no próximo ciclo do monitor.")
            separator()

            # ══════════════════════════════════════════════════════════════
            # SEÇÃO: Arquivos de configuração
            # ══════════════════════════════════════════════════════════════
            sec_title("Arquivos de Configuração", "📄")
            body("Arquivos que controlam o comportamento do sistema:")
            item_row("config.yaml",         "Parâmetros da estação, banco, pastas, sync e senhas de perfil.")
            item_row(".env",                "Senha do banco de dados (MES_DB_PASSWORD). Nunca editar no config.yaml)")
            item_row("spec_limits.csv",     "Tabela de limites LSL/USL por passo de teste.")
            item_row("column_mappings.json","Mapeamento de colunas CSV para campos do banco (editável via MAPEAMENTO).")
            item_row("offsets.json",        "Posição de leitura de cada CSV (controle de progresso).")
            item_row("offline_queue.jsonl", "Fila de dados para reenvio quando o banco estiver offline.")
            code("MES_DB_PASSWORD=sua_senha_aqui   ← conteúdo do arquivo .env")
            separator()

            # ══════════════════════════════════════════════════════════════
            # SEÇÃO: Solução de Problemas
            # ══════════════════════════════════════════════════════════════
            sec_title("Solução de Problemas", "🔧")
            item_row("Banco OFFLINE",
                     "Verifique se o PostgreSQL está rodando e se host/porta/usuário no config.yaml estão corretos.",
                     "#e07070")
            item_row("Campos vazios no CONFIG",
                     "O config.yaml pode estar sem os campos esperados. Confira se todas as chaves existem no arquivo.",
                     "#e07070")
            item_row("Monitor não processa arquivos",
                     "Verifique se a pasta de logs existe e se o app tem permissão de leitura.",
                     "#e07070")
            item_row("App já em execução",
                     "Delete o arquivo MES_CLIENT_PARSER_TE.lock na pasta %TEMP% e tente novamente.",
                     "#e07070")
            item_row("Senha esquecida (ENGENHARIA)",
                     "Edite manualmente auth.engenharia_password no config.yaml com um editor de texto.",
                     "#e07070")
            separator()

            # ══════════════════════════════════════════════════════════════
            # SEÇÃO: Atalhos
            # ══════════════════════════════════════════════════════════════
            sec_title("Atalhos de Teclado", "⌨️")
            item_row("F1",          "Abre esta tela de Ajuda a partir de qualquer janela.")
            item_row("Enter",       "Confirma ação no campo ativo (login, edição de linha).")
            item_row("Esc",         "Fecha diálogos de edição.")
            separator()

            # ── Versão ────────────────────────────────────────────────────
            tk.Label(inner, text="MES Client v1.0  •  Engenharia de Teste — Salcomp Manaus  •  Junho 2026",
                     bg=self.bg_main, fg="#555555",
                     font=("Segoe UI", 8)).pack(pady=(16, 20))

            # ── Footer ────────────────────────────────────────────────────
            footer = tk.Frame(self.ajuda_window, bg=self.bg_main)
            footer.pack(fill="x", padx=16, pady=(4, 14))
            self._make_button(footer, "FECHAR", _close_ajuda,
                              width=14).pack(side="right")

            # Scroll para seção ao abrir
            sections_map = {
                "login":   0.10, "perfis": 0.10,
                "status":  0.35, "config": 0.45, "configuração": 0.45,
                "limites": 0.55, "arquivos": 0.65,
                "problemas": 0.75, "atalhos": 0.85,
            }
            target = sections_map.get(section.lower(), 0.0)
            if target:
                self.ajuda_window.after(200, lambda: canvas.yview_moveto(target))

        self.root.after(0, _open)

    # -------------------------------------------------------------------------
    # TELA LIMITES — editor de spec_limits.csv
    # Usa ttk.Treeview para a tabela e _open_row_dialog para editar cada linha.
    # Mesma lógica EDITAR/SALVAR/readonly da tela CONFIG.
    # -------------------------------------------------------------------------
    def limites_clicked(self, icon=None, item=None):
        def _open():
            if not self._try_open_window("LIMITES"):
                return

            cfg_raw = load_raw_config()
            spec_fname = cfg_raw.get("spec_check", {}).get("file", "spec_limits.csv")
            spec_path = os.path.join(get_base_path(), spec_fname)
            fieldnames = ["enabled", "model", "step_key", "step_name", "unit", "lsl", "usl"]

            rows = []
            if os.path.exists(spec_path):
                with open(spec_path, "r", encoding="utf-8-sig", newline="") as f:
                    for row in _csv.DictReader(f):
                        rows.append([row.get(k, "") for k in fieldnames])

            self.limites_window = tk.Toplevel(self.root)
            _geo, _lw, _lh = self._dynamic_geometry(0.75, 0.72, 860, 480, max_w=1200, max_h=780)
            self._style_window(self.limites_window, "Limites de Especificação", _geo)
            self.limites_window.protocol("WM_DELETE_WINDOW", self.limites_window.destroy)
            self._register_window(self.limites_window)

            tk.Label(self.limites_window, text="LIMITES DE ESPECIFICAÇÃO",
                     bg=self.bg_main, fg=self.fg_main,
                     font=("Segoe UI", 16, "bold")).pack(pady=(16, 2))
            role_lbl = "ENGENHARIA — edição habilitada" if self.current_role == "engenharia" else "OPERADOR — somente visualização"
            tk.Label(self.limites_window, text=role_lbl,
                     bg=self.bg_main, fg=self.fg_secondary,
                     font=("Segoe UI", 9)).pack(pady=(0, 8))

            # Treeview styling
            style = ttk.Style()
            style.theme_use("clam")
            style.configure("Limites.Treeview",
                background=self.bg_card, foreground=self.fg_main,
                fieldbackground=self.bg_card, rowheight=26,
                font=("Segoe UI", 10))
            style.configure("Limites.Treeview.Heading",
                background=self.bg_input, foreground=self.fg_main,
                font=("Segoe UI", 10, "bold"), relief="flat")
            style.map("Limites.Treeview",
                background=[("selected", "#3a4a3a")],
                foreground=[("selected", self.fg_main)])

            tree_frame = tk.Frame(self.limites_window, bg=self.bg_main)
            tree_frame.pack(fill="both", expand=True, padx=16, pady=(0, 4))

            col_headers = ("Ativo", "Modelo", "Chave", "Nome do Passo", "Unidade", "LSL", "USL")
            col_widths   = (52, 80, 100, 220, 70, 80, 80)
            col_anchor   = ("center", "w", "w", "w", "center", "center", "center")

            tree = ttk.Treeview(tree_frame, columns=fieldnames, show="headings",
                                style="Limites.Treeview", selectmode="browse")
            for cid, hdr, w, anc in zip(fieldnames, col_headers, col_widths, col_anchor):
                tree.heading(cid, text=hdr)
                tree.column(cid, width=w, anchor=anc, minwidth=w)

            vsb = tk.Scrollbar(tree_frame, orient="vertical", command=tree.yview,
                               bg=self.bg_card, troughcolor=self.bg_main)
            tree.configure(yscrollcommand=vsb.set)
            tree.pack(side="left", fill="both", expand=True)
            vsb.pack(side="right", fill="y")

            is_editing = [False]

            def _refresh_tree():
                for item in tree.get_children():
                    tree.delete(item)
                for i, row in enumerate(rows):
                    display = list(row)
                    display[0] = "✓" if row[0] in ("1", "true", "TRUE", "yes") else "✗"
                    tree.insert("", "end", iid=str(i), values=display)

            _refresh_tree()

            # Footer
            footer = tk.Frame(self.limites_window, bg=self.bg_main)
            footer.pack(fill="x", padx=16, pady=(4, 14))

            edit_btn  = self._make_button(footer, "EDITAR", None, width=13)
            save_btn  = self._make_button(footer, "SALVAR", None, width=13)
            add_btn   = self._make_button(footer, "NOVA LINHA", None, width=13)
            del_btn   = self._make_button(footer, "DELETAR", None, width=13)
            close_btn = self._make_button(footer, "FECHAR", None, width=13)

            edit_btn.pack(side="left", padx=(0, 6))
            save_btn.pack(side="left", padx=6)
            add_btn.pack(side="left",  padx=6)
            del_btn.pack(side="left",  padx=6)
            close_btn.pack(side="right")
            self._add_help_btn(footer, section="limites").pack(side="right", padx=(0, 6))

            save_btn.configure(state="disabled")
            add_btn.configure(state="disabled")
            del_btn.configure(state="disabled")

            def _open_row_dialog(row_data=None, title="Editar Linha"):
                dlg = tk.Toplevel(self.limites_window)
                dlg.title(title)
                dlg.configure(bg=self.bg_main)
                dlg.resizable(False, False)
                dlg.iconphoto(False, self._window_icon)
                dlg.transient(self.limites_window)

                if row_data is None:
                    row_data = ["1", "", "", "", "", "", ""]

                result = [None]
                labels = ["Ativo (1=sim / 0=não)", "Modelo", "Chave (step_key)",
                          "Nome do Passo", "Unidade", "LSL", "USL"]
                entries = []

                for i, (lbl, val) in enumerate(zip(labels, row_data)):
                    tk.Label(dlg, text=lbl, bg=self.bg_main, fg=self.fg_secondary,
                             font=("Segoe UI", 10), anchor="w").grid(
                             row=i, column=0, padx=(16, 8), pady=5, sticky="w")
                    e = tk.Entry(dlg, bg=self.bg_input, fg=self.fg_main,
                                 insertbackground=self.fg_main, font=("Segoe UI", 10),
                                 width=28, relief="flat", bd=4)
                    e.insert(0, str(val))
                    e.grid(row=i, column=1, padx=(0, 16), pady=5, sticky="ew")
                    entries.append(e)

                def on_ok(event=None):
                    vals = [e.get().strip() for e in entries]
                    if vals[0] not in ("0", "1"):
                        self._dark_msg("Valor inválido", "Campo 'Ativo' deve ser 0 ou 1.",
                                       kind="warning", parent=dlg)
                        return
                    result[0] = vals
                    dlg.destroy()

                entries[-1].bind("<Return>", on_ok)
                btn_f = tk.Frame(dlg, bg=self.bg_main)
                btn_f.grid(row=len(labels), column=0, columnspan=2, pady=12)
                self._make_button(btn_f, "OK", on_ok, width=12).pack(side="left", padx=8)
                self._make_button(btn_f, "Cancelar", dlg.destroy, width=12).pack(side="left", padx=8)

                dlg.update_idletasks()
                px = self.limites_window.winfo_x() + (self.limites_window.winfo_width()  - dlg.winfo_width())  // 2
                py = self.limites_window.winfo_y() + (self.limites_window.winfo_height() - dlg.winfo_height()) // 2
                dlg.geometry(f"+{px}+{py}")
                dlg.grab_set()
                dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
                dlg.wait_window()
                return result[0]

            def edit_clicked():
                if not self._check_role(action_label="editar limites de especificação",
                                        parent=self.limites_window):
                    return
                is_editing[0] = True
                edit_btn.configure(state="disabled")
                save_btn.configure(state="normal")
                add_btn.configure(state="normal")
                del_btn.configure(state="normal")

            def on_double_click(event):
                if not is_editing[0]:
                    return
                sel = tree.selection()
                if not sel:
                    return
                idx = int(sel[0])
                new_row = _open_row_dialog(rows[idx], "Editar Linha")
                if new_row is not None:
                    rows[idx] = new_row
                    _refresh_tree()
                    tree.selection_set(str(idx))

            tree.bind("<Double-1>", on_double_click)

            def add_row():
                new_row = _open_row_dialog(title="Nova Linha")
                if new_row is not None:
                    rows.append(new_row)
                    _refresh_tree()
                    tree.selection_set(str(len(rows) - 1))

            def del_row():
                sel = tree.selection()
                if not sel:
                    self._dark_msg("Aviso", "Selecione uma linha para deletar.",
                                   kind="warning", parent=self.limites_window)
                    return
                idx = int(sel[0])
                if self._dark_msg("Confirmar exclusão",
                        f"Deletar linha {idx + 1}: '{rows[idx][3] or rows[idx][2]}'?",
                        kind="yesno", parent=self.limites_window):
                    rows.pop(idx)
                    _refresh_tree()

            def _reset_limites():
                is_editing[0] = False
                if self.current_role == "engenharia":
                    edit_btn.configure(state="normal")
                save_btn.configure(state="disabled")
                add_btn.configure(state="disabled")
                del_btn.configure(state="disabled")

            def save_clicked():
                try:
                    with open(spec_path, "w", encoding="utf-8", newline="") as f:
                        writer = _csv.writer(f)
                        writer.writerow(fieldnames)
                        for row in rows:
                            writer.writerow(row)
                    self._dark_msg("Salvo", f"{len(rows)} linha(s) salva(s) com sucesso.",
                                   kind="info", parent=self.limites_window)
                    _reset_limites()
                except Exception as ex:
                    self._dark_msg("Erro", f"Não foi possível salvar:\n{ex}",
                                   kind="error", parent=self.limites_window)

            def _on_close():
                if is_editing[0]:
                    msg = ("Você está no modo de edição com alterações não salvas.\n\n"
                           "Deseja fechar mesmo assim? (alterações serão descartadas)")
                    title = "Fechar sem salvar"
                else:
                    msg = "Deseja realmente fechar a tela de Limites?"
                    title = "Fechar"
                if not self._dark_msg(title, msg, kind="yesno", parent=self.limites_window):
                    return
                self.limites_window.destroy()

            self.limites_window.protocol("WM_DELETE_WINDOW", _on_close)
            edit_btn.configure(command=edit_clicked)
            save_btn.configure(command=save_clicked)
            add_btn.configure(command=add_row)
            del_btn.configure(command=del_row)
            close_btn.configure(command=_on_close)

        self.root.after(0, _open)

    # -------------------------------------------------------------------------
    # TELA MAPEAMENTO — editor de column_mappings.json
    # Define quais colunas do CSV correspondem a cada campo estruturado do banco.
    # Usa ttk.Treeview flattened: (Modelo, Campo MES, Colunas CSV).
    # -------------------------------------------------------------------------
    def mapeamento_clicked(self, icon=None, item=None):
        def _open():
            if not self._try_open_window("MAPEAMENTO"):
                return

            from config.column_mapper import load_mappings, save_mappings, STRUCTURED_FIELDS

            mappings = load_mappings()

            # Flatten JSON {modelo: {campo: [cols]}} → lista de [modelo, campo, cols_str]
            rows = []
            for model_key, fields in mappings.items():
                for field_key, col_list in fields.items():
                    if isinstance(col_list, list):
                        col_str = ", ".join(col_list)
                    else:
                        col_str = str(col_list)
                    rows.append([model_key, field_key, col_str])

            # DEFAULT primeiro, depois ordena por modelo e campo
            rows.sort(key=lambda r: (0 if r[0] == "DEFAULT" else 1, r[0], r[1]))

            self.mapeamento_window = tk.Toplevel(self.root)
            _geo, _lw, _lh = self._dynamic_geometry(0.82, 0.70, 960, 520, max_w=1400, max_h=840)
            self._style_window(self.mapeamento_window, "Mapeamento de Colunas CSV", _geo)
            self.mapeamento_window.protocol("WM_DELETE_WINDOW", self.mapeamento_window.destroy)
            self._register_window(self.mapeamento_window)

            tk.Label(self.mapeamento_window, text="MAPEAMENTO DE COLUNAS CSV",
                     bg=self.bg_main, fg=self.fg_main,
                     font=("Segoe UI", 16, "bold")).pack(pady=(16, 2))
            role_lbl = ("ENGENHARIA — edição habilitada"
                        if self.current_role == "engenharia"
                        else "OPERADOR — somente visualização")
            tk.Label(self.mapeamento_window, text=role_lbl,
                     bg=self.bg_main, fg=self.fg_secondary,
                     font=("Segoe UI", 9)).pack(pady=(0, 2))
            tk.Label(self.mapeamento_window,
                     text="Define quais colunas do CSV correspondem a cada campo do banco. "
                          "Alterações entram em vigor no próximo ciclo do monitor.",
                     bg=self.bg_main, fg=self.fg_secondary,
                     font=("Segoe UI", 9)).pack(pady=(0, 8))

            # ── Treeview ─────────────────────────────────────────────────────
            style = ttk.Style()
            style.theme_use("clam")
            style.configure("Map.Treeview",
                background=self.bg_card, foreground=self.fg_main,
                fieldbackground=self.bg_card, rowheight=26,
                font=("Segoe UI", 10))
            style.configure("Map.Treeview.Heading",
                background=self.bg_input, foreground=self.fg_main,
                font=("Segoe UI", 10, "bold"), relief="flat")
            style.map("Map.Treeview",
                background=[("selected", "#3a4a3a")],
                foreground=[("selected", self.fg_main)])

            tree_frame = tk.Frame(self.mapeamento_window, bg=self.bg_main)
            tree_frame.pack(fill="both", expand=True, padx=16, pady=(0, 4))

            col_ids     = ("model", "field", "columns")
            col_headers = ("Modelo", "Campo MES", "Colunas no CSV (separadas por vírgula)")
            col_widths  = (130, 190, 530)
            col_anchor  = ("w", "w", "w")

            tree = ttk.Treeview(tree_frame, columns=col_ids, show="headings",
                                style="Map.Treeview", selectmode="browse")
            for cid, hdr, w, anc in zip(col_ids, col_headers, col_widths, col_anchor):
                tree.heading(cid, text=hdr)
                tree.column(cid, width=w, anchor=anc, minwidth=w)

            vsb = tk.Scrollbar(tree_frame, orient="vertical", command=tree.yview,
                               bg=self.bg_card, troughcolor=self.bg_main)
            tree.configure(yscrollcommand=vsb.set)
            tree.pack(side="left", fill="both", expand=True)
            vsb.pack(side="right", fill="y")

            is_editing = [False]

            field_options = list(STRUCTURED_FIELDS.keys())
            field_labels  = [STRUCTURED_FIELDS[k] for k in field_options]

            def _refresh_tree():
                for item in tree.get_children():
                    tree.delete(item)
                for i, row in enumerate(rows):
                    label = STRUCTURED_FIELDS.get(row[1], row[1])
                    tree.insert("", "end", iid=str(i), values=(row[0], label, row[2]))

            _refresh_tree()

            # ── Footer ────────────────────────────────────────────────────────
            footer = tk.Frame(self.mapeamento_window, bg=self.bg_main)
            footer.pack(fill="x", padx=16, pady=(4, 14))

            edit_btn  = self._make_button(footer, "EDITAR",    None, width=13)
            save_btn  = self._make_button(footer, "SALVAR",    None, width=13)
            add_btn   = self._make_button(footer, "ADICIONAR", None, width=13)
            del_btn   = self._make_button(footer, "DELETAR",   None, width=13)
            close_btn = self._make_button(footer, "FECHAR",    None, width=13)

            edit_btn.pack(side="left", padx=(0, 6))
            save_btn.pack(side="left", padx=6)
            add_btn.pack(side="left",  padx=6)
            del_btn.pack(side="left",  padx=6)
            close_btn.pack(side="right")

            save_btn.configure(state="disabled")
            add_btn.configure(state="disabled")
            del_btn.configure(state="disabled")

            # ── Diálogo de edição / criação de linha ─────────────────────────
            def _open_row_dialog(row_data=None, title="Adicionar Mapeamento"):
                dlg = tk.Toplevel(self.mapeamento_window)
                dlg.title(title)
                dlg.configure(bg=self.bg_main)
                dlg.resizable(False, False)
                dlg.iconphoto(False, self._window_icon)
                dlg.transient(self.mapeamento_window)

                if row_data is None:
                    row_data = ["DEFAULT", "serial_number", ""]

                result = [None]

                # Modelo
                tk.Label(dlg, text="Modelo  (DEFAULT = todos; ou nome específico, ex: A17)",
                         bg=self.bg_main, fg=self.fg_secondary,
                         font=("Segoe UI", 10), anchor="w").grid(
                         row=0, column=0, padx=(16, 8), pady=(14, 5), sticky="w")
                model_var = tk.StringVar(value=row_data[0])
                tk.Entry(dlg, textvariable=model_var, bg=self.bg_input, fg=self.fg_main,
                         insertbackground=self.fg_main, font=("Segoe UI", 10),
                         width=32, relief="flat", bd=4).grid(
                         row=0, column=1, padx=(0, 16), pady=(14, 5), sticky="ew")

                # Campo MES (combobox)
                tk.Label(dlg, text="Campo MES",
                         bg=self.bg_main, fg=self.fg_secondary,
                         font=("Segoe UI", 10), anchor="w").grid(
                         row=1, column=0, padx=(16, 8), pady=5, sticky="w")
                field_var = tk.StringVar(value=STRUCTURED_FIELDS.get(row_data[1], row_data[1]))
                field_combo = ttk.Combobox(dlg, textvariable=field_var, values=field_labels,
                                           state="readonly", font=("Segoe UI", 10), width=30)
                field_combo.grid(row=1, column=1, padx=(0, 16), pady=5, sticky="ew")

                # Colunas no CSV
                tk.Label(dlg, text="Colunas no CSV  (separadas por vírgula)",
                         bg=self.bg_main, fg=self.fg_secondary,
                         font=("Segoe UI", 10), anchor="w").grid(
                         row=2, column=0, padx=(16, 8), pady=5, sticky="w")
                cols_var = tk.StringVar(value=row_data[2])
                cols_entry = tk.Entry(dlg, textvariable=cols_var, bg=self.bg_input, fg=self.fg_main,
                                      insertbackground=self.fg_main, font=("Segoe UI", 10),
                                      width=44, relief="flat", bd=4)
                cols_entry.grid(row=2, column=1, padx=(0, 16), pady=5, sticky="ew")

                def on_ok(event=None):
                    model_val      = model_var.get().strip()
                    field_lbl_val  = field_var.get().strip()
                    cols_val       = cols_var.get().strip()

                    if not model_val:
                        self._dark_msg("Campo obrigatório",
                                       "Modelo não pode ser vazio.\nUse 'DEFAULT' para todos os modelos.",
                                       kind="warning", parent=dlg)
                        return
                    if not field_lbl_val:
                        self._dark_msg("Campo obrigatório",
                                       "Selecione um Campo MES.",
                                       kind="warning", parent=dlg)
                        return
                    if not cols_val:
                        self._dark_msg("Campo obrigatório",
                                       "Informe ao menos uma coluna CSV.",
                                       kind="warning", parent=dlg)
                        return

                    try:
                        field_key = field_options[field_labels.index(field_lbl_val)]
                    except (ValueError, IndexError):
                        field_key = field_lbl_val

                    result[0] = [model_val, field_key, cols_val]
                    dlg.destroy()

                cols_entry.bind("<Return>", on_ok)
                btn_f = tk.Frame(dlg, bg=self.bg_main)
                btn_f.grid(row=3, column=0, columnspan=2, pady=12)
                self._make_button(btn_f, "OK",       on_ok,       width=12).pack(side="left", padx=8)
                self._make_button(btn_f, "Cancelar", dlg.destroy, width=12).pack(side="left", padx=8)

                dlg.update_idletasks()
                px = (self.mapeamento_window.winfo_x()
                      + (self.mapeamento_window.winfo_width()  - dlg.winfo_width())  // 2)
                py = (self.mapeamento_window.winfo_y()
                      + (self.mapeamento_window.winfo_height() - dlg.winfo_height()) // 2)
                dlg.geometry(f"+{px}+{py}")
                dlg.grab_set()
                dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
                dlg.wait_window()
                return result[0]

            # ── Handlers dos botões ───────────────────────────────────────────
            def edit_clicked():
                if not self._check_role(action_label="editar mapeamento de colunas",
                                        parent=self.mapeamento_window):
                    return
                is_editing[0] = True
                edit_btn.configure(state="disabled")
                save_btn.configure(state="normal")
                add_btn.configure(state="normal")
                del_btn.configure(state="normal")

            def on_double_click(event):
                if not is_editing[0]:
                    return
                sel = tree.selection()
                if not sel:
                    return
                idx = int(sel[0])
                new_row = _open_row_dialog(rows[idx], "Editar Mapeamento")
                if new_row is not None:
                    rows[idx] = new_row
                    _refresh_tree()
                    tree.selection_set(str(idx))

            tree.bind("<Double-1>", on_double_click)

            def add_row():
                new_row = _open_row_dialog(title="Adicionar Mapeamento")
                if new_row is not None:
                    rows.append(new_row)
                    _refresh_tree()
                    tree.selection_set(str(len(rows) - 1))

            def del_row():
                sel = tree.selection()
                if not sel:
                    self._dark_msg("Aviso", "Selecione uma linha para deletar.",
                                   kind="warning", parent=self.mapeamento_window)
                    return
                idx = int(sel[0])
                is_default = rows[idx][0] == "DEFAULT"
                field_lbl  = STRUCTURED_FIELDS.get(rows[idx][1], rows[idx][1])
                msg = (
                    f"Você está deletando um mapeamento DEFAULT.\n"
                    f"Campo '{field_lbl}' ficará NULL para modelos sem mapeamento específico.\n\nConfirmar?"
                    if is_default else
                    f"Deletar mapeamento: {rows[idx][0]} / {field_lbl}?"
                )
                if not self._dark_msg("Confirmar exclusão", msg,
                                      kind="yesno", parent=self.mapeamento_window):
                    return
                rows.pop(idx)
                _refresh_tree()

            def _reset_mapeamento():
                is_editing[0] = False
                edit_btn.configure(state="normal")
                save_btn.configure(state="disabled")
                add_btn.configure(state="disabled")
                del_btn.configure(state="disabled")

            def save_clicked():
                try:
                    new_mappings = {}
                    for row in rows:
                        model_key, field_key, cols_str = row
                        col_list = [c.strip() for c in cols_str.split(",") if c.strip()]
                        if model_key not in new_mappings:
                            new_mappings[model_key] = {}
                        new_mappings[model_key][field_key] = col_list
                    save_mappings(new_mappings)
                    self._dark_msg("Salvo",
                                   f"{len(rows)} mapeamento(s) salvo(s). "
                                   "O monitor usará a nova configuração no próximo ciclo.",
                                   kind="info", parent=self.mapeamento_window)
                    _reset_mapeamento()
                except Exception as ex:
                    self._dark_msg("Erro", f"Não foi possível salvar:\n{ex}",
                                   kind="error", parent=self.mapeamento_window)

            def _on_close():
                if is_editing[0]:
                    msg   = ("Você está no modo de edição com alterações não salvas.\n\n"
                             "Deseja fechar mesmo assim? (alterações serão descartadas)")
                    title = "Fechar sem salvar"
                else:
                    msg   = "Deseja realmente fechar a tela de Mapeamento?"
                    title = "Fechar"
                if not self._dark_msg(title, msg, kind="yesno", parent=self.mapeamento_window):
                    return
                self.mapeamento_window.destroy()

            self.mapeamento_window.protocol("WM_DELETE_WINDOW", _on_close)
            edit_btn.configure(command=edit_clicked)
            save_btn.configure(command=save_clicked)
            add_btn.configure(command=add_row)
            del_btn.configure(command=del_row)
            close_btn.configure(command=_on_close)

        self.root.after(0, _open)

    def exit_clicked(self, icon=None, item=None):
        # Vem do pystray (outra thread) → usar after(0, ...) para rodar na main thread
        def _confirm_exit():
            if not self._check_role(action_label="fechar o aplicativo"):
                return

            # Dialog de confirmação customizado — evita messagebox com root withdrawn
            # que some imediatamente no .exe compilado (PyInstaller + console=False).
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            w, h = 410, 190
            dlg = tk.Toplevel(self.root)
            dlg.title("Confirmar saída")
            dlg.configure(bg="#141414")
            dlg.resizable(False, False)
            dlg.attributes("-topmost", True)
            dlg.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
            try:
                dlg.iconphoto(False, self._window_icon)
            except Exception:
                pass

            result = [False]

            tk.Label(
                dlg,
                text="Deseja realmente encerrar o MES Client?\n\n"
                     "Ele foi projetado para funcionar 24 h/dia\n"
                     "e iniciar automaticamente com o Windows.",
                bg="#141414", fg="#e2e2e2",
                font=("Segoe UI", 10), justify="center", wraplength=370
            ).pack(pady=24)

            btn_f = tk.Frame(dlg, bg="#141414")
            btn_f.pack(pady=(0, 20))

            def _yes():
                result[0] = True
                dlg.destroy()

            def _no():
                dlg.destroy()

            tk.Button(
                btn_f, text="SIM, ENCERRAR", command=_yes,
                bg="#7a1c1c", fg="white", font=("Segoe UI", 10, "bold"),
                activebackground="#9e2424", activeforeground="white",
                relief="flat", padx=16, pady=7, cursor="hand2", bd=0
            ).pack(side="left", padx=10)
            tk.Button(
                btn_f, text="CANCELAR", command=_no,
                bg="#2d2d2d", fg="#e2e2e2", font=("Segoe UI", 10),
                activebackground="#3a3a3a", activeforeground="#e2e2e2",
                relief="flat", padx=16, pady=7, cursor="hand2", bd=0
            ).pack(side="left", padx=10)

            self._bring_to_front(dlg)
            dlg.grab_set()
            dlg.focus_force()
            dlg.protocol("WM_DELETE_WINDOW", _no)
            dlg.wait_window()

            if result[0]:
                self.stop_event.set()
                try:
                    self.icon.stop()
                except Exception:
                    pass
                os._exit(0)

        self.root.after(0, _confirm_exit)

    # -------------------------------------------------------------------------
    # ENTRY POINT
    # -------------------------------------------------------------------------
    def run(self):
        # after(0, ...) agenda o login para APÓS o mainloop iniciar.
        # Sem isso, wait_window() dentro do login travaria antes do loop começar.
        self.root.after(0, self._show_login_then_start)
        self.root.mainloop()


if __name__ == "__main__":
    instance = SingleInstance("MES_CLIENT_PARSER_TE")

    root = tk.Tk()
    root.withdraw()

    if not instance.acquire():
        # Dialog dark inline — MESClientApp ainda não foi criado
        dlg = tk.Toplevel(root)
        dlg.title("MES Client")
        dlg.configure(bg="#141414")
        dlg.resizable(False, False)
        dlg.attributes("-topmost", True)
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        w, h = 460, 148
        dlg.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
        hdr = tk.Frame(dlg, bg="#3a2d00", height=38)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="  ⚠   MES Client", bg="#3a2d00", fg="#ffbb33",
                 font=("Segoe UI", 10, "bold")).pack(side="left", padx=8, pady=9)
        tk.Label(dlg,
                 text="Já existe uma instância do parser em execução nesta estação.",
                 bg="#141414", fg="#e2e2e2", font=("Segoe UI", 10),
                 justify="center", wraplength=420).pack(pady=16)
        tk.Button(dlg, text="OK", command=dlg.destroy,
                  bg="#2d2d2d", fg="#e2e2e2", font=("Segoe UI", 10),
                  relief="flat", padx=28, pady=6, cursor="hand2", bd=0).pack()
        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        dlg.grab_set()
        dlg.focus_force()
        dlg.wait_window()
        root.destroy()
        os._exit(0)

    root.destroy()

    app = MESClientUI()
    app.run()