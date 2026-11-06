-- =============================================================================
-- 002_cadastro.sql — cadastro centralizado + resultados (schema versao 2)
--
-- Aplicado em CADA banco de dominio (mes_nonalpha, mes_alpha, homologacao),
-- sempre como o DONO do banco, para que os objetos pertencam a ele:
--
--   producao (no servidor):
--     sudo -u postgres psql -d mes_nonalpha -v ON_ERROR_STOP=1 \
--          -c "SET ROLE mes_owner_nonalpha" -f - < ~/002_cadastro.sql
--   homologacao/testes: conectado como mes_homolog (dono do banco).
--
-- Idempotente (IF NOT EXISTS / CREATE OR REPLACE / DROP TRIGGER IF EXISTS).
-- Sem comandos do psql (\...) para poder rodar tambem pelo psycopg2 nos testes.
--
-- Principios:
--   * O BANCO e' a fonte da verdade das regras. O app web (Django) e o cliente
--     so' repetem as validacoes para dar mensagem amigavel; quem garante e' aqui.
--   * Codigos (plantas, linhas, estacoes...) so' em MAIUSCULAS, sem acento nem
--     espaco: dominio mes_codigo. Nome de exibicao e' livre.
--   * Nada de DELETE do que ja' foi usado (FK RESTRICT); desativa-se (ativo=false).
--   * O codigo nao muda depois de usado (trigger); renomeia-se o "nome".
--   * Os resultados guardam um RETRATO de estacao/linha no momento do teste.
--   * Estacao so' grava do PC a que esta' vinculada (application_name).
--     Isso protege contra PC clonado/erro de instalacao, NAO contra ataque
--     (application_name e' informado pelo proprio cliente).
--
-- Grupos (criados no 000_roles_bancos.sql):
--   mes_grp_admin   app web: escreve no catalogo, le tudo
--   mes_grp_client  estacoes: le catalogo, grava resultados (colunas limitadas)
--   mes_grp_leitura dashboards: so' le
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 0. Versao do schema (o cliente confere na partida)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mes_schema_version (
    versao      integer PRIMARY KEY,
    descricao   text NOT NULL,
    aplicado_em timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- 1. Dominio de codigo
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
                   WHERE t.typname = 'mes_codigo' AND n.nspname = 'public') THEN
        CREATE DOMAIN mes_codigo AS text
            CONSTRAINT mes_codigo_formato
            CHECK (VALUE ~ '^[A-Z0-9]+([_-][A-Z0-9]+)*$' AND length(VALUE) <= 40);
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 2. Catalogo
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mes_plantas (
    planta_id     integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    codigo        mes_codigo NOT NULL UNIQUE,              -- MAO
    nome          text NOT NULL CHECK (btrim(nome) <> ''),
    fuso          text NOT NULL DEFAULT 'America/Manaus',  -- validado por trigger
    idioma        text NOT NULL DEFAULT 'pt-BR',
    ativo         boolean NOT NULL DEFAULT true,
    criado_em     timestamptz NOT NULL DEFAULT now(),
    atualizado_em timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS mes_projetos (
    projeto_id    integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    codigo        mes_codigo NOT NULL UNIQUE,
    nome          text NOT NULL CHECK (btrim(nome) <> ''),
    ativo         boolean NOT NULL DEFAULT true,
    criado_em     timestamptz NOT NULL DEFAULT now(),
    atualizado_em timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS mes_modelos (
    modelo_id     integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    projeto_id    integer REFERENCES mes_projetos ON DELETE RESTRICT,
    codigo        mes_codigo NOT NULL UNIQUE,              -- A08
    descricao     text,
    ativo         boolean NOT NULL DEFAULT true,
    criado_em     timestamptz NOT NULL DEFAULT now(),
    atualizado_em timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS mes_secoes (
    secao_id      integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    planta_id     integer NOT NULL REFERENCES mes_plantas ON DELETE RESTRICT,
    codigo        mes_codigo NOT NULL,                     -- SECAO_04
    nome          text NOT NULL CHECK (btrim(nome) <> ''),
    ativo         boolean NOT NULL DEFAULT true,
    criado_em     timestamptz NOT NULL DEFAULT now(),
    atualizado_em timestamptz NOT NULL DEFAULT now(),
    UNIQUE (planta_id, codigo)
);

CREATE TABLE IF NOT EXISTS mes_linhas (
    linha_id      integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    secao_id      integer NOT NULL REFERENCES mes_secoes ON DELETE RESTRICT,
    planta_id     integer NOT NULL REFERENCES mes_plantas ON DELETE RESTRICT, -- preenchido pelo trigger
    codigo        mes_codigo NOT NULL,                     -- CAIAPO
    nome          text NOT NULL CHECK (btrim(nome) <> ''),
    ativo         boolean NOT NULL DEFAULT true,
    criado_em     timestamptz NOT NULL DEFAULT now(),
    atualizado_em timestamptz NOT NULL DEFAULT now(),
    UNIQUE (planta_id, codigo)
);

CREATE TABLE IF NOT EXISTS mes_tipos_estacao (
    tipo_id       integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    codigo        mes_codigo NOT NULL UNIQUE,              -- FUNCIONAL
    sigla         mes_codigo NOT NULL UNIQUE CHECK (length(sigla) <= 6),  -- FT
    nome          text NOT NULL CHECK (btrim(nome) <> ''),
    ativo         boolean NOT NULL DEFAULT true,
    criado_em     timestamptz NOT NULL DEFAULT now(),
    atualizado_em timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS mes_formatos (
    formato_id         integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    codigo             mes_codigo NOT NULL UNIQUE,         -- P2500S, OCV_TABCUT...
    tipo               text NOT NULL CHECK (tipo IN ('CONFIGURAVEL', 'DEDICADO')),
    definicao          jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(definicao) = 'object'),
    versao_min_cliente text NOT NULL DEFAULT '2.0.0' CHECK (versao_min_cliente ~ '^[0-9]+\.[0-9]+\.[0-9]+$'),
    descricao          text,
    ativo              boolean NOT NULL DEFAULT true,
    criado_em          timestamptz NOT NULL DEFAULT now(),
    atualizado_em      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT mes_formatos_configuravel_tem_definicao
        CHECK (tipo = 'DEDICADO' OR definicao <> '{}'::jsonb)
);

CREATE TABLE IF NOT EXISTS mes_estacoes (
    station_pk      integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    codigo          mes_codigo NOT NULL UNIQUE,            -- CAIAPO-M13-FT
    linha_id        integer NOT NULL REFERENCES mes_linhas ON DELETE RESTRICT,
    tipo_id         integer NOT NULL REFERENCES mes_tipos_estacao ON DELETE RESTRICT,
    maquina         mes_codigo NOT NULL,                   -- M13
    modelo_atual_id integer REFERENCES mes_modelos ON DELETE RESTRICT,
    descricao       text,
    host_vinculado  text,                                  -- nome do PC (maiusculas)
    vinculado_em    timestamptz,
    ativo           boolean NOT NULL DEFAULT true,
    criado_em       timestamptz NOT NULL DEFAULT now(),
    atualizado_em   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (linha_id, maquina, tipo_id),
    CHECK (host_vinculado IS NULL OR host_vinculado = upper(btrim(host_vinculado)))
);

CREATE TABLE IF NOT EXISTS mes_fontes (
    fonte_id       integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    station_pk     integer NOT NULL REFERENCES mes_estacoes ON DELETE RESTRICT,
    codigo         mes_codigo NOT NULL,                    -- FT, OCV, AOI
    formato_id     integer NOT NULL REFERENCES mes_formatos ON DELETE RESTRICT,
    padrao_arquivo text NOT NULL DEFAULT '*.csv' CHECK (btrim(padrao_arquivo) <> ''),
    recursivo      boolean NOT NULL DEFAULT false,
    anexos         jsonb CHECK (anexos IS NULL OR jsonb_typeof(anexos) = 'object'),
    descricao      text,
    ativo          boolean NOT NULL DEFAULT true,
    criado_em      timestamptz NOT NULL DEFAULT now(),
    atualizado_em  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (station_pk, codigo)
);

-- Auditoria de tudo que muda no catalogo
CREATE TABLE IF NOT EXISTS mes_cadastro_log (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    em          timestamptz NOT NULL DEFAULT now(),
    tabela      text NOT NULL,
    operacao    text NOT NULL,
    chave       text,
    antes       jsonb,
    depois      jsonb,
    usuario_db  text NOT NULL,     -- role que fez a operacao (session_user)
    usuario_app text               -- usuario do app web (SET LOCAL mes.usuario_app)
);
CREATE INDEX IF NOT EXISTS idx_mes_cadastro_log_em ON mes_cadastro_log (em);

-- ---------------------------------------------------------------------------
-- 3. Resultados
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mes_test_results (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at      timestamptz NOT NULL DEFAULT now(),
    fonte_id        integer NOT NULL REFERENCES mes_fontes ON DELETE RESTRICT,
    station_pk      integer NOT NULL REFERENCES mes_estacoes ON DELETE RESTRICT, -- retrato (trigger)
    linha_id        integer NOT NULL REFERENCES mes_linhas ON DELETE RESTRICT,   -- retrato (trigger)
    model_name      text,
    version_name    text,
    serial_number   text,
    result_status   text,          -- PASS / FAIL / valor desconhecido preservado
    defeito         text,
    test_start_time timestamptz,
    test_stop_time  timestamptz,
    anexo_path      text,          -- caminho relativo da imagem copiada (AOI)
    source_file     text NOT NULL,
    source_line_no  integer NOT NULL,
    schema_hash     text,
    row_data        jsonb,
    CONSTRAINT uq_mes_test_results_source UNIQUE (fonte_id, source_file, source_line_no)
);
CREATE INDEX IF NOT EXISTS idx_mes_test_results_station_time ON mes_test_results (station_pk, test_start_time);
CREATE INDEX IF NOT EXISTS idx_mes_test_results_serial       ON mes_test_results (serial_number);
CREATE INDEX IF NOT EXISTS idx_mes_test_results_fonte_criado ON mes_test_results (fonte_id, created_at);
-- Sem GIN em row_data de proposito (relatorio 25/09: 0 uso, ~30% do tamanho).

CREATE TABLE IF NOT EXISTS mes_csv_schemas (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    schema_hash         text NOT NULL UNIQUE,
    model_name          text,
    version_name        text,
    source_file_pattern text,
    columns_json        jsonb,
    upper_limits_json   jsonb,
    lower_limits_json   jsonb,
    units_json          jsonb,
    first_seen          timestamptz NOT NULL DEFAULT now(),
    last_seen           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS mes_spec_mismatches (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at    timestamptz NOT NULL DEFAULT now(),
    fonte_id      integer NOT NULL REFERENCES mes_fontes ON DELETE RESTRICT,
    model_name    text,
    version_name  text,
    source_file   text,
    schema_hash   text,
    step_key      text,
    step_name     text,
    unit          text,
    expected_lsl  double precision,
    expected_usl  double precision,
    tester_lsl    double precision,
    tester_usl    double precision,
    reason        text
);

-- ---------------------------------------------------------------------------
-- 4. Funcoes de trigger
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_mes_atualizado_em() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.atualizado_em := now();
    RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION fn_mes_valida_fuso() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_timezone_names WHERE name = NEW.fuso) THEN
        RAISE EXCEPTION 'Fuso horario invalido: "%". Use um nome IANA, ex.: America/Manaus', NEW.fuso
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$$;

-- A secao nao muda de planta (as linhas dela ficariam na planta errada).
CREATE OR REPLACE FUNCTION fn_mes_secao_planta_fixa() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.planta_id <> OLD.planta_id THEN
        RAISE EXCEPTION 'A secao % nao pode mudar de planta. Crie uma secao nova na outra planta.', OLD.codigo
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$$;

-- planta_id da linha vem da secao. Linha pode mudar de secao, nao de planta.
CREATE OR REPLACE FUNCTION fn_mes_linha_planta() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    SELECT s.planta_id INTO NEW.planta_id FROM mes_secoes s WHERE s.secao_id = NEW.secao_id;
    IF TG_OP = 'UPDATE' AND NEW.planta_id <> OLD.planta_id THEN
        RAISE EXCEPTION 'A linha % nao pode mudar de planta (so de secao dentro da mesma planta).', OLD.codigo
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$$;

-- Codigo imutavel depois de usado.
-- Argumentos em trios: tabela_filha, coluna_filha, coluna_propria
--   (coluna_propria = a PK, ou 'codigo' quando a filha guarda o texto).
CREATE OR REPLACE FUNCTION fn_mes_codigo_imutavel() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    i       integer := 0;
    usado   boolean;
    valor   text;
BEGIN
    IF NEW.codigo IS NOT DISTINCT FROM OLD.codigo THEN
        RETURN NEW;
    END IF;
    WHILE i + 2 < TG_NARGS LOOP
        valor := to_jsonb(OLD) ->> TG_ARGV[i + 2];
        IF TG_ARGV[i + 2] = 'codigo' THEN
            EXECUTE format('SELECT EXISTS (SELECT 1 FROM %I WHERE %I = $1)', TG_ARGV[i], TG_ARGV[i + 1])
                INTO usado USING valor;
        ELSE
            EXECUTE format('SELECT EXISTS (SELECT 1 FROM %I WHERE %I = $1)', TG_ARGV[i], TG_ARGV[i + 1])
                INTO usado USING valor::integer;
        END IF;
        IF usado THEN
            RAISE EXCEPTION 'O codigo "%" (%) ja esta em uso e nao pode ser alterado. Altere so o nome, ou desative e cadastre outro.',
                OLD.codigo, TG_TABLE_NAME USING ERRCODE = 'check_violation';
        END IF;
        i := i + 3;
    END LOOP;
    RETURN NEW;
END
$$;

-- Auditoria (SECURITY DEFINER: grava no log mesmo sem o usuario ter INSERT nele)
CREATE OR REPLACE FUNCTION fn_mes_auditoria() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
    linha jsonb := CASE WHEN TG_OP = 'DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
BEGIN
    INSERT INTO mes_cadastro_log (tabela, operacao, chave, antes, depois, usuario_db, usuario_app)
    VALUES (TG_TABLE_NAME, TG_OP, linha ->> TG_ARGV[0],
            CASE WHEN TG_OP <> 'INSERT' THEN to_jsonb(OLD) END,
            CASE WHEN TG_OP <> 'DELETE' THEN to_jsonb(NEW) END,
            session_user,
            nullif(current_setting('mes.usuario_app', true), ''));
    RETURN NULL;
END
$$;

-- Resultado: valida a fonte/estacao/vinculo e grava o retrato estacao+linha.
-- O cliente nao tem permissao de INSERT em station_pk/linha_id (column grant),
-- entao nao consegue falsificar esses valores.
CREATE OR REPLACE FUNCTION fn_mes_resultado_preparar() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    f      record;
    v_host text := upper(btrim(coalesce(current_setting('application_name', true), '')));
BEGIN
    SELECT fo.ativo AS fonte_ativa, fo.codigo AS fonte_codigo,
           e.station_pk, e.codigo AS estacao, e.ativo AS estacao_ativa,
           e.host_vinculado, e.linha_id
      INTO f
      FROM mes_fontes fo JOIN mes_estacoes e ON e.station_pk = fo.station_pk
     WHERE fo.fonte_id = NEW.fonte_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Fonte % nao cadastrada', NEW.fonte_id USING ERRCODE = 'foreign_key_violation';
    END IF;
    IF NOT f.estacao_ativa THEN
        RAISE EXCEPTION 'Gravacao recusada: estacao % esta INATIVA no cadastro', f.estacao USING ERRCODE = 'MS002';
    END IF;
    IF NOT f.fonte_ativa THEN
        RAISE EXCEPTION 'Gravacao recusada: fonte % da estacao % esta INATIVA', f.fonte_codigo, f.estacao USING ERRCODE = 'MS003';
    END IF;
    IF f.host_vinculado IS NULL THEN
        RAISE EXCEPTION 'Gravacao recusada: estacao % nao esta vinculada a nenhum PC', f.estacao USING ERRCODE = 'MS004';
    END IF;
    IF f.host_vinculado <> v_host THEN
        RAISE EXCEPTION 'Gravacao recusada: estacao % esta vinculada ao PC %, mas este PC se identifica como "%"',
            f.estacao, f.host_vinculado, v_host USING ERRCODE = 'MS005';
    END IF;

    NEW.station_pk := f.station_pk;
    NEW.linha_id   := f.linha_id;
    RETURN NEW;
END
$$;

-- ---------------------------------------------------------------------------
-- 5. Funcao de vinculo (chamada pelo cliente; ele nao tem UPDATE na tabela)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION mes_vincular_estacao(p_codigo text) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
    v_host text := upper(btrim(coalesce(current_setting('application_name', true), '')));
    r      mes_estacoes%ROWTYPE;
BEGIN
    IF v_host = '' THEN
        RAISE EXCEPTION 'Vinculo recusado: a conexao nao informou o nome do PC (application_name)' USING ERRCODE = 'MS010';
    END IF;
    SELECT * INTO r FROM mes_estacoes WHERE codigo = upper(btrim(p_codigo)) FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Estacao "%" nao cadastrada', p_codigo USING ERRCODE = 'MS011';
    END IF;
    IF NOT r.ativo THEN
        RAISE EXCEPTION 'Estacao % esta INATIVA', r.codigo USING ERRCODE = 'MS012';
    END IF;
    IF r.host_vinculado IS NOT NULL AND r.host_vinculado <> v_host THEN
        RAISE EXCEPTION 'Estacao % ja esta vinculada ao PC %. Peca a engenharia para liberar o vinculo no MES Cadastro.',
            r.codigo, r.host_vinculado USING ERRCODE = 'MS013';
    END IF;
    IF r.host_vinculado IS NULL THEN
        UPDATE mes_estacoes SET host_vinculado = v_host, vinculado_em = now()
         WHERE station_pk = r.station_pk;
    END IF;
    RETURN r.station_pk;
END
$$;
REVOKE ALL ON FUNCTION mes_vincular_estacao(text) FROM PUBLIC;

-- ---------------------------------------------------------------------------
-- 6. Triggers (recriados a cada aplicacao)
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    t record;
BEGIN
    FOR t IN SELECT * FROM (VALUES
        ('mes_plantas', 'planta_id'), ('mes_projetos', 'projeto_id'), ('mes_modelos', 'modelo_id'),
        ('mes_secoes', 'secao_id'), ('mes_linhas', 'linha_id'), ('mes_tipos_estacao', 'tipo_id'),
        ('mes_formatos', 'formato_id'), ('mes_estacoes', 'station_pk'), ('mes_fontes', 'fonte_id')
    ) AS v(tabela, pk)
    LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS trg_atualizado_em ON %I', t.tabela);
        EXECUTE format('CREATE TRIGGER trg_atualizado_em BEFORE UPDATE ON %I
                        FOR EACH ROW EXECUTE FUNCTION fn_mes_atualizado_em()', t.tabela);
        EXECUTE format('DROP TRIGGER IF EXISTS trg_auditoria ON %I', t.tabela);
        EXECUTE format('CREATE TRIGGER trg_auditoria AFTER INSERT OR UPDATE OR DELETE ON %I
                        FOR EACH ROW EXECUTE FUNCTION fn_mes_auditoria(%L)', t.tabela, t.pk);
    END LOOP;
END
$$;

DROP TRIGGER IF EXISTS trg_valida_fuso ON mes_plantas;
CREATE TRIGGER trg_valida_fuso BEFORE INSERT OR UPDATE OF fuso ON mes_plantas
    FOR EACH ROW EXECUTE FUNCTION fn_mes_valida_fuso();

DROP TRIGGER IF EXISTS trg_secao_planta_fixa ON mes_secoes;
CREATE TRIGGER trg_secao_planta_fixa BEFORE UPDATE OF planta_id ON mes_secoes
    FOR EACH ROW EXECUTE FUNCTION fn_mes_secao_planta_fixa();

DROP TRIGGER IF EXISTS trg_linha_planta ON mes_linhas;
CREATE TRIGGER trg_linha_planta BEFORE INSERT OR UPDATE ON mes_linhas
    FOR EACH ROW EXECUTE FUNCTION fn_mes_linha_planta();

-- codigo imutavel depois de usado: (tabela_filha, coluna_filha, coluna_propria)*
DROP TRIGGER IF EXISTS trg_codigo_imutavel ON mes_plantas;
CREATE TRIGGER trg_codigo_imutavel BEFORE UPDATE OF codigo ON mes_plantas FOR EACH ROW
    EXECUTE FUNCTION fn_mes_codigo_imutavel('mes_secoes', 'planta_id', 'planta_id');
DROP TRIGGER IF EXISTS trg_codigo_imutavel ON mes_projetos;
CREATE TRIGGER trg_codigo_imutavel BEFORE UPDATE OF codigo ON mes_projetos FOR EACH ROW
    EXECUTE FUNCTION fn_mes_codigo_imutavel('mes_modelos', 'projeto_id', 'projeto_id');
DROP TRIGGER IF EXISTS trg_codigo_imutavel ON mes_modelos;
CREATE TRIGGER trg_codigo_imutavel BEFORE UPDATE OF codigo ON mes_modelos FOR EACH ROW
    EXECUTE FUNCTION fn_mes_codigo_imutavel('mes_estacoes', 'modelo_atual_id', 'modelo_id',
                                            'mes_test_results', 'model_name', 'codigo');
DROP TRIGGER IF EXISTS trg_codigo_imutavel ON mes_secoes;
CREATE TRIGGER trg_codigo_imutavel BEFORE UPDATE OF codigo ON mes_secoes FOR EACH ROW
    EXECUTE FUNCTION fn_mes_codigo_imutavel('mes_linhas', 'secao_id', 'secao_id');
DROP TRIGGER IF EXISTS trg_codigo_imutavel ON mes_linhas;
CREATE TRIGGER trg_codigo_imutavel BEFORE UPDATE OF codigo ON mes_linhas FOR EACH ROW
    EXECUTE FUNCTION fn_mes_codigo_imutavel('mes_estacoes', 'linha_id', 'linha_id',
                                            'mes_test_results', 'linha_id', 'linha_id');
DROP TRIGGER IF EXISTS trg_codigo_imutavel ON mes_tipos_estacao;
CREATE TRIGGER trg_codigo_imutavel BEFORE UPDATE OF codigo, sigla ON mes_tipos_estacao FOR EACH ROW
    EXECUTE FUNCTION fn_mes_codigo_imutavel('mes_estacoes', 'tipo_id', 'tipo_id');
DROP TRIGGER IF EXISTS trg_codigo_imutavel ON mes_formatos;
CREATE TRIGGER trg_codigo_imutavel BEFORE UPDATE OF codigo ON mes_formatos FOR EACH ROW
    EXECUTE FUNCTION fn_mes_codigo_imutavel('mes_fontes', 'formato_id', 'formato_id');
DROP TRIGGER IF EXISTS trg_codigo_imutavel ON mes_estacoes;
CREATE TRIGGER trg_codigo_imutavel BEFORE UPDATE OF codigo ON mes_estacoes FOR EACH ROW
    EXECUTE FUNCTION fn_mes_codigo_imutavel('mes_fontes', 'station_pk', 'station_pk',
                                            'mes_test_results', 'station_pk', 'station_pk');
DROP TRIGGER IF EXISTS trg_codigo_imutavel ON mes_fontes;
CREATE TRIGGER trg_codigo_imutavel BEFORE UPDATE OF codigo ON mes_fontes FOR EACH ROW
    EXECUTE FUNCTION fn_mes_codigo_imutavel('mes_test_results', 'fonte_id', 'fonte_id');

DROP TRIGGER IF EXISTS trg_resultado_preparar ON mes_test_results;
CREATE TRIGGER trg_resultado_preparar BEFORE INSERT ON mes_test_results
    FOR EACH ROW EXECUTE FUNCTION fn_mes_resultado_preparar();

-- ---------------------------------------------------------------------------
-- 7. Views
-- ---------------------------------------------------------------------------
-- Catalogo achatado: o que o cliente usa para vincular e o app web para listar
CREATE OR REPLACE VIEW v_cadastro_fontes AS
SELECT fo.fonte_id, fo.codigo AS fonte_codigo, fo.padrao_arquivo, fo.recursivo, fo.anexos,
       fo.ativo AS fonte_ativa,
       fm.formato_id, fm.codigo AS formato_codigo, fm.tipo AS formato_tipo, fm.definicao,
       fm.versao_min_cliente, fm.ativo AS formato_ativo,
       e.station_pk, e.codigo AS estacao_codigo, e.maquina, e.descricao AS estacao_descricao,
       e.host_vinculado, e.vinculado_em, e.ativo AS estacao_ativa,
       te.codigo AS tipo_codigo, te.sigla AS tipo_sigla,
       mo.codigo AS modelo_atual,
       l.linha_id, l.codigo AS linha_codigo, l.nome AS linha_nome, l.ativo AS linha_ativa,
       s.secao_id, s.codigo AS secao_codigo, s.nome AS secao_nome, s.ativo AS secao_ativa,
       p.planta_id, p.codigo AS planta_codigo, p.nome AS planta_nome, p.fuso, p.ativo AS planta_ativa
  FROM mes_fontes fo
  JOIN mes_formatos fm       ON fm.formato_id = fo.formato_id
  JOIN mes_estacoes e        ON e.station_pk  = fo.station_pk
  JOIN mes_tipos_estacao te  ON te.tipo_id    = e.tipo_id
  LEFT JOIN mes_modelos mo   ON mo.modelo_id  = e.modelo_atual_id
  JOIN mes_linhas l          ON l.linha_id    = e.linha_id
  JOIN mes_secoes s          ON s.secao_id    = l.secao_id
  JOIN mes_plantas p         ON p.planta_id   = l.planta_id;

-- Resultados com a hierarquia (linha = retrato do momento do teste)
CREATE OR REPLACE VIEW v_mes_test_results AS
SELECT r.id, r.created_at, r.test_start_time,
       (r.test_start_time AT TIME ZONE p.fuso) AS test_start_local,
       p.codigo AS planta, s.codigo AS secao, l.codigo AS linha,
       e.codigo AS estacao, e.maquina, te.sigla AS tipo, fo.codigo AS fonte,
       pr.codigo AS projeto, r.model_name, r.version_name,
       r.serial_number, r.result_status, r.defeito, r.anexo_path,
       r.source_file, r.source_line_no, r.schema_hash, r.row_data,
       r.fonte_id, r.station_pk, r.linha_id
  FROM mes_test_results r
  JOIN mes_fontes fo        ON fo.fonte_id  = r.fonte_id
  JOIN mes_estacoes e       ON e.station_pk = r.station_pk
  JOIN mes_tipos_estacao te ON te.tipo_id   = e.tipo_id
  JOIN mes_linhas l         ON l.linha_id   = r.linha_id
  JOIN mes_secoes s         ON s.secao_id   = l.secao_id
  JOIN mes_plantas p        ON p.planta_id  = l.planta_id
  LEFT JOIN mes_modelos m   ON m.codigo     = r.model_name
  LEFT JOIN mes_projetos pr ON pr.projeto_id = m.projeto_id;

-- Vida de um serial pelas estacoes (OCV -> AOI -> FT ...)
CREATE OR REPLACE VIEW v_rastreabilidade_serial AS
SELECT serial_number, test_start_time, test_start_local, planta, linha, estacao, tipo, fonte,
       model_name, result_status, defeito, anexo_path, id
  FROM v_mes_test_results
 WHERE serial_number IS NOT NULL;

-- Ultimo dado por fonte (tela "Atividade" do app web)
CREATE OR REPLACE VIEW v_atividade_fontes AS
SELECT c.planta_codigo, c.linha_codigo, c.estacao_codigo, c.fonte_codigo, c.fonte_id,
       c.host_vinculado, c.estacao_ativa, c.fonte_ativa,
       u.ultimo_dado, d.testes_24h, d.reprovados_24h
  FROM v_cadastro_fontes c
  LEFT JOIN LATERAL (SELECT max(r.created_at) AS ultimo_dado
                       FROM mes_test_results r WHERE r.fonte_id = c.fonte_id) u ON true
  LEFT JOIN LATERAL (SELECT count(*) AS testes_24h,
                            count(*) FILTER (WHERE r.result_status = 'FAIL') AS reprovados_24h
                       FROM mes_test_results r
                      WHERE r.fonte_id = c.fonte_id AND r.created_at > now() - interval '24 hours') d ON true;

-- ---------------------------------------------------------------------------
-- 8. Permissoes
-- ---------------------------------------------------------------------------
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;

-- Catalogo
GRANT SELECT ON mes_schema_version, mes_plantas, mes_projetos, mes_modelos, mes_secoes, mes_linhas,
                mes_tipos_estacao, mes_formatos, mes_estacoes, mes_fontes, v_cadastro_fontes
      TO mes_grp_admin, mes_grp_client, mes_grp_leitura;
GRANT INSERT, UPDATE, DELETE ON mes_plantas, mes_projetos, mes_modelos, mes_secoes, mes_linhas,
                mes_tipos_estacao, mes_formatos, mes_estacoes, mes_fontes
      TO mes_grp_admin;
GRANT SELECT ON mes_cadastro_log TO mes_grp_admin, mes_grp_leitura;

-- Resultados: o cliente so' insere, e so' nas colunas que lhe cabem.
-- O cliente deve usar "ON CONFLICT DO NOTHING" SEM lista de colunas: com a
-- lista, o PostgreSQL exige SELECT nas colunas da chave, e o cliente nao le
-- resultados (de proposito). A unica chave unica alem do id e'
-- uq_mes_test_results_source, entao o efeito e' o mesmo.
GRANT INSERT (fonte_id, model_name, version_name, serial_number, result_status, defeito,
              test_start_time, test_stop_time, anexo_path, source_file, source_line_no,
              schema_hash, row_data)
      ON mes_test_results TO mes_grp_client;
GRANT SELECT ON mes_test_results, v_mes_test_results, v_rastreabilidade_serial, v_atividade_fontes,
                mes_csv_schemas, mes_spec_mismatches
      TO mes_grp_admin, mes_grp_leitura;
GRANT SELECT, INSERT, UPDATE ON mes_csv_schemas TO mes_grp_client;
GRANT INSERT ON mes_spec_mismatches TO mes_grp_client;

GRANT EXECUTE ON FUNCTION mes_vincular_estacao(text) TO mes_grp_client;

-- ---------------------------------------------------------------------------
-- 9. Formatos com parser dedicado (ligados ao codigo do cliente)
-- ---------------------------------------------------------------------------
INSERT INTO mes_formatos (codigo, tipo, versao_min_cliente, descricao)
VALUES ('P2500S',     'DEDICADO', '2.0.0', 'BW P2500S (Teste Funcional Caiapo): CSV 46 colunas, pares Max/Min, canais 1A..4B'),
       ('PCM_TESTER', 'DEDICADO', '2.0.0', 'PCM Tester / TestPad: CSV com cabecalho proprio, subpastas por modelo'),
       ('CYG',        'DEDICADO', '2.0.0', 'Formato CYG')
ON CONFLICT (codigo) DO NOTHING;

INSERT INTO mes_schema_version (versao, descricao)
VALUES (2, 'Cadastro centralizado: plantas, secoes, linhas, estacoes, fontes, formatos; resultados por fonte')
ON CONFLICT (versao) DO NOTHING;

COMMIT;
