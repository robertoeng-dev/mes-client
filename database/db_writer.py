# =============================================================================
# db_writer.py — Escrita no banco de dados PostgreSQL
# =============================================================================
#
# Responsabilidades:
#   - Criar banco e tabelas automaticamente se não existirem
#   - Inserir lotes de resultados de teste (INSERT com ON CONFLICT DO NOTHING)
#   - Manter o schema de colunas detectado pelo parser (upsert)
#   - Registrar divergências de especificação (spec_mismatches)
#   - Reconectar automaticamente se a conexão cair (ping + reconnect)
#
# TABELAS criadas:
#   mes_csv_schemas     — catálogo de schemas de arquivos CSV detectados
#   {table}             — resultados de teste (nome configurável em config.yaml)
#   mes_spec_mismatches — divergências entre limites do testador e spec_limits.csv
# =============================================================================

import os
import json
import re

# PGCLIENTENCODING garante que dados com acentos/utf-8 cheguem corretos ao PostgreSQL
os.environ.setdefault("PGCLIENTENCODING", "UTF8")

import psycopg2
from psycopg2.extras import execute_values

from config.loader import load_config
from state.app_context import runtime_status
from logs.logger_setup import get_logger

logger = get_logger()


# Caracteres de controle ASCII que quebram JSONB no PostgreSQL.
# \x00 (null byte) é o mais comum no PCM Tester — o banco rejeita se não remover.
CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")


def sanitize_value(value):
    """Remove caracteres invisíveis que quebram JSONB no PostgreSQL.
    Aplica recursivamente em dicts e listas."""
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
    """Sanitiza e serializa para string JSON (necessário para colunas JSONB)."""
    clean_data = sanitize_value(data)
    # ensure_ascii=True: evita problemas de encoding ao gravar no banco
    return json.dumps(clean_data, ensure_ascii=True)


