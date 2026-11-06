# =============================================================================
# file_monitor.py — Loop principal: lê as FONTES de log vinculadas a este PC
# =============================================================================
#
# Cliente 2.0 (cadastro centralizado). O config.yaml lista os vínculos:
#
#   vinculos:
#     - estacao: CAIAPO-M13-FT      # código cadastrado no MES Cadastro
#       fonte:   FT                 # código da fonte dentro da estação
#       pasta:   D:\battData        # pasta local onde o equipamento grava
#       sync_destino: ""            # opcional: cópia dos arquivos para a rede
#
# Formato, padrão de arquivo, recursivo, modelo atual e fuso vêm do cadastro
# (v_cadastro_fontes), relido a cada 10 min e guardado em cadastro_cache.json.
#
# A cada scan_interval segundos, para cada fonte liberada:
#   1. (sync) copia os arquivos para o destino de rede, se configurado
#   2. lê só as linhas novas de cada arquivo (offset por "fonte_id|caminho")
#   3. grava no banco em lote (fonte_id); offset só avança depois do COMMIT
#   4. banco fora → não lê (o offset guarda a posição); queda no meio do
#      lote → lote vai para a fila offline e é reenviado quando o banco volta
#   5. o banco recusou pela regra do cadastro (MS0xx: inativa, outro PC,
#      vínculo liberado) → a fonte PARA, com o motivo na tela STATUS; nada
#      vai para a fila e o offset não anda (nada se perde)
#
# Parar: stop_event.set(). Reiniciar: set → aguardar → clear → nova thread.
# =============================================================================

import fnmatch
import os
import time
from datetime import datetime

from buffer.queue_buffer import OfflineQueue
from config.column_mapper import detect_unmapped_fields, load_mappings
from config.loader import load_config
from database.db_writer import SCHEMA_SUPORTADO, CadastroRecusado, DBWriter, host_do_pc
from logs.logger_setup import get_logger
from parser import registry
from parser.campos import _normalize_result, _parse_test_time, schema_hash  # noqa: F401 (testes)
from spec.spec_validator import validate_schema_limits
from state.app_context import runtime_status
from state.offset_manager import OffsetManager
from state.runtime_status import CLIENT_VERSION
from state.station_cache import StationCache
from sync.file_sync import sync_folder

logger = get_logger()

INTERVALO_CADASTRO = 600      # s entre releituras do cadastro

# Status de uma fonte
OK = "OK"
SEM_BANCO = "OK (CACHE)"         # lendo pelo cache; banco fora
NAO_VINCULADA = "NÃO VINCULADA"
NAO_CADASTRADA = "NÃO CADASTRADA"
LIBERADO = "VÍNCULO LIBERADO"
OUTRO_PC = "OUTRO PC"
INATIVA = "INATIVA"
ATUALIZAR = "ATUALIZE O CLIENTE"
FORMATO = "FORMATO NÃO SUPORTADO"
RECUSADA = "RECUSADA PELO BANCO"
SCHEMA = "SCHEMA INCOMPATÍVEL"
PASTA = "PASTA NÃO ENCONTRADA"
ERRO = "ERRO"

LIBERADOS = (OK, SEM_BANCO)


def _versao_tupla(v):
    try:
        return tuple(int(x) for x in str(v).split("."))
    except ValueError:
        return (0,)


def _list_files(pasta, padrao="*.csv", recursivo=False):
    """Arquivos da pasta que casam com o padrão (sem diferenciar maiúsculas).
    Vários padrões separados por ';' (ex.: '*.csv;*.txt')."""
    padroes = [p.strip().lower() for p in (padrao or "*.csv").split(";") if p.strip()]
    if not os.path.isdir(pasta):
        return []

    def casa(nome):
        n = nome.lower()
        return any(fnmatch.fnmatchcase(n, p) for p in padroes)

    if not recursivo:
        return [os.path.join(pasta, n) for n in os.listdir(pasta)
                if casa(n) and os.path.isfile(os.path.join(pasta, n))]
    achados = []
    for raiz, _, nomes in os.walk(pasta):
        achados += [os.path.join(raiz, n) for n in nomes if casa(n)]
    return achados


def _list_csv_files(log_folder, recursive=False):
    """Compatibilidade (testes/telas antigas)."""
    return _list_files(log_folder, "*.csv", recursive)


def _source_key(full_path, pasta):
    """Caminho RELATIVO à pasta da fonte, com '/' (mesmo nome em subpastas
    diferentes não colide no índice único fonte+arquivo+linha)."""
    try:
        return os.path.relpath(full_path, pasta).replace("\\", "/")
    except ValueError:
        return os.path.basename(full_path)


