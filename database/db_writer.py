# =============================================================================
# db_writer.py — Acesso do cliente ao banco do domínio (mes_nonalpha/mes_alpha)
# =============================================================================
#
# Cliente 2.0 (cadastro centralizado, schema v2 = database/002_cadastro.sql):
#   - NÃO cria banco, tabela nem índice. O schema é do servidor; o cliente só
#     confere a versão (mes_schema_version) e recusa gravar se for outra.
#   - Lê o cadastro (v_cadastro_fontes) e vincula a estação a este PC pela
#     função mes_vincular_estacao (o cliente não tem UPDATE no catálogo).
#   - Grava resultados por FONTE (fonte_id). station_pk/linha_id são
#     preenchidos pelo trigger do banco, que também recusa estação/fonte
#     inativa e PC diferente do vinculado (SQLSTATE MS0xx).
#   - O nome do PC vai no application_name da conexão (é o que o banco
#     compara com mes_estacoes.host_vinculado).
#   - Conexão em AUTOCOMMIT: leituras e ping não deixam a sessão
#     "idle in transaction" (bug do v1.0.x, pendência 21). Lotes usam
#     BEGIN/COMMIT explícitos.
# =============================================================================

import json
import os
import re
import socket

os.environ.setdefault("PGCLIENTENCODING", "UTF8")

import psycopg2
import psycopg2.errors
import psycopg2.extras
from psycopg2.extras import execute_values

from config.loader import load_config
from state.app_context import runtime_status
from logs.logger_setup import get_logger

logger = get_logger()

SCHEMA_SUPORTADO = 2

CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")


def sanitize_value(value):
    """Remove caracteres de controle que quebram JSONB/texto no PostgreSQL."""
    if value is None:
        return None
    if isinstance(value, str):
        return CONTROL_CHARS_RE.sub("", value)
    if isinstance(value, dict):
        return {sanitize_value(k): sanitize_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_value(v) for v in value]
    return value


def to_json(data):
    return json.dumps(sanitize_value(data), ensure_ascii=True)


def host_do_pc(config):
    """Nome do PC enviado ao banco: cliente.host_id do config ou COMPUTERNAME."""
    h = ((config or {}).get("cliente") or {}).get("host_id") \
        or os.environ.get("COMPUTERNAME") or socket.gethostname()
    return str(h).strip().upper()[:63]


class CadastroRecusado(Exception):
    """O banco recusou pela regra do cadastro (estação/fonte inativa, não
    vinculada, outro PC, vínculo recusado). Não adianta repetir nem pôr na
    fila: só a engenharia resolve no MES Cadastro."""

    def __init__(self, pgcode, mensagem):
        super().__init__(mensagem)
        self.pgcode = pgcode
        self.mensagem = mensagem


def _erro_conexao(e):
    return isinstance(e, (psycopg2.OperationalError, psycopg2.InterfaceError))


def _mensagem(e):
    diag = getattr(e, "diag", None)
    return ((diag.message_primary if diag else None) or str(e)).strip()


