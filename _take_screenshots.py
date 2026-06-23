"""
_take_screenshots.py
Captura automatica das telas do MES Client para o README.
Roda sem pystray real, sem monitor -- so renderiza as janelas e fotografa.
"""
import os, sys, time, ctypes, ctypes.wintypes
import tkinter as tk

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ── Win+D: minimiza TUDO e exibe a area de trabalho limpa ─────────────────
def _show_desktop():
    u32 = ctypes.windll.user32
    VK_LWIN, VK_D, UP = 0x5B, 0x44, 0x0002
    u32.keybd_event(VK_LWIN, 0, 0,  0)
    u32.keybd_event(VK_D,    0, 0,  0)
    u32.keybd_event(VK_D,    0, UP, 0)
    u32.keybd_event(VK_LWIN, 0, UP, 0)

_show_desktop()
time.sleep(1.0)   # aguarda animacao de minimizacao

OUT = os.path.join(ROOT, "assets", "screenshots")
os.makedirs(OUT, exist_ok=True)

# ── patch pystray ANTES de importar ui_main ───────────────────────────────
import pystray as _pystray

class _FakeIcon:
    def __init__(self, name, image=None, title=None, menu=None, **kw):
        self.name  = name
        self.title = title or name
        self._message_handlers = {}
        self._on_notify = lambda *a: None
    def stop(self): pass
    def run(self):  pass

_pystray.Icon = _FakeIcon

from system.ui_main import MESClientUI
from PIL import ImageGrab


# ── helpers ───────────────────────────────────────────────────────────────

def pump(app, n=25):
    for _ in range(n):
        try:   app.root.update()
        except tk.TclError: break
        time.sleep(0.02)

def snap(win, name, app, pad=2):
    try:
        win.attributes("-topmost", True)
        win.lift()
        app.root.update(); app.root.update_idletasks()
        time.sleep(0.4)
        x = win.winfo_rootx() - pad
        y = win.winfo_rooty() - pad
        w = win.winfo_width()  + pad * 2
        h = win.winfo_height() + pad * 2
        img = ImageGrab.grab(bbox=(max(0,x), max(0,y), x+w, y+h))
        img.save(os.path.join(OUT, name))
        print(f"  OK  {name}")
    except Exception as e:
        print(f"  ERR {name}: {e}")

def find_toplevel(app, *title_fragments):
    for w in app.root.winfo_children():
        if not isinstance(w, tk.Toplevel): continue
        try:
            t = w.title()
            if any(f in t for f in title_fragments):
                return w
        except Exception:
            pass
    return None

def reset(app):
    if app.active_window:
        try:
            if app.active_window.winfo_exists():
                app.active_window.grab_release()
                app.active_window.destroy()
        except Exception: pass
    app.active_window = None
    for attr in ("status_window","config_window","about_window",
                 "limites_window","ajuda_window","_tray_popup_win"):
        try: setattr(app, attr, None)
        except Exception: pass


# ── cria instancia ────────────────────────────────────────────────────────
print("\nIniciando MES Client em modo screenshot...")
app = MESClientUI()
app.current_role = "engenharia"
pump(app, 15)


# ── 1. LOGIN ──────────────────────────────────────────────────────────────
print("\n[1/6] Login")

def _close_login():
    w = find_toplevel(app, "Login")
    if w:
        snap(w, "login.png", app)
        w.destroy()
    else:
        app.root.after(120, _close_login)

app.root.after(700, _close_login)
try:
    app._show_login_dialog()
except Exception:
    pass
pump(app, 10)


# ── 2. AUTH DIALOG ────────────────────────────────────────────────────────
print("[2/6] Auth dialog (acesso restrito)")
reset(app)
app.current_role = None

def _close_auth():
    w = find_toplevel(app, "Autenticação", "necessária", "restrito", "Acesso")
    if w:
        snap(w, "auth.png", app)
        w.destroy()
    else:
        app.root.after(120, _close_auth)

app.root.after(700, _close_auth)
try:
    app._check_role(action_label="demonstração")
except Exception:
    pass
app.current_role = "engenharia"
pump(app, 10)


# ── 3. STATUS ─────────────────────────────────────────────────────────────
print("[3/6] STATUS")
reset(app)
app.status_clicked()
pump(app, 40)

win = app.status_window
if win and win.winfo_exists():
    snap(win, "status.png", app)
    win.destroy()
reset(app)
pump(app, 5)


# ── 4. CONFIG ─────────────────────────────────────────────────────────────
print("[4/6] CONFIG")
reset(app)
app.config_clicked()
pump(app, 40)

win = app.config_window
if win and win.winfo_exists():
    snap(win, "config.png", app)
    win.destroy()
reset(app)
pump(app, 5)


# ── 5. EXIT CONFIRM ───────────────────────────────────────────────────────
print("[5/6] Confirmacao de saida (EXIT)")
reset(app)

# Bypass da verificacao de perfil para a janela de exit aparecer
_orig_check = app._check_role
app._check_role = lambda *a, **kw: True

def _close_exit():
    w = find_toplevel(app, "Confirmar", "saída", "encerrar", "sair")
    if w:
        snap(w, "exit_confirm.png", app)
        w.destroy()
    else:
        app.root.after(120, _close_exit)

app.root.after(700, _close_exit)
try:
    app.exit_clicked()
except SystemExit:
    pass
except Exception:
    pass

pump(app, 60)
app._check_role = _orig_check
reset(app)
pump(app, 5)


# ── 6. TRAY POPUP ─────────────────────────────────────────────────────────
print("[6/6] Popup dark do system tray")
reset(app)

# Posiciona cursor no centro-direito da tela (popup abre perto dali)
sw = app.root.winfo_screenwidth()
sh = app.root.winfo_screenheight()
ctypes.windll.user32.SetCursorPos(sw - 300, sh // 2)

app._open_tray_popup()
pump(app, 25)

pw = app._tray_popup_win
if pw and pw.winfo_exists():
    snap(pw, "tray_popup.png", app)
    try:
        app._close_tray_popup_win()
    except Exception:
        try: pw.destroy()
        except Exception: pass
pump(app, 5)


# ── fim ───────────────────────────────────────────────────────────────────
print("\nScreenshots salvos em:", OUT)
try:
    app.root.destroy()
except Exception:
    pass
