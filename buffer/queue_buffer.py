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
#   3. Na próxima rodada, se o banco voltou:
#        peek_all()  → lê a fila SEM apagar
#        insert_rows → grava no banco
#        commit()    → só então apaga o arquivo
#
# POR QUE peek + commit, e não um "pop" que lê e apaga de uma vez:
#   Se o insert falhar depois de o arquivo já ter sido apagado (conexão caiu
#   entre o ping e o insert, timeout, disco cheio no servidor), os registros
#   somem para sempre — exatamente o que esta fila existe para evitar.
#   Com peek + commit, uma falha deixa o arquivo intacto e a próxima rodada
#   tenta de novo. Reprocessar é seguro: o INSERT usa ON CONFLICT DO NOTHING.
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

    def peek_all(self):
        """Lê todos os registros da fila SEM apagar o arquivo.

        Só apague depois, com commit(), quando o insert tiver dado commit no
        banco. Linhas corrompidas (JSON inválido — escrita interrompida por
        queda de energia) são puladas em vez de derrubar o reenvio inteiro."""
        if not os.path.exists(self.file_path):
            return []

        items = []

        with open(self.file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError:
                    # Linha truncada no fim do arquivo: ignora e segue com o resto.
                    continue

        return items

    def commit(self):
        """Apaga a fila. Chamar SOMENTE após o insert ter dado commit no banco."""
        if os.path.exists(self.file_path):
            os.remove(self.file_path)

    def count(self):
        """Conta quantos registros estão na fila (para exibir no STATUS)."""
        if not os.path.exists(self.file_path):
            return 0

        count = 0
        with open(self.file_path, "r", encoding="utf-8") as f:
            for _ in f:
                count += 1

        return count

    def size_bytes(self):
        """Tamanho do arquivo da fila — usado para o alerta de fila crescendo demais."""
        if not os.path.exists(self.file_path):
            return 0
        return os.path.getsize(self.file_path)