class DBWriter:
    # -------------------------------------------------------------------------
    # INICIALIZAÇÃO
    # -------------------------------------------------------------------------
    def __init__(self):
        self.config = load_config()
        self.conn = None
        self.cur = None

        # Valida o nome da tabela antes de usá-lo em SQL (previne SQL injection)
        raw_table = self.config["database"].get("table", "mes_test_results")
        if not re.match(r"^[a-zA-Z_]\w*$", raw_table):
            raise ValueError(f"Nome de tabela inválido: '{raw_table}'. Use apenas letras, números e '_'.")
        self.table = raw_table

        # Fluxo de inicialização: criar banco → conectar → criar tabelas/índices
        self._ensure_database()
        self._connect()

        if self.conn:
            self._ensure_tables()

    def _admin_conn(self):
        """Conexão administrativa ao banco 'postgres' (para criar outros bancos)."""
        return psycopg2.connect(
            host=self.config["database"]["host"],
            port=self.config["database"]["port"],
            dbname="postgres",          # banco padrão do PostgreSQL — sempre existe
            user=self.config["database"]["user"],
            password=self.config["database"]["password"],
            options="-c client_encoding=UTF8"
        )

    def _ensure_database(self):
        """Cria o banco de dados configurado se ele ainda não existir.
        Usa conexão admin ao 'postgres' com autocommit (CREATE DATABASE exige isso)."""
        dbname = self.config["database"]["name"]

        try:
            conn = self._admin_conn()
            conn.autocommit = True      # CREATE DATABASE não pode rodar dentro de transação
            cur = conn.cursor()

            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,))

            if not cur.fetchone():
                cur.execute(f'CREATE DATABASE "{dbname}"')
                logger.info(f"Banco criado automaticamente: {dbname}")

            cur.close()
            conn.close()

        except Exception as e:
            runtime_status.set("db_status", "OFFLINE")
            logger.warning(f"Não foi possível validar/criar o banco automaticamente: {repr(e)}")

    def _connect(self):
        """Conecta ao banco de dados configurado. Marca status ONLINE/OFFLINE."""
        try:
            self.conn = psycopg2.connect(
                host=self.config["database"]["host"],
                port=self.config["database"]["port"],
                dbname=self.config["database"]["name"],
                user=self.config["database"]["user"],
                password=self.config["database"]["password"],
                options="-c client_encoding=UTF8"
            )

            self.conn.autocommit = False    # controle manual de transações (commit/rollback)
            self.cur = self.conn.cursor()
            runtime_status.set("db_status", "ONLINE")
            logger.info("Conexão com banco estabelecida.")

        except Exception as e:
            self.conn = None
            self.cur = None
            runtime_status.set("db_status", "OFFLINE")
            runtime_status.mark_error(f"Falha ao conectar no banco: {repr(e)}")
            logger.error(f"Falha ao conectar no banco: {repr(e)}")

    # -------------------------------------------------------------------------
    # HEALTH CHECK
    # -------------------------------------------------------------------------

    def ping(self):
        """Verifica se a conexão está ativa. Tenta reconectar se necessário.
        Retorna True se o banco está acessível."""
        if not self.conn or not self.cur:
            self._connect()
            return self.conn is not None

        try:
            # SELECT 1 é a query mais leve possível para testar a conexão
            self.cur.execute("SELECT 1")
            self.cur.fetchone()
            runtime_status.set("db_status", "ONLINE")
            return True

        except Exception as e:
            logger.error(f"Falha no ping do banco: {repr(e)}")
            self._connect()
            return self.conn is not None

    # -------------------------------------------------------------------------
    # CRIAÇÃO DE TABELAS E ÍNDICES
    # -------------------------------------------------------------------------

    def _ensure_tables(self):
        """Cria tabelas e índices se não existirem. Idempotente — seguro chamar sempre."""
        if not self.cur:
            return

        # Catálogo de schemas: guarda a estrutura de cada CSV detectado
        self.cur.execute("""
        CREATE TABLE IF NOT EXISTS mes_csv_schemas (
            id BIGSERIAL PRIMARY KEY,
            schema_hash TEXT UNIQUE,
            model_name TEXT,
            version_name TEXT,
            source_file_pattern TEXT,
            columns_json JSONB,
            upper_limits_json JSONB,
            lower_limits_json JSONB,
            units_json JSONB,
            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # Tabela principal de resultados (nome configurável)
        self.cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {self.table} (
            id BIGSERIAL PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            station_id TEXT,
            model_name TEXT,
            version_name TEXT,
            serial_number TEXT,
            result_status TEXT,
            test_start_time TEXT,
            test_stop_time TEXT,
            source_file TEXT,
            source_line_no INTEGER,
            schema_hash TEXT,
            row_data JSONB          -- linha completa do CSV em formato flexível
        )
        """)

        # Divergências entre limites do testador e spec_limits.csv
        self.cur.execute("""
        CREATE TABLE IF NOT EXISTS mes_spec_mismatches (
            id BIGSERIAL PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            station_id TEXT,
            model_name TEXT,
            version_name TEXT,
            source_file TEXT,
            schema_hash TEXT,
            step_key TEXT,
            step_name TEXT,
            unit TEXT,
            expected_lsl DOUBLE PRECISION,
            expected_usl DOUBLE PRECISION,
            tester_lsl DOUBLE PRECISION,
            tester_usl DOUBLE PRECISION,
            reason TEXT
        )
        """)

        # Índice único: evita duplicatas se o mesmo arquivo for processado duas vezes
        self.cur.execute(f"""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_{self.table}_source
        ON {self.table} (station_id, source_file, source_line_no)
        """)

        # Índices de busca para queries comuns no painel MES
        self.cur.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_{self.table}_serial
        ON {self.table} (serial_number)
        """)

        self.cur.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_{self.table}_result
        ON {self.table} (result_status)
        """)

        # GIN: índice especial do PostgreSQL para busca dentro de JSONB
        self.cur.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_{self.table}_jsonb
        ON {self.table}
        USING GIN (row_data)
        """)

        self.conn.commit()
        logger.info("Estrutura do banco validada/criada com sucesso.")

    # -------------------------------------------------------------------------
    # OPERAÇÕES DE ESCRITA
    # -------------------------------------------------------------------------

    def upsert_schema(
        self,
        schema_hash,
        model_name,
        version_name,
        source_file_pattern,
        columns_json,
        upper_limits_json,
        lower_limits_json,
        units_json
    ):
        """Insere ou atualiza o schema do CSV no catálogo.
        ON CONFLICT: se o hash já existe, atualiza last_seen e os dados."""
        if not self.ping():
            raise ConnectionError("Banco offline")

        self.cur.execute("""
        INSERT INTO mes_csv_schemas (
            schema_hash,
            model_name,
            version_name,
            source_file_pattern,
            columns_json,
            upper_limits_json,
            lower_limits_json,
            units_json
        )
        VALUES (%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb)
        ON CONFLICT (schema_hash)
        DO UPDATE SET
            last_seen = CURRENT_TIMESTAMP,
            model_name = EXCLUDED.model_name,
            version_name = EXCLUDED.version_name,
            source_file_pattern = EXCLUDED.source_file_pattern,
            columns_json = EXCLUDED.columns_json,
            upper_limits_json = EXCLUDED.upper_limits_json,
            lower_limits_json = EXCLUDED.lower_limits_json,
            units_json = EXCLUDED.units_json
        """, (
            sanitize_value(schema_hash),
            sanitize_value(model_name),
            sanitize_value(version_name),
            sanitize_value(source_file_pattern),
            to_json(columns_json),
            to_json(upper_limits_json),
            to_json(lower_limits_json),
            to_json(units_json),
        ))

    def insert_spec_mismatches(self, station_id, model_name, version_name, source_file, schema_hash, mismatches):
        """Insere divergências de spec detectadas. Retorna quantidade inserida."""
        if not mismatches:
            return 0

        if not self.ping():
            raise ConnectionError("Banco offline")

        sql = """
        INSERT INTO mes_spec_mismatches (
            station_id,
            model_name,
            version_name,
            source_file,
            schema_hash,
            step_key,
            step_name,
            unit,
            expected_lsl,
            expected_usl,
            tester_lsl,
            tester_usl,
            reason
        )
        VALUES %s
        """

        values = []

        for m in mismatches:
            values.append((
                sanitize_value(station_id),
                sanitize_value(model_name),
                sanitize_value(version_name),
                sanitize_value(source_file),
                sanitize_value(schema_hash),
                sanitize_value(m.get("step_key")),
                sanitize_value(m.get("step_name")),
                sanitize_value(m.get("unit")),
                m.get("expected_lsl"),
                m.get("expected_usl"),
                m.get("tester_lsl"),
                m.get("tester_usl"),
                sanitize_value(m.get("reason")),
            ))

        # execute_values: insere múltiplas linhas de uma vez (muito mais rápido que um INSERT por linha)
        execute_values(self.cur, sql, values, page_size=100)
        self.conn.commit()
        return len(values)

    def insert_rows(self, rows):
        """Insere lote de resultados de teste.
        ON CONFLICT DO NOTHING: ignora silenciosamente duplicatas (idempotente)."""
        if not rows:
            return 0

        if not self.ping():
            raise ConnectionError("Banco offline")

        sql = f"""
        INSERT INTO {self.table} (
            station_id,
            model_name,
            version_name,
            serial_number,
            result_status,
            test_start_time,
            test_stop_time,
            source_file,
            source_line_no,
            schema_hash,
            row_data
        )
        VALUES %s
        ON CONFLICT (station_id, source_file, source_line_no) DO NOTHING
        """

        values = []

        for item in rows:
            values.append((
                sanitize_value(item["station_id"]),
                sanitize_value(item["model_name"]),
                sanitize_value(item["version_name"]),
                sanitize_value(item["serial_number"]),
                sanitize_value(item["result_status"]),
                sanitize_value(item["test_start_time"]),
                sanitize_value(item["test_stop_time"]),
                sanitize_value(item["source_file"]),
                item["source_line_no"],
                sanitize_value(item["schema_hash"]),
                to_json(item["row_data"])
            ))

        execute_values(self.cur, sql, values, page_size=200)
        self.conn.commit()
        runtime_status.set("db_status", "ONLINE")
        logger.info(f"Lote inserido com sucesso. Quantidade: {len(values)}")
        return len(values)

    def rollback(self):
        """Desfaz a transação atual. Chamado quando insert_rows falha
        para não deixar dados parciais no banco."""
        if self.conn:
            self.conn.rollback()
            logger.warning("Rollback executado no banco.")
