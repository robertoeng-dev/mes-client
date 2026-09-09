# =============================================================================
# offset_manager.py — Rastreia posição de leitura em cada arquivo CSV
# =============================================================================
#
# Problema: o monitor roda a cada N segundos e o testador continua escrevendo.
# Sem rastreamento, cada ciclo releria o arquivo inteiro desde o início.
#
# Solução: para cada arquivo, salva em offsets.json:
#   offset    — posição em bytes (f.seek) onde parou a última leitura
#   line_no   — número da linha de dados processada (para source_line_no no banco)
#   file_size — tamanho do arquivo na última leitura (detecta truncamento/rotação)
#
# Se file_size diminuiu → arquivo foi rotacionado → reinicia do início.
#
# ESCRITA ATÔMICA: grava num arquivo temporário e faz os.replace(). Uma queda
# de energia no meio da escrita deixa o offsets.json anterior intacto em vez de
# um JSON pela metade, que impediria o monitor de subir na próxima vez.
# =============================================================================

import json
import os
import tempfile

from config.loader import get_base_path


class OffsetManager:
    def __init__(self):
        # offsets.json fica na raiz do projeto, ao lado do config.yaml
        self.file = os.path.join(get_base_path(), "offsets.json")

        if not os.path.exists(self.file):
            self._save({})

    def _load(self):
        """Lê o JSON do disco. Sempre relê — simples e sem cache que pode desatualizar.

        Se o arquivo estiver corrompido (interrompido por queda de energia numa
        versão anterior, sem escrita atômica), recomeça do zero em vez de
        derrubar o monitor: relê os CSVs desde o início e o
        ON CONFLICT DO NOTHING do banco descarta o que já tinha entrado."""
        try:
            with open(self.file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {}
            return data
        except (json.JSONDecodeError, OSError):
            return {}

    def _save(self, data):
        """Grava offsets.json de forma atômica: arquivo temporário + os.replace().

        os.replace() é atômico no Windows e no Linux — em nenhum instante existe
        um offsets.json parcialmente escrito."""
        dir_name = os.path.dirname(self.file) or "."
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, prefix=".offsets_", suffix=".tmp")

        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
                f.flush()
                os.fsync(f.fileno())    # garante que chegou ao disco, não só ao cache
            os.replace(tmp_path, self.file)
        except Exception:
            # Não deixa lixo para trás se algo falhar no meio do caminho
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise

    def get(self, file_path):
        """Retorna o estado salvo para o arquivo. Se nunca visto, retorna zeros (início)."""
        data = self._load()

        return data.get(file_path, {
            "offset":    0,
            "line_no":   0,
            "file_size": 0
        })

    def update(self, file_path, offset, line_no, file_size):
        """Salva o novo estado após um insert bem-sucedido.
        Chamado SOMENTE após commit no banco — se falhar antes, relê as linhas na próxima rodada."""
        data = self._load()

        data[file_path] = {
            "offset":    offset,
            "line_no":   line_no,
            "file_size": file_size
        }

        self._save(data)