class DBWriter:
    def __init__(self, config=None, host_id=None):
        self.config = config or load_config()
        self.db = self.config["database"]
        self.host_id = host_id or host_do_pc(self.config)
        self.conn = None
        self._connect()

    # -------------------------------------------------------------------------
    # CONEXÃO
    # -------------------------------------------------------------------------
    def _connect(self):
        kwargs = dict(
            host=self.db["host"], port=self.db.get("port", 5432), dbname=self.db["name"],
            user=self.db["user"], application_name=self.host_id,
            connect_timeout=int(self.db.get("connect_timeout", 8)),
            options="-c client_encoding=UTF8",
        )
        # Sem senha no config → libpq usa o pgpass.conf (testes/homologação)
        if self.db.get("password"):
            kwargs["password"] = self.db["password"]
        if self.db.get("sslmode"):
            kwargs["sslmode"] = self.db["sslmode"]
        try:
            self.conn = psycopg2.connect(**kwargs)
            self.conn.autocommit = True
            if self.db.get("set_role"):          # só nos testes (mes_homolog → mes_grp_client)
                self.conn.cursor().execute("SET ROLE %s" % psycopg2.extensions.quote_ident(
                    self.db["set_role"], self.conn))
            runtime_status.set("db_status", "ONLINE")
            logger.info("Conexão com banco %s estabelecida (PC %s)." % (self.db["name"], self.host_id))
        except Exception as e:
            self.conn = None
            runtime_status.set("db_status", "OFFLINE")
            runtime_status.set("last_error", "Falha ao conectar no banco: %s" % _mensagem(e))
            logger.error("Falha ao conectar no banco: %r" % e)

    def close(self):
        if self.conn:
            try:
                self.conn.close()
            except Exception:
                pass
        self.conn = None

    def ping(self):
        """True se o banco responde. Reconecta se a conexão caiu."""
        if self.conn is None or self.conn.closed:
            self._connect()
            return self.conn is not None
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            runtime_status.set("db_status", "ONLINE")
            return True
        except Exception as e:
            logger.error("Falha no ping do banco: %r" % e)
            self.close()
            self._connect()
            return self.conn is not None

    def _cursor(self, dict_rows=False):
        if not self.ping():
            raise ConnectionError("Banco offline")
        return self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor if dict_rows else None)

    def _executar(self, func):
        """Roda func(cur) numa transação. Traduz erros:
        conexão → ConnectionError (vai para a fila); MS0xx → CadastroRecusado."""
        cur = self._cursor()
        try:
            cur.execute("BEGIN")
            resultado = func(cur)
            cur.execute("COMMIT")
            return resultado
        except Exception as e:
            try:
                if not self.conn.closed:
                    cur.execute("ROLLBACK")
            except Exception:
                self.close()
            if _erro_conexao(e):
                self.close()
                raise ConnectionError(_mensagem(e))
            pgcode = getattr(e, "pgcode", None)
            if pgcode and pgcode.startswith("MS"):
                raise CadastroRecusado(pgcode, _mensagem(e))
            raise
        finally:
            cur.close()

    def rollback(self):
        """Compatibilidade: em autocommit não há transação pendente."""
        return None

    # -------------------------------------------------------------------------
    # CADASTRO
    # -------------------------------------------------------------------------
    def versao_schema(self):
        with self._cursor() as cur:
            try:
                cur.execute("SELECT max(versao) FROM mes_schema_version")
                return cur.fetchone()[0]
            except psycopg2.errors.UndefinedTable:
                return None

    def listar_catalogo(self):
        """Todas as fontes do domínio (linhas de v_cadastro_fontes)."""
        with self._cursor(dict_rows=True) as cur:
            cur.execute("SELECT * FROM v_cadastro_fontes ORDER BY planta_codigo, secao_codigo, "
                        "linha_codigo, estacao_codigo, fonte_codigo")
            return [dict(r) for r in cur.fetchall()]

    def vincular(self, estacao_codigo):
        """Vincula a estação a este PC. Devolve station_pk.
        Recusa → CadastroRecusado (MS010..MS013)."""
        def f(cur):
            cur.execute("SELECT mes_vincular_estacao(%s)", (estacao_codigo,))
            return cur.fetchone()[0]
        pk = self._executar(f)
        logger.info("Estação %s vinculada ao PC %s" % (estacao_codigo, self.host_id))
        return pk

    # -------------------------------------------------------------------------
    # RESULTADOS
    # -------------------------------------------------------------------------
    def upsert_schema(self, schema_hash, model_name, version_name, source_file_pattern,
                      columns_json, upper_limits_json, lower_limits_json, units_json):
        def f(cur):
            cur.execute("""
            INSERT INTO mes_csv_schemas (schema_hash, model_name, version_name, source_file_pattern,
                                         columns_json, upper_limits_json, lower_limits_json, units_json)
            VALUES (%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb)
            ON CONFLICT (schema_hash) DO UPDATE SET
                last_seen = now(),
                model_name = EXCLUDED.model_name,
                version_name = EXCLUDED.version_name,
                source_file_pattern = EXCLUDED.source_file_pattern,
                columns_json = EXCLUDED.columns_json,
                upper_limits_json = EXCLUDED.upper_limits_json,
                lower_limits_json = EXCLUDED.lower_limits_json,
                units_json = EXCLUDED.units_json
            """, (sanitize_value(schema_hash), sanitize_value(model_name), sanitize_value(version_name),
                  sanitize_value(source_file_pattern), to_json(columns_json), to_json(upper_limits_json),
                  to_json(lower_limits_json), to_json(units_json)))
        self._executar(f)

    def insert_spec_mismatches(self, fonte_id, model_name, version_name, source_file, schema_hash, mismatches):
        if not mismatches:
            return 0
        values = [(fonte_id, sanitize_value(model_name), sanitize_value(version_name),
                   sanitize_value(source_file), sanitize_value(schema_hash),
                   sanitize_value(m.get("step_key")), sanitize_value(m.get("step_name")),
                   sanitize_value(m.get("unit")), m.get("expected_lsl"), m.get("expected_usl"),
                   m.get("tester_lsl"), m.get("tester_usl"), sanitize_value(m.get("reason")))
                  for m in mismatches]

        def f(cur):
            execute_values(cur, """
            INSERT INTO mes_spec_mismatches (fonte_id, model_name, version_name, source_file, schema_hash,
                step_key, step_name, unit, expected_lsl, expected_usl, tester_lsl, tester_usl, reason)
            VALUES %s""", values, page_size=100)
        self._executar(f)
        return len(values)

    # test_*_time chegam como texto sem fuso (hora local da planta); o banco
    # converte com o fuso da planta (coluna TIMESTAMPTZ, sessão em UTC).
    _TEMPLATE = ("(%s,%s,%s,%s,%s,%s,(%s::timestamp AT TIME ZONE %s),(%s::timestamp AT TIME ZONE %s),"
                 "%s,%s,%s,%s,%s::jsonb)")

    def insert_rows(self, rows):
        """Insere o lote numa transação. Duplicata (mesma fonte+arquivo+linha)
        é ignorada pelo ON CONFLICT DO NOTHING — sem lista de colunas, porque
        o cliente não tem SELECT nos resultados. Devolve len(rows)."""
        if not rows:
            return 0
        values = []
        for it in rows:
            fuso = it.get("fuso") or "UTC"
            values.append((
                it["fonte_id"], sanitize_value(it.get("model_name")), sanitize_value(it.get("version_name")),
                sanitize_value(it.get("serial_number")), sanitize_value(it.get("result_status")),
                sanitize_value(it.get("defeito")),
                it.get("test_start_time"), fuso, it.get("test_stop_time"), fuso,
                sanitize_value(it.get("anexo_path")), sanitize_value(it["source_file"]),
                it["source_line_no"], sanitize_value(it.get("schema_hash")), to_json(it.get("row_data")),
            ))

        def f(cur):
            execute_values(cur, """
            INSERT INTO mes_test_results (fonte_id, model_name, version_name, serial_number,
                result_status, defeito, test_start_time, test_stop_time, anexo_path,
                source_file, source_line_no, schema_hash, row_data)
            VALUES %s
            ON CONFLICT DO NOTHING""", values, template=self._TEMPLATE, page_size=200)
        self._executar(f)
        runtime_status.set("db_status", "ONLINE")
        return len(values)
