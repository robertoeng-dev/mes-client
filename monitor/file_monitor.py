# =============================================================================
# file_monitor.py — Loop principal de monitoramento de arquivos CSV
# =============================================================================
#
# Função start_monitor() roda em thread daemon separada.
# A cada scan_interval segundos ela:
#   1. Lista CSVs na pasta monitorada
#   2. Sincroniza para destino (se sync habilitado)
#   3. Lê linhas novas de cada CSV (usando offset_manager)
#   4. Insere no PostgreSQL em lote
#   5. Se banco offline → salva na fila offline (queue_buffer)
#   6. Atualiza ícone da bandeja (verde/amarelo/vermelho)
#
# Parar o monitor: stop_event.set()
# Reiniciar: stop_event.set() → aguardar → stop_event.clear() → nova thread
# =============================================================================

import os
import time
import hashlib

from config.loader import load_config
from config.column_mapper import load_mappings, resolve_field, detect_unmapped_fields
from parser.cyg_parser import parse_appended_rows, detect_model_from_filename
from state.offset_manager import OffsetManager
from database.db_writer import DBWriter
from buffer.queue_buffer import OfflineQueue
from state.app_context import runtime_status
from logs.logger_setup import get_logger
from sync.file_sync import sync_folder
from spec.spec_validator import validate_schema_limits

logger = get_logger()


# -----------------------------------------------------------------------------
# FUNÇÕES AUXILIARES
# -----------------------------------------------------------------------------

def _schema_hash(headers):
    """Gera hash MD5 da lista de colunas do CSV.
    Identifica unicamente a estrutura do arquivo — detecta mudanças de schema."""
    text = "|".join(headers)
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _normalize_result(value):
    """Normaliza texto de resultado para PASS ou FAIL.
    Diferentes testadores usam variações (PASSED, NG, FAILED)."""
    if not value:
        return None

    v = str(value).strip().upper()

    if "PASS" in v or "PASSED" in v:
        return "PASS"

    if "FAIL" in v or "FAILED" in v or "NG" in v:
        return "FAIL"

    return v


def _list_csv_files(log_folder, recursive=False):
    """Lista todos os arquivos .csv na pasta.
    recursive=True: percorre subpastas (os.walk).
    recursive=False: apenas o nível raiz (os.listdir — mais rápido)."""
    csv_files = []

    if not os.path.exists(log_folder):
        return csv_files

    if not recursive:
        for file_name in os.listdir(log_folder):
            full_path = os.path.join(log_folder, file_name)
            if os.path.isfile(full_path) and file_name.lower().endswith(".csv"):
                csv_files.append(full_path)
        return csv_files

    for root, _, files in os.walk(log_folder):
        for file_name in files:
            if file_name.lower().endswith(".csv"):
                csv_files.append(os.path.join(root, file_name))

    return csv_files


def _resolve_model_name(file_model, config_model, rows, mappings):
    """Determina o nome do modelo com prioridade:
    1º nome detectado no arquivo (PCM), 2º campo da linha (via column_mapper), 3º config.yaml."""
    if file_model:
        return file_model

    if rows:
        val = resolve_field("model_name", rows[0], "DEFAULT", mappings)
        if val:
            return val

    return config_model or "UNKNOWN_MODEL"


def _resolve_version_name(file_version, rows):
    """Determina a versão de firmware/software do modelo testado."""
    if file_version:
        return file_version

    if rows:
        for key in ("bmu_MIX_FW_Version", "SC_ROM", "Version", "version"):
            value = rows[0].get(key)
            if value:
                return str(value).strip()

    return "UNKNOWN_VERSION"


def _pcm_serial(row):
    """Compõe chave composta para PCM_TESTER (não possui serial único).
    Formato: machine_no|CH{channel_no}|device_name|test_time
    Nota: colunas do PCM Tester são fixas pelo protocolo do equipamento."""
    machine   = row.get("machine_no")  or ""
    channel   = row.get("channel_no")  or ""
    carrier   = row.get("device_name") or row.get("barcode") or ""
    test_time = row.get("test_time")   or ""
    return f"{machine}|CH{channel}|{carrier}|{test_time}"


def _update_tray_color(status_callback, db_ok=True, sync_ok=True, stopped=False):
    """Atualiza a cor do ícone na bandeja conforme o estado do sistema.
    amarelo=parado, vermelho=erro, verde=tudo ok."""
    if not status_callback:
        return

    if stopped:
        status_callback("yellow")
        return

    if not db_ok or not sync_ok:
        status_callback("red")
        return

    status_callback("green")


# -----------------------------------------------------------------------------
# LOOP PRINCIPAL
# -----------------------------------------------------------------------------

