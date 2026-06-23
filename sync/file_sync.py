# =============================================================================
# file_sync.py — Sincronização de arquivos CSV para destino de rede/pendrive
# =============================================================================
#
# Modos de operação (configurável em config.yaml):
#   diff          — copia somente arquivos diferentes (tamanho ou data)
#   copy_overwrite — copia tudo sempre, sobrescreve
#   sync          — igual ao diff + remove do destino arquivos que não existem na origem
#
# Funciona para:
#   - Pasta local           (D:\backup)
#   - Pendrive              (E:\)
#   - Pasta de rede Samba   (\\10.20.1.10\MES_LOGS)
#
# shutil.copy2 preserva metadados (data de modificação) — necessário para
# o modo diff funcionar corretamente na próxima rodada.
# =============================================================================

import os
import shutil
from datetime import datetime

from logs.logger_setup import get_logger

logger = get_logger()


def _should_copy(src, dst, mode):
    """Decide se o arquivo deve ser copiado com base no modo e nas diferenças."""
    if mode == "copy_overwrite":
        return True     # sempre copia

    if not os.path.exists(dst):
        return True     # destino não existe — copia sempre

    src_stat = os.stat(src)
    dst_stat = os.stat(dst)

    # Compara tamanho e data de modificação — se diferentes, arquivo foi atualizado
    if src_stat.st_size != dst_stat.st_size:
        return True

    # int() trunca para segundos — evita diferenças de precisão entre sistemas de arquivos
    if int(src_stat.st_mtime) != int(dst_stat.st_mtime):
        return True

    return False    # arquivos idênticos — não precisa copiar


def sync_folder(source_folder, destination_folder, mode="diff", recursive=False):
    """Sincroniza arquivos CSV da pasta origem para destino.
    Retorna dicionário com resumo da operação (para exibir no STATUS)."""
    result = {
        "copied":         0,
        "deleted":        0,
        "checked":        0,
        "last_file":      "",
        "last_sync_time": "",
        "error":          ""
    }

    try:
        if not source_folder:
            result["error"] = "Pasta origem vazia"
            return result

        if not destination_folder:
            result["error"] = "Pasta destino vazia"
            return result

        if not os.path.exists(source_folder):
            result["error"] = f"Origem não existe: {source_folder}"
            return result

        # Cria destino automaticamente se não existir (inclusive subpastas)
        os.makedirs(destination_folder, exist_ok=True)

        source_files = set()    # rastreia arquivos na origem (para o modo sync)

        # recursive=False: lista apenas raiz (mais rápido)
        # recursive=True:  percorre subpastas mantendo estrutura no destino
        if recursive:
            walker = os.walk(source_folder)
        else:
            walker = [(source_folder, [], os.listdir(source_folder))]

        for root, _, files in walker:
            for file_name in files:
                if not file_name.lower().endswith(".csv"):
                    continue

                src = os.path.join(root, file_name)

                # relpath mantém a estrutura de subpastas ao copiar
                rel_path = os.path.relpath(src, source_folder)
                dst = os.path.join(destination_folder, rel_path)

                source_files.add(rel_path)
                result["checked"] += 1

                try:
                    os.makedirs(os.path.dirname(dst), exist_ok=True)

                    if _should_copy(src, dst, mode):
                        # copy2 copia o arquivo E preserva data/hora de modificação
                        shutil.copy2(src, dst)
                        result["copied"] += 1
                        result["last_file"] = rel_path
                        logger.info(f"SYNC: arquivo copiado: {rel_path}")

                except Exception as e:
                    result["error"] = f"Erro copiando {rel_path}: {e}"
                    logger.error(result["error"])
                    return result

        # Modo sync: remove do destino arquivos que não existem mais na origem
        if mode == "sync":
            for root, _, files in os.walk(destination_folder):
                for file_name in files:
                    if not file_name.lower().endswith(".csv"):
                        continue

                    dst      = os.path.join(root, file_name)
                    rel_path = os.path.relpath(dst, destination_folder)

                    if rel_path not in source_files:
                        try:
                            os.remove(dst)
                            result["deleted"] += 1
                            logger.info(f"SYNC: arquivo removido no destino: {rel_path}")

                        except Exception as e:
                            result["error"] = f"Erro removendo {rel_path}: {e}"
                            logger.error(result["error"])
                            return result

        result["last_sync_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return result

    except Exception as e:
        result["error"] = str(e)
        logger.exception(f"Erro geral no sync: {e}")
        return result
