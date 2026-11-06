# =============================================================================
# station_cache.py — Cópia local do cadastro das fontes deste PC
# =============================================================================
#
# cadastro_cache.json (ao lado do config.yaml) guarda:
#   fontes       — a linha de v_cadastro_fontes de cada vínculo deste PC
#                  (formato, definição, padrão de arquivo, fuso...), para o
#                  cliente continuar lendo os logs e enchendo a fila offline
#                  quando o banco estiver fora;
#   confirmados  — station_pk das estações que JÁ foram vinculadas a este PC.
#
# "confirmados" decide o vínculo automático: uma estação nunca vinculada aqui
# é vinculada sozinha na primeira vez. Se depois o banco mostrar a estação SEM
# PC (a engenharia liberou o vínculo no MES Cadastro), o cliente NÃO vincula
# de novo sozinho — mostra "VÍNCULO LIBERADO" e espera alguém pedir na tela
# FONTES DESTE PC. Isso impede que dois PCs clonados briguem pela estação.
#
# Escrita atômica (arquivo temporário + os.replace), igual ao offsets.json.
# =============================================================================

import json
import os
import tempfile
import threading
from datetime import datetime

from config.loader import get_base_path

_lock = threading.Lock()


class StationCache:
    def __init__(self, caminho=None):
        self.file = caminho or os.path.join(get_base_path(), "cadastro_cache.json")

    def _load(self):
        try:
            with open(self.file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                data.setdefault("fontes", {})
                data.setdefault("confirmados", [])
                return data
        except (OSError, ValueError):
            pass
        return {"atualizado_em": None, "fontes": {}, "confirmados": []}

    def _save(self, data):
        pasta = os.path.dirname(self.file) or "."
        fd, tmp = tempfile.mkstemp(dir=pasta, prefix=".cadastro_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.file)
        except Exception:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            raise

    @staticmethod
    def chave(estacao, fonte):
        return "%s/%s" % (str(estacao).strip().upper(), str(fonte).strip().upper())

    def buscar(self, estacao, fonte):
        with _lock:
            return self._load()["fontes"].get(self.chave(estacao, fonte))

    def guardar(self, linhas_por_chave):
        """Substitui as fontes guardadas (só as dos vínculos deste PC)."""
        with _lock:
            data = self._load()
            data["fontes"] = dict(linhas_por_chave)
            data["atualizado_em"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._save(data)

    def confirmado(self, station_pk):
        with _lock:
            return station_pk in self._load()["confirmados"]

    def confirmar(self, station_pk):
        with _lock:
            data = self._load()
            if station_pk not in data["confirmados"]:
                data["confirmados"].append(station_pk)
                self._save(data)

    def desconfirmar(self, station_pk):
        """Usado pela tela FONTES DESTE PC ("vincular de novo")."""
        with _lock:
            data = self._load()
            if station_pk in data["confirmados"]:
                data["confirmados"].remove(station_pk)
                self._save(data)

    def atualizado_em(self):
        with _lock:
            return self._load().get("atualizado_em")
