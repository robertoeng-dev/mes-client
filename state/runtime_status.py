# =============================================================================
# runtime_status.py — Estado em tempo real do monitor (thread-safe)
# =============================================================================
#
# RuntimeStatus é um dicionário compartilhado entre threads:
#   - Thread do monitor escreve os valores (set, mark_insert, mark_error)
#   - Thread do Tkinter lê para exibir na tela STATUS (snapshot)
#
# threading.Lock garante que leituras e escritas não colidam entre threads.
# snapshot() retorna uma CÓPIA do dict — não deixa a UI segurar o lock.
# =============================================================================

import threading
from datetime import datetime


class RuntimeStatus:
    def __init__(self):
        # Lock: impede que duas threads leiam/escrevam ao mesmo tempo
        self._lock = threading.Lock()

        # Estado inicial — chaves espelhadas nos campos da tela STATUS
        self.data = {
            "client_status":         "STARTING",
            "db_status":             "UNKNOWN",
            "station_name":          "",
            "client_version":        "1.0",
            "startup_time":          datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "operation_mode":        "",

            # Sincronização de arquivos
            "sync_status":           "",
            "sync_checked":          0,
            "sync_copied":           0,
            "sync_deleted":          0,
            "sync_last_file":        "",
            "sync_last_time":        "",

            # Processamento de arquivos CSV
            "last_sync_file":        "",
            "spec_mismatch_count":   0,
            "current_file":          "",
            "last_file":             "",
            "last_model":            "",
            "last_version":          "",
            "last_batch_inserted":   0,
            "session_total_inserted": 0,
            "last_insert_time":      "",
            "last_error":            "",
            "offline_queue_count":   0,
            "last_serial":           "",
            "last_result":           "",
            "files_monitored":       0
        }

    def set(self, key, value):
        """Atualiza um campo. Thread-safe."""
        with self._lock:
            self.data[key] = value

    def increment(self, key, amount):
        """Soma um valor a um campo numérico. Thread-safe."""
        with self._lock:
            self.data[key] += amount

    def snapshot(self):
        """Retorna cópia do estado atual. Use na UI para não segurar o lock."""
        with self._lock:
            return dict(self.data)

    def mark_insert(
        self,
        file_name,
        batch_size,
        last_serial="",
        last_result="",
        last_model="",
        last_version=""
    ):
        """Atualiza múltiplos campos de uma vez após insert bem-sucedido.
        Um único lock para todas as escritas — evita estado parcial na UI."""
        with self._lock:
            self.data["last_file"]              = file_name
            self.data["last_batch_inserted"]    = batch_size
            self.data["session_total_inserted"] += batch_size
            self.data["last_insert_time"]       = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            if last_serial:
                self.data["last_serial"] = last_serial
            if last_result:
                self.data["last_result"] = last_result
            if last_model:
                self.data["last_model"] = last_model
            if last_version:
                self.data["last_version"] = last_version

            self.data["last_error"] = ""    # limpa erro anterior após sucesso

    def mark_error(self, message):
        """Registra erro e muda status para ERROR."""
        with self._lock:
            self.data["last_error"]    = str(message)
            self.data["client_status"] = "ERROR"