def _update_tray_color(status_callback, cor):
    if status_callback:
        status_callback(cor)


def ler_vinculos(config):
    """Lista de vínculos válidos do config.yaml (códigos em maiúsculas)."""
    vinculos = []
    for i, v in enumerate(config.get("vinculos") or []):
        estacao = str((v or {}).get("estacao") or "").strip().upper()
        fonte = str((v or {}).get("fonte") or "").strip().upper()
        pasta = str((v or {}).get("pasta") or "").strip()
        if not (estacao and fonte and pasta):
            logger.error("Vínculo #%d incompleto no config.yaml (estacao/fonte/pasta): %r" % (i + 1, v))
            continue
        vinculos.append({
            "estacao": estacao, "fonte": fonte, "pasta": pasta,
            "sync_destino": str(v.get("sync_destino") or "").strip(),
            "chave": StationCache.chave(estacao, fonte),
            "linha": None, "status": NAO_VINCULADA, "detalhe": "",
        })
    return vinculos


class MonitorFontes:
    """Um ciclo de leitura de todas as fontes vinculadas. Separado do laço
    infinito para poder ser testado contra o banco de homologação."""

    def __init__(self, config, db=None, cache=None, offsets=None, fila=None, status_callback=None):
        self.config = config
        self.host = host_do_pc(config)
        self.modo = (config.get("operation") or {}).get("mode", "database").lower()
        self.sync_modo = (config.get("sync") or {}).get("mode", "diff")
        self.spec = config.get("spec_check") or {}
        self.vinculos = ler_vinculos(config)
        self.db = db
        self.cache = cache or StationCache()
        self.offsets = offsets or OffsetManager()
        self.fila = fila or OfflineQueue()
        self.status_callback = status_callback
        self._ultimo_cadastro = 0.0
        self._ping_do_ciclo = None
        self.db_ok = False
        self.schema_ok = None

        # Destino de sync global só vale com um único vínculo (compatível com
        # o instalador de uma pasta só); com vários, cada vínculo diz o seu.
        destino_global = str((config.get("sync") or {}).get("destination_folder") or "").strip()
        if destino_global and len(self.vinculos) == 1 and not self.vinculos[0]["sync_destino"]:
            self.vinculos[0]["sync_destino"] = destino_global

        runtime_status.reset_fontes()
        runtime_status.set("host_id", self.host)
        runtime_status.set("station_name", ", ".join(sorted({v["estacao"] for v in self.vinculos})))
        for v in self.vinculos:
            self._status(v, NAO_VINCULADA, "aguardando o cadastro")

    # ------------------------------------------------------------------ status
    def _status(self, v, status, detalhe=""):
        if (v["status"], v["detalhe"]) != (status, detalhe) and status not in LIBERADOS:
            logger.warning("Fonte %s: %s %s" % (v["chave"], status, detalhe))
        v["status"], v["detalhe"] = status, detalhe
        runtime_status.set_fonte(v["chave"], estacao=v["estacao"], fonte=v["fonte"],
                                 pasta=v["pasta"], status=status, detalhe=detalhe)

    def _cor(self):
        if not self.vinculos:
            return "red"
        if self.db is not None and not self.db_ok:
            return "red"
        if any(v["status"] not in LIBERADOS for v in self.vinculos):
            return "red"
        return "green"

    # ---------------------------------------------------------------- cadastro
    def atualizar_cadastro(self, forcar=False):
        """Relê o cadastro do banco (a cada 10 min) e decide o status de cada
        vínculo. Sem banco: usa o cache local para continuar lendo."""
        if not forcar and time.time() - self._ultimo_cadastro < INTERVALO_CADASTRO:
            return
        # No ciclo o ping já foi feito (evita 2 tentativas de conexão por
        # rodada com o banco fora); chamada avulsa (UI/testes) faz o ping.
        if self._ping_do_ciclo is not None:
            online = self._ping_do_ciclo
        else:
            online = self.db is not None and self.db.ping()
        if not online:
            for v in self.vinculos:
                linha = self.cache.buscar(v["estacao"], v["fonte"])
                if linha and self.cache.confirmado(linha["station_pk"]) and v["status"] in (NAO_VINCULADA, OK, SEM_BANCO):
                    v["linha"] = linha
                    self._status(v, SEM_BANCO if self.db is not None else OK, "cadastro de %s" % self.cache.atualizado_em())
                elif not linha:
                    self._status(v, NAO_VINCULADA, "sem banco e sem cadastro local")
            return

        self._ultimo_cadastro = time.time()
        versao = self.db.versao_schema()
        self.schema_ok = versao == SCHEMA_SUPORTADO
        runtime_status.set("schema_status", "v%s" % versao)
        if not self.schema_ok:
            for v in self.vinculos:
                self._status(v, SCHEMA, "banco na versão %s, cliente %s espera %s"
                             % (versao, CLIENT_VERSION, SCHEMA_SUPORTADO))
            return

        catalogo = {StationCache.chave(r["estacao_codigo"], r["fonte_codigo"]): r
                    for r in self.db.listar_catalogo()}
        guardar = {}
        for v in self.vinculos:
            linha = catalogo.get(v["chave"])
            v["linha"] = linha
            if linha is None:
                self._status(v, NAO_CADASTRADA, "%s não existe no cadastro deste domínio" % v["chave"])
                continue
            guardar[v["chave"]] = linha
            self._avaliar(v, linha)
        self.cache.guardar(guardar)

    def _avaliar(self, v, linha):
        inativos = [nome for nome, campo in (("planta", "planta_ativa"), ("seção", "secao_ativa"),
                                             ("linha", "linha_ativa"), ("estação", "estacao_ativa"),
                                             ("fonte", "fonte_ativa"), ("formato", "formato_ativo"))
                    if not linha.get(campo)]
        if inativos:
            return self._status(v, INATIVA, "desativado no cadastro: " + ", ".join(inativos))
        if _versao_tupla(linha.get("versao_min_cliente")) > _versao_tupla(CLIENT_VERSION):
            return self._status(v, ATUALIZAR, "o formato %s exige o cliente %s (este é %s)"
                                % (linha["formato_codigo"], linha["versao_min_cliente"], CLIENT_VERSION))
        ok, motivo = registry.formato_suportado(linha)
        if not ok:
            return self._status(v, FORMATO, motivo)

        host = linha.get("host_vinculado")
        pk = linha["station_pk"]
        if host == self.host:
            self.cache.confirmar(pk)
            return self._status(v, OK, "")
        if host:
            return self._status(v, OUTRO_PC, "a estação está vinculada ao PC %s; este PC é %s. "
                                "Peça à engenharia para liberar o vínculo." % (host, self.host))
        if self.cache.confirmado(pk):
            return self._status(v, LIBERADO, "a engenharia liberou o vínculo deste PC. "
                                "Para voltar a gravar aqui, use FONTES DESTE PC > Vincular de novo.")
        try:
            self.db.vincular(v["estacao"])
            self.cache.confirmar(pk)
            linha["host_vinculado"] = self.host
            self._status(v, OK, "vinculada agora a este PC")
        except CadastroRecusado as e:
            self._status(v, RECUSADA, "%s (%s)" % (e.mensagem, e.pgcode))
        except ConnectionError as e:
            self._status(v, NAO_VINCULADA, "banco caiu durante o vínculo: %s" % e)

    # ------------------------------------------------------------- fila offline
    def reenviar_fila(self):
        pendentes = self.fila.peek_all()
        if not pendentes:
            return
        validos = [p for p in pendentes if p.get("fonte_id")]
        if len(validos) < len(pendentes):
            logger.warning("Fila offline: %d registro(s) sem fonte_id (formato do cliente 1.x) "
                           "descartados" % (len(pendentes) - len(validos)))
        grupos = {}
        for p in validos:
            grupos.setdefault(p["fonte_id"], []).append(p)
        sobrou = []
        for fonte_id, itens in grupos.items():
            if sobrou and not self.db_ok:
                sobrou += itens
                continue
            try:
                n = self.db.insert_rows(itens)
                runtime_status.mark_insert("offline_queue", n)
                logger.info("Fila offline: %d registro(s) da fonte %s reenviados" % (n, fonte_id))
            except CadastroRecusado as e:
                logger.error("Fila offline: fonte %s recusada (%s) — %d registro(s) continuam na fila"
                             % (fonte_id, e.mensagem, len(itens)))
                sobrou += itens
            except ConnectionError:
                self.db_ok = False
                sobrou += itens
        self.fila.rewrite(sobrou)
        runtime_status.set("offline_queue_count", self.fila.count())

    # ------------------------------------------------------------------- ciclo
    def ciclo(self):
        """Uma rodada completa. Devolve a cor da bandeja."""
        mappings = load_mappings()
        usa_banco = self.db is not None and self.modo in ("database", "both")

        if self.modo == "sync":
            # Só cópia de arquivos: não depende do cadastro nem do banco
            for v in self.vinculos:
                if not os.path.isdir(v["pasta"]):
                    self._status(v, PASTA, v["pasta"])
                elif v["sync_destino"]:
                    self._status(v, OK, "somente cópia")
                    self._sincronizar(v)
                else:
                    self._status(v, ERRO, "modo sync sem sync_destino")
            return self._cor()

        if usa_banco:
            era_ok = self.db_ok
            self.db_ok = self.db.ping()
            runtime_status.set("db_status", "ONLINE" if self.db_ok else "OFFLINE")
            if self.db_ok and not era_ok:
                self._ultimo_cadastro = 0      # banco voltou: relê o cadastro já
        self._ping_do_ciclo = self.db_ok if usa_banco else False
        try:
            self.atualizar_cadastro()
        finally:
            self._ping_do_ciclo = None

        if usa_banco and self.db_ok and self.schema_ok:
            self.reenviar_fila()
        runtime_status.set("offline_queue_count", self.fila.count())

        total_arquivos = 0
        for v in self.vinculos:
            if v["status"] not in LIBERADOS and v["status"] != PASTA:
                continue
            if not os.path.isdir(v["pasta"]):
                self._status(v, PASTA, v["pasta"])
                continue
            if v["status"] == PASTA:
                self._status(v, OK if self.db_ok or not usa_banco else SEM_BANCO, "")

            if self.modo in ("sync", "both") and v["sync_destino"]:
                self._sincronizar(v)

            if not usa_banco or not self.db_ok or not self.schema_ok:
                continue      # banco fora: não lê — o offset guarda a posição
            linha = v["linha"]
            arquivos = sorted(_list_files(v["pasta"], linha.get("padrao_arquivo"), linha.get("recursivo")))
            total_arquivos += len(arquivos)
            for caminho in arquivos:
                if not self._processar_arquivo(v, caminho, mappings):
                    break
            if not self.db_ok:
                break

        runtime_status.set("files_monitored", total_arquivos)
        runtime_status.set("current_file", "")
        return self._cor()

    def _sincronizar(self, v):
        r = sync_folder(source_folder=v["pasta"], destination_folder=v["sync_destino"],
                        mode=self.sync_modo, recursive=bool((v["linha"] or {}).get("recursivo")))
        runtime_status.set("sync_status", "ERRO" if r["error"] else "OK")
        for k in ("checked", "copied", "deleted"):
            runtime_status.set("sync_" + k, r.get(k, 0))
        runtime_status.set("sync_last_file", r["error"] or r.get("last_file", ""))
        runtime_status.set("sync_last_time", r.get("last_sync_time", ""))
        if r["error"]:
            logger.error("SYNC %s: %s" % (v["chave"], r["error"]))

    def _processar_arquivo(self, v, caminho, mappings):
        """Lê e grava um arquivo. False = parar esta fonte nesta rodada."""
        linha = v["linha"]
        nome = os.path.basename(caminho)
        chave_offset = "%s|%s" % (linha["fonte_id"], caminho)
        runtime_status.set("current_file", nome)
        try:
            parsed = registry.ler(linha, caminho, self.offsets.get(chave_offset))
        except (OSError, ValueError) as e:
            logger.error("Fonte %s: não foi possível ler %s: %s" % (v["chave"], nome, e))
            return True

        skipped = parsed.get("skipped") or []
        if skipped:
            runtime_status.increment("session_rows_skipped", len(skipped))
            logger.warning("%d linha(s) rejeitada(s) em %s: " % (len(skipped), nome)
                           + ", ".join("#%s(%s)" % (n, r) for n, r in skipped[:20])
                           + (" ..." if len(skipped) > 20 else ""))
        if not parsed["rows"]:
            if skipped:        # só lixo: avança para não reprocessar para sempre
                self.offsets.update(chave_offset, parsed["new_offset"], parsed["new_line_no"], parsed["file_size"])
            return True

        source_key = _source_key(caminho, v["pasta"])
        schema = parsed["schema"]
        h = schema_hash(schema["headers"])
        lote, modelo, versao = registry.montar_lote(linha, parsed, caminho, source_key, h, mappings)

        if linha.get("formato_tipo") == "DEDICADO":
            faltando = detect_unmapped_fields(parsed["rows"][0], modelo, mappings)
            if faltando:
                runtime_status.set("unmapped_fields_alert", {"file": nome, "model": modelo, "fields": faltando})

        try:
            self.db.upsert_schema(h, modelo, versao, nome, schema["headers"], schema["upper_map"],
                                  schema["lower_map"], schema["unit_map"])
            if self.spec.get("enabled"):
                divergencias = validate_schema_limits(model_name=modelo, schema=schema,
                                                      spec_file_name=self.spec.get("file", "spec_limits.csv"))
                n = self.db.insert_spec_mismatches(linha["fonte_id"], modelo, versao, source_key, h, divergencias)
                runtime_status.set("spec_mismatch_count", n)
            inseridos = self.db.insert_rows(lote)
        except CadastroRecusado as e:
            self._status(v, RECUSADA, "%s (%s)" % (e.mensagem, e.pgcode))
            self._ultimo_cadastro = 0          # relê o cadastro na próxima rodada
            return False
        except ConnectionError as e:
            self.fila.push_many(lote)
            self.db_ok = False
            runtime_status.set("offline_queue_count", self.fila.count())
            runtime_status.mark_error("Banco caiu ao gravar %s: %s (lote na fila offline)" % (nome, e))
            logger.error("Banco caiu ao gravar %s; %d linha(s) na fila offline: %s" % (nome, len(lote), e))
            # Na fila: avança o offset para não empilhar o mesmo lote de novo
            self.offsets.update(chave_offset, parsed["new_offset"], parsed["new_line_no"], parsed["file_size"])
            return False
        except Exception as e:
            # Erro de dado (ex.: valor que o banco não aceita): não avança o
            # offset nem põe na fila; a fonte fica em ERRO até alguém olhar.
            self._status(v, ERRO, "%s: %s" % (nome, str(e).strip().splitlines()[0] if str(e).strip() else repr(e)))
            logger.exception("Erro ao gravar %s" % nome)
            return False

        self.offsets.update(chave_offset, parsed["new_offset"], parsed["new_line_no"], parsed["file_size"])
        ultimo = lote[-1]
        runtime_status.mark_insert(file_name=nome, batch_size=inseridos,
                                   last_serial=ultimo.get("serial_number") or "",
                                   last_result=ultimo.get("result_status") or "",
                                   last_model=modelo, last_version=versao)
        runtime_status.set_fonte(v["chave"], ultimo_arquivo=nome, somar_total=inseridos,
                                 ultimo_insert=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        if v["status"] == ERRO:
            self._status(v, OK, "")
        logger.info("%s: %d linha(s) de %s" % (v["chave"], inseridos, nome))
        return True


# -----------------------------------------------------------------------------
# LAÇO PRINCIPAL (thread daemon iniciada pela UI)
# -----------------------------------------------------------------------------

def start_monitor(stop_event=None, status_callback=None, encerrar=None):
    """stop_event: pausa (STOP/START). encerrar: termina esta thread de vez
    (reinício depois de salvar a configuração — antes a thread antiga
    continuava viva e passava a rodar junto com a nova)."""
    config = load_config()
    intervalo = (config.get("parser") or {}).get("scan_interval", 5)
    modo = (config.get("operation") or {}).get("mode", "database").lower()
    usa_banco = (config.get("database") or {}).get("enabled", True) and modo in ("database", "both")
    db = DBWriter(config) if usa_banco else None
    mon = MonitorFontes(config, db=db, status_callback=status_callback)

    runtime_status.set("client_status", "RUNNING")
    runtime_status.set("client_version", CLIENT_VERSION)
    runtime_status.set("operation_mode", modo)
    logger.info("MONITOR INICIADO — cliente %s, PC %s, modo %s, %d fonte(s): %s"
                % (CLIENT_VERSION, mon.host, modo, len(mon.vinculos),
                   ", ".join("%s<-%s" % (v["chave"], v["pasta"]) for v in mon.vinculos) or "nenhuma"))
    if not mon.vinculos:
        runtime_status.set("last_error", "Nenhuma fonte vinculada. Abra CONFIG > FONTES DESTE PC.")

    while not (encerrar and encerrar.is_set()):
        if stop_event and stop_event.is_set():
            runtime_status.set("client_status", "STOPPED")
            _update_tray_color(status_callback, "yellow")
            time.sleep(1)
            continue
        runtime_status.set("client_status", "RUNNING")
        try:
            _update_tray_color(status_callback, mon.ciclo())
        except Exception as e:
            runtime_status.mark_error(str(e))
            logger.exception("Erro no monitor: %s" % e)
            _update_tray_color(status_callback, "red")
        # dorme em passos de 0,5 s para o encerramento ser rápido
        fim = time.time() + intervalo
        while time.time() < fim and not (encerrar and encerrar.is_set()):
            time.sleep(0.5)
    if db:
        db.close()
    logger.info("MONITOR ENCERRADO (reinício)")
