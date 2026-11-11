"""2.0.2: sys.executable com lixo (M13, WinError 123) e pasta de log inválida."""
import os, sys, importlib, tempfile, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
falhas = 0


def ok(cond, msg):
    global falhas
    print(("ok   " if cond else "FALHA ") + msg)
    falhas += 0 if cond else 1


LIXO = "缺\xa0Ű\x9erver\\140\\DTS\\Binn\\;C:"

sys.frozen = True
sys.executable = LIXO
import config.loader as loader
sys.executable = LIXO
importlib.reload(loader)
ok(loader.EXECUTABLE_CORRIGIDO == LIXO, "lixo detectado e devolvido para o log")
ok(os.path.isfile(sys.executable), "sys.executable corrigido: %s" % sys.executable)
ok(os.path.normcase(sys.executable) == os.path.normcase(loader._caminho_exe_real()),
   "igual ao caminho dado pelo Windows")
ok(os.path.isdir(loader.get_base_path()), "get_base_path existe")

importlib.reload(loader)
ok(loader.EXECUTABLE_CORRIGIDO is None, "exe valido nao e' alterado")

from logs import logger_setup
orig = logger_setup.get_base_path
logger_setup.get_base_path = lambda: "缺\xa0:\\?*<>|"
logging.getLogger("MES_CLIENT").handlers.clear()
loader.EXECUTABLE_CORRIGIDO = LIXO
lg = logger_setup.get_logger()
arqs = [h.baseFilename for h in lg.handlers if hasattr(h, "baseFilename")]
ok(bool(arqs) and arqs[0].startswith(tempfile.gettempdir()), "log caiu no TEMP: %s" % arqs)
for h in list(lg.handlers):
    h.close()
    lg.removeHandler(h)
logger_setup.get_base_path = orig
del sys.frozen
print("FALHAS:", falhas)
sys.exit(1 if falhas else 0)