def start_monitor(stop_event=None, status_callback=None):
    """Ponto de entrada do monitor. Roda em loop infinito até stop_event.set().

    stop_event: threading.Event — .set() para parar, .clear() para retomar
    status_callback: função(cor) — atualiza o ícone da bandeja
    """
    config = load_config()

    log_folder    = config["log"]["folder"]
    recursive     = config.get("log", {}).get("recursive", False)
    scan_interval = config["parser"].get("scan_interval", 5)
    station_id    = config["station"]["id"]
    station_type  = config["station"].get("type", "AUTO").upper()
    config_model  = config["station"].get("model", "")
    operation_mode = config.get("operation", {}).get("mode", "database").lower()

    database_enabled = config.get("database", {}).get("enabled", True)
    sync_enabled     = config.get("sync", {}).get("enabled", False)

    if operation_mode in ("sync", "both"):
        sync_enabled = True

    # OffsetManager: rastreia até onde cada arquivo já foi lido (evita reler linhas)
    offset_manager = OffsetManager()

    # DBWriter é None se banco estiver desabilitado no modo "sync"
    db = DBWriter() if database_enabled and operation_mode in ("database", "both") else None

    # OfflineQueue: fila em disco para lotes que falharam ao inserir no banco
    offline_queue = OfflineQueue()

    runtime_status.set("client_status", "RUNNING")
    runtime_status.set("station_name", station_id)
    runtime_status.set("client_version", "1.0")
    runtime_status.set("operation_mode", operation_mode)

    logger.info("MONITOR INICIADO")
    logger.info(f"Pasta monitorada: {log_folder}")
    logger.info(f"Recursivo: {recursive}")
    logger.info(f"Intervalo: {scan_interval}s")
    logger.info(f"Station: {station_id}")
    logger.info(f"Station Type: {station_type}")
    logger.info(f"Modo de operação: {operation_mode}")
    logger.info(f"Sync enabled: {sync_enabled}")

    while True:
        db_ok   = True
        sync_ok = True

        # Se stop_event foi sinalizado, fica em idle (sem processar)
        if stop_event and stop_event.is_set():
            runtime_status.set("client_status", "STOPPED")
            _update_tray_color(status_callback, stopped=True)
            time.sleep(1)
            continue

        runtime_status.set("client_status", "RUNNING")

        try:
            # Recarrega mapeamentos a cada ciclo — nova config via tela MAPEAMENTO
            # entra em vigor sem reiniciar o monitor.
            mappings = load_mappings()

            if not os.path.exists(log_folder):
                msg = f"Pasta não encontrada: {log_folder}"
                logger.error(msg)
                runtime_status.mark_error(msg)
                _update_tray_color(status_callback, db_ok=False, sync_ok=False)
                time.sleep(scan_interval)
                continue

            files = _list_csv_files(log_folder, recursive=recursive)
            runtime_status.set("files_monitored", len(files))

            # -----------------------------------------------------------------
            # SYNC: copia CSVs para destino de rede/pendrive
            # -----------------------------------------------------------------
            if sync_enabled and operation_mode in ("sync", "both"):
                sync_result = sync_folder(
                    source_folder=log_folder,
                    destination_folder=config["sync"]["destination_folder"],
                    mode=config["sync"].get("mode", "diff"),
                    recursive=recursive
                )

                if sync_result["error"]:
                    sync_ok = False
                    runtime_status.set("sync_status", "ERRO")
                    runtime_status.set("sync_checked", sync_result.get("checked", 0))
                    runtime_status.set("sync_copied",  sync_result.get("copied",  0))
                    runtime_status.set("sync_deleted", sync_result.get("deleted", 0))
                    runtime_status.set("sync_last_file", sync_result["error"])
                    runtime_status.set("sync_last_time", sync_result.get("last_sync_time", ""))
                    logger.error(f"SYNC ERRO: {sync_result['error']}")
                else:
                    runtime_status.set("sync_status",    "OK")
                    runtime_status.set("sync_checked",   sync_result["checked"])
                    runtime_status.set("sync_copied",    sync_result["copied"])
                    runtime_status.set("sync_deleted",   sync_result["deleted"])
                    runtime_status.set("sync_last_file", sync_result["last_file"])
                    runtime_status.set("sync_last_time", sync_result["last_sync_time"])

            # Modo somente sync: não processa banco
            if operation_mode == "sync":
                _update_tray_color(status_callback, db_ok=True, sync_ok=sync_ok)
                time.sleep(scan_interval)
                continue

            # -----------------------------------------------------------------
            # DB: verifica conexão e reenvia fila offline se banco voltou
            # -----------------------------------------------------------------
            if db:
                runtime_status.set("offline_queue_count", offline_queue.count())

                if db.ping():
                    # Banco voltou: tenta reenviar lotes que ficaram na fila offline
                    pending = offline_queue.pop_all()

                    if pending:
                        inserted = db.insert_rows(pending)
                        runtime_status.mark_insert("offline_queue", inserted)
                        logger.info(f"Reenvio da fila offline concluído. Quantidade: {inserted}")

                    runtime_status.set("offline_queue_count", offline_queue.count())
                    runtime_status.set("db_status", "ONLINE")
                    db_ok = True
                else:
                    runtime_status.set("db_status", "OFFLINE")
                    db_ok = False

            if not db:
                _update_tray_color(status_callback, db_ok=True, sync_ok=sync_ok)
                time.sleep(scan_interval)
                continue

            # -----------------------------------------------------------------
            # INSERT: processa cada CSV e insere linhas novas no banco
            # -----------------------------------------------------------------
            for full_path in sorted(files):
                file_name = os.path.basename(full_path)
                # last_state: onde paramos na leitura anterior deste arquivo
                state = offset_manager.get(full_path)

                runtime_status.set("current_file", file_name)

                # parse_appended_rows lê apenas bytes novos (a partir do offset salvo)
                parsed = parse_appended_rows(
                    full_path,
                    state,
                    station_type=station_type
                )

                rows = parsed["rows"]

                if not rows:
                    continue

                file_model, file_version = detect_model_from_filename(full_path)

                model_name   = _resolve_model_name(file_model, config_model, rows, mappings)
                version_name = _resolve_version_name(file_version, rows)

                # Fundação Opção C: detecta campos sem mapeamento configurado
                unmapped = detect_unmapped_fields(rows[0], model_name, mappings)
                if unmapped:
                    runtime_status.set("unmapped_fields_alert", {
                        "file": file_name,
                        "model": model_name,
                        "fields": unmapped
                    })

                schema      = parsed["schema"]
                schema_hash = _schema_hash(schema["headers"])

                # Registra/atualiza o schema do CSV no catálogo do banco
                db.upsert_schema(
                    schema_hash=schema_hash,
                    model_name=model_name,
                    version_name=version_name,
                    source_file_pattern=file_name,
                    columns_json=schema["headers"],
                    upper_limits_json=schema["upper_map"],
                    lower_limits_json=schema["lower_map"],
                    units_json=schema["unit_map"]
                )

                # Valida limites do testador contra spec_limits.csv (se habilitado)
                if config.get("spec_check", {}).get("enabled", False):
                    mismatches = validate_schema_limits(
                        model_name=model_name,
                        schema=schema,
                        spec_file_name=config["spec_check"].get("file", "spec_limits.csv")
                    )

                    mismatch_count = db.insert_spec_mismatches(
                        station_id=station_id,
                        model_name=model_name,
                        version_name=version_name,
                        source_file=file_name,
                        schema_hash=schema_hash,
                        mismatches=mismatches
                    )

                    runtime_status.set("spec_mismatch_count", mismatch_count)

                    if mismatch_count:
                        logger.warning(f"{mismatch_count} divergências de spec detectadas em {file_name}")

                # Monta o lote para inserção
                batch = []

                for row in rows:
                    serial = (
                        _pcm_serial(row) if station_type == "PCM_TESTER"
                        else resolve_field("serial_number", row, model_name, mappings)
                    )
                    batch.append({
                        "station_id":      station_id,
                        "model_name":      model_name,
                        "version_name":    version_name,
                        "serial_number":   serial,
                        "result_status":   _normalize_result(
                                               resolve_field("result_status", row, model_name, mappings)
                                           ),
                        "test_start_time": resolve_field("test_start_time", row, model_name, mappings),
                        "test_stop_time":  resolve_field("test_stop_time",  row, model_name, mappings),
                        "source_file":     file_name,
                        "source_line_no":  row["_line_no"],
                        "schema_hash":     schema_hash,
                        "row_data":        row
                    })

                try:
                    inserted = db.insert_rows(batch)

                    # Atualiza offset SOMENTE após insert bem-sucedido
                    # (garante que na próxima rodada não pula linhas não inseridas)
                    offset_manager.update(
                        full_path,
                        parsed["new_offset"],
                        parsed["new_line_no"],
                        parsed["file_size"]
                    )

                    last_serial = batch[-1]["serial_number"] if batch else ""
                    last_result = batch[-1]["result_status"]  if batch else ""

                    runtime_status.mark_insert(
                        file_name=file_name,
                        batch_size=inserted,
                        last_serial=last_serial,
                        last_result=last_result,
                        last_model=model_name,
                        last_version=version_name
                    )

                    runtime_status.set("current_file", "")
                    runtime_status.set("db_status", "ONLINE")

                    logger.info(f"{inserted} novas linhas inseridas: {file_name}")

                except Exception as e:
                    # Banco falhou: desfaz, salva na fila offline para tentar depois
                    db.rollback()
                    offline_queue.push_many(batch)
                    runtime_status.set("offline_queue_count", offline_queue.count())
                    runtime_status.mark_error(f"Erro ao inserir lote de {file_name}: {e}")
                    logger.error(f"Banco offline ou erro ao inserir. Batch salvo offline. Erro: {e}")
                    db_ok = False

            _update_tray_color(status_callback, db_ok=db_ok, sync_ok=sync_ok)

        except Exception as e:
            runtime_status.mark_error(str(e))
            logger.exception(f"Erro no monitor: {e}")
            _update_tray_color(status_callback, db_ok=False, sync_ok=False)

        time.sleep(scan_interval)
