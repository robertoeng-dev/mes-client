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
# =============================================================================

import json
import os
from config.loader import get_base_path


class OffsetManager:
    def __init__(self):
        # offsets.json fica na raiz do projeto, ao lado do config.yaml
        self.file = os.path.join(get_base_path(), "offsets.json")

        if not os.path.exists(self.file):
            with open(self.file, "w", encoding="utf-8") as f:
                json.dump({}, f, indent=4)

    def _load(self):
        """Lê o JSON do disco. Sempre relê — simples e sem cache que pode desatualizar."""
        with open(self.file, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save(self, data):
        with open(self.file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)

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
