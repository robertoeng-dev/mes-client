# =============================================================================
# app_context.py — Instância global compartilhada do RuntimeStatus
# =============================================================================
#
# runtime_status é importado por todos os módulos que precisam ler ou escrever
# o estado em tempo real (monitor, db_writer, ui_main).
#
# Singleton simples: o Python cacheia o módulo após o primeiro import,
# então todos os módulos compartilham exatamente a mesma instância.
# =============================================================================

from state.runtime_status import RuntimeStatus

runtime_status = RuntimeStatus()
