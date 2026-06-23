# =============================================================================
# queue_buffer.py — Fila offline em disco para lotes que falharam no banco
# =============================================================================
#
# Quando o PostgreSQL está offline, os lotes de dados não são perdidos.
# Cada lote é salvo em offline_queue.jsonl (um JSON por linha — formato JSONL).
#
# Fluxo:
#   1. insert_rows falha → db_writer chama rollback
#   2. file_monitor chama offline_queue.push_many(batch)
#   3. Na próxima rodada, se banco voltou → offline_queue.pop_all() → reinsere
#
# JSONL (JSON Lines): cada linha é um JSON completo independente.
# Vantagem: fácil de append sem reescrever o arquivo inteiro.
# =============================================================================

import os
import json
from config.loader import get_base_path


class OfflineQueue:
    def __init__(self):
        # offline_queue.jsonl fica na raiz do projeto
        self.file_path = os.path.join(get_base_path(), "offline_queue.jsonl")

    def push_many(self, rows):
        """Adiciona lote de linhas ao final do arquivo (append).
        ensure_ascii=False preserva acentos — o arquivo é interno, não vai ao banco ainda."""
        if not rows:
            return

        with open(self.file_path, "a", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def pop_all(self):
        """Lê todas as linhas e apaga o arquivo.
        Deve ser chamado somente quando o banco está online (ping retornou True)."""
        if not os.path.exists(self.file_path):
            return []

        items = []

        with open(self.file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    items.append(json.loads(line))

        # Remove o arquivo depois de ler — evita reprocessamento
        os.remove(self.file_path)
        return items

    def count(self):
        """Conta quantos registros estão na fila (para exibir no STATUS)."""
        if not os.path.exists(self.file_path):
            return 0

        count = 0
        with open(self.file_path, "r", encoding="utf-8") as f:
            for _ in f:
                count += 1

        return count
