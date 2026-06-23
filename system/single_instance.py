# =============================================================================
# single_instance.py — Impede que o MES Client rode duas vezes ao mesmo tempo
# =============================================================================
#
# Técnica: lock de arquivo no diretório temporário do sistema.
# Windows: msvcrt.locking (bloqueio exclusivo não-bloqueante)
# Linux:   fcntl.flock
#
# Se acquire() retorna False, outra instância já está rodando.
# atexit.register garante que o lock seja liberado quando o processo termina.
# =============================================================================

import os
import tempfile
import atexit


class SingleInstance:
    def __init__(self, name="MES_CLIENT_SINGLE_INSTANCE"):
        self.name = name
        # Arquivo de lock no temp do sistema (ex: C:\Users\DELL\AppData\Local\Temp)
        self.lockfile_path = os.path.join(
            tempfile.gettempdir(),
            f"{self.name}.lock"
        )
        self.handle = None

    def acquire(self):
        """Tenta adquirir o lock. Retorna True se conseguiu (única instância).
        Retorna False se outra instância já tem o lock."""
        try:
            # Abre em append ("a+") — não apaga conteúdo existente
            self.handle = open(self.lockfile_path, "a+")

            if os.name == "nt":
                import msvcrt
                # LK_NBLCK: tenta o lock sem esperar (não-bloqueante)
                # Se o arquivo já está lockado, lança exceção imediatamente
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                # LOCK_EX: exclusivo | LOCK_NB: não-bloqueante
                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)

            # Registra liberação automática ao encerrar o processo
            atexit.register(self.release)
            return True

        except Exception:
            return False

    def release(self):
        """Libera o lock. Chamado automaticamente pelo atexit ao fechar o app."""
        try:
            if self.handle:
                if os.name == "nt":
                    import msvcrt
                    self.handle.seek(0)
                    msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.handle, fcntl.LOCK_UN)

                self.handle.close()
                self.handle = None

        except Exception:
            pass    # silencia erros no shutdown — processo já está encerrando
