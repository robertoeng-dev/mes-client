-- =============================================================================
-- 000_roles_bancos.sql — roles e bancos do MES (modelo novo, 05/11/2026)
--
-- Roda UMA vez no servidor, como superusuario, pelo psql (usa \gexec e \echo):
--     sudo -u postgres psql -v ON_ERROR_STOP=1 -f 000_roles_bancos.sql
-- Idempotente: pode rodar de novo sem erro e sem duplicar nada.
-- NAO toca no banco mes_db nem no role mes_user (ficam como arquivo).
--
-- SENHAS: este script NAO define senha nenhuma (o arquivo vai para o GitHub).
-- Os roles de login ficam sem senha (nao conseguem entrar) ate voce rodar,
-- no mesmo servidor, para cada um:
--     sudo -u postgres psql -c "\password mes_web"
-- (a lista completa sai no final da execucao).
--
-- Desenho de seguranca:
--   * Grupos (NOLOGIN) carregam os privilegios de tabela; o 002_cadastro.sql
--     concede SELECT/INSERT etc. a eles:
--       mes_grp_admin   -> escreve no catalogo (app web)
--       mes_grp_client  -> le o catalogo e grava resultados (estacoes)
--       mes_grp_leitura -> so le (dashboards / relatorios)
--   * A SEGREGACAO Alpha x Non-Alpha e' feita pelo CONNECT de cada banco: ele e'
--     revogado de PUBLIC e concedido so aos roles de LOGIN daquele dominio.
--     Nunca conceder CONNECT a um grupo — isso abriria o banco para todos os
--     membros, de qualquer dominio.
--   * Cada banco tem um dono NOLOGIN proprio (mes_owner_<dominio>). Os objetos
--     sao criados com SET ROLE para esse dono. Ninguem entra como dono.
-- =============================================================================

\set ON_ERROR_STOP 1

-- ---------------------------------------------------------------------------
-- 1. Roles
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    r record;
BEGIN
    FOR r IN SELECT * FROM (VALUES
        -- nome                     login  createdb
        ('mes_owner_nonalpha',     false, false),
        ('mes_owner_alpha',        false, false),
        ('mes_grp_admin',          false, false),
        ('mes_grp_client',         false, false),
        ('mes_grp_leitura',        false, false),
        ('mes_web',                true,  false),   -- app web: banco interno do Django
        ('mes_web_nonalpha',       true,  false),   -- app web: catalogo Non-Alpha
        ('mes_web_alpha',          true,  false),   -- app web: catalogo Alpha
        ('mes_client_nonalpha',    true,  false),   -- estacoes Non-Alpha
        ('mes_client_alpha',       true,  false),   -- estacoes Alpha
        ('mes_leitura_nonalpha',   true,  false),   -- dashboards Non-Alpha
        ('mes_leitura_alpha',      true,  false),   -- dashboards Alpha
        ('mes_homolog',            true,  true)     -- testes (cria/apaga banco de teste)
    ) AS t(nome, login, createdb)
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r.nome) THEN
            EXECUTE format('CREATE ROLE %I %s %s NOSUPERUSER NOCREATEROLE',
                           r.nome,
                           CASE WHEN r.login THEN 'LOGIN' ELSE 'NOLOGIN' END,
                           CASE WHEN r.createdb THEN 'CREATEDB' ELSE 'NOCREATEDB' END);
            RAISE NOTICE 'role criado: %', r.nome;
        ELSE
            RAISE NOTICE 'role ja existe: %', r.nome;
        END IF;
    END LOOP;
END
$$;

-- Limite de conexoes por role (protege o servidor de um cliente em loop).
-- max_connections do servidor = 150 (001_ajuste_postgresql.sql); a soma dos
-- limites abaixo pode passar disso porque nem todos lotam ao mesmo tempo, mas
-- nenhum role sozinho consegue esgotar o servidor.
ALTER ROLE mes_client_nonalpha CONNECTION LIMIT 100;
ALTER ROLE mes_client_alpha    CONNECTION LIMIT 100;
ALTER ROLE mes_web             CONNECTION LIMIT 20;
ALTER ROLE mes_web_nonalpha    CONNECTION LIMIT 20;
ALTER ROLE mes_web_alpha       CONNECTION LIMIT 20;
ALTER ROLE mes_leitura_nonalpha CONNECTION LIMIT 30;
ALTER ROLE mes_leitura_alpha    CONNECTION LIMIT 30;
ALTER ROLE mes_homolog         CONNECTION LIMIT 20;

-- Quem cria objetos precisa poder fazer SET ROLE para o dono do banco
-- (postgres ja pode). Fuso padrao das sessoes do MES: UTC no banco; a
-- conversao para o fuso da planta e' feita nas views (mes_plantas.fuso).

-- Participacao nos grupos
GRANT mes_grp_admin   TO mes_web_nonalpha, mes_web_alpha;
GRANT mes_grp_client  TO mes_client_nonalpha, mes_client_alpha;
GRANT mes_grp_leitura TO mes_leitura_nonalpha, mes_leitura_alpha;
-- mes_homolog: precisa agir como cada grupo nos testes (SET ROLE), mas so
-- tem CONNECT no banco de homologacao, entao nao alcanca producao.
GRANT mes_grp_admin, mes_grp_client, mes_grp_leitura TO mes_homolog;

-- ---------------------------------------------------------------------------
-- 2. Bancos (CREATE DATABASE nao roda dentro de DO/transacao -> \gexec)
-- ---------------------------------------------------------------------------
SELECT format('CREATE DATABASE %I OWNER %I ENCODING %L TEMPLATE template0 LC_COLLATE %L LC_CTYPE %L',
              d.nome, d.dono, 'UTF8', 'C.UTF-8', 'C.UTF-8')
FROM (VALUES
    ('mes_nonalpha',          'mes_owner_nonalpha'),
    ('mes_alpha',             'mes_owner_alpha'),
    ('mes_nonalpha_homolog',  'mes_homolog'),
    ('mes_cadastro_app',      'mes_web')
) AS d(nome, dono)
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = d.nome)
\gexec

-- ---------------------------------------------------------------------------
-- 3. CONNECT: so os roles de login do proprio dominio
-- ---------------------------------------------------------------------------
REVOKE ALL ON DATABASE mes_nonalpha, mes_alpha, mes_nonalpha_homolog, mes_cadastro_app FROM PUBLIC;

GRANT CONNECT, TEMPORARY ON DATABASE mes_nonalpha
      TO mes_web_nonalpha, mes_client_nonalpha, mes_leitura_nonalpha;
GRANT CONNECT, TEMPORARY ON DATABASE mes_alpha
      TO mes_web_alpha, mes_client_alpha, mes_leitura_alpha;
GRANT CONNECT, TEMPORARY ON DATABASE mes_cadastro_app TO mes_web;
-- mes_nonalpha_homolog: o dono (mes_homolog) ja tem todos os privilegios.

-- Fuso das sessoes nos bancos novos (created_at/test_start_time sao TIMESTAMPTZ;
-- UTC no armazenamento, conversao por planta nas views)
ALTER DATABASE mes_nonalpha         SET timezone TO 'UTC';
ALTER DATABASE mes_alpha            SET timezone TO 'UTC';
ALTER DATABASE mes_nonalpha_homolog SET timezone TO 'UTC';
ALTER DATABASE mes_cadastro_app     SET timezone TO 'UTC';

-- Sessao esquecida "idle in transaction" segura o VACUUM e pode travar DDL.
-- O cliente v1.0.x fazia isso (ping SELECT 1 com autocommit=False, sem commit).
-- Nos bancos novos, o servidor encerra a sessao depois de 5 min parada assim
-- (o cliente novo reconecta sozinho). Nao afeta o mes_db.
ALTER DATABASE mes_nonalpha         SET idle_in_transaction_session_timeout TO '5min';
ALTER DATABASE mes_alpha            SET idle_in_transaction_session_timeout TO '5min';
ALTER DATABASE mes_nonalpha_homolog SET idle_in_transaction_session_timeout TO '5min';
ALTER DATABASE mes_cadastro_app     SET idle_in_transaction_session_timeout TO '5min';

-- ---------------------------------------------------------------------------
-- 4. Schema public de cada banco de dominio: ninguem alem do dono cria objetos
-- ---------------------------------------------------------------------------
\connect mes_nonalpha
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO mes_owner_nonalpha;
GRANT USAGE ON SCHEMA public TO mes_grp_admin, mes_grp_client, mes_grp_leitura;

\connect mes_alpha
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO mes_owner_alpha;
GRANT USAGE ON SCHEMA public TO mes_grp_admin, mes_grp_client, mes_grp_leitura;

\connect mes_nonalpha_homolog
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO mes_homolog;
GRANT USAGE ON SCHEMA public TO mes_grp_admin, mes_grp_client, mes_grp_leitura;

\connect mes_cadastro_app
ALTER SCHEMA public OWNER TO mes_web;

-- ---------------------------------------------------------------------------
-- 5. Proximo passo: senhas (interativo, nunca em arquivo)
-- ---------------------------------------------------------------------------
\echo ''
\echo '==================================================================='
\echo ' Roles e bancos prontos. Defina as senhas (uma por vez):'
\echo '   sudo -u postgres psql -c "\\password mes_web"'
\echo '   sudo -u postgres psql -c "\\password mes_web_nonalpha"'
\echo '   sudo -u postgres psql -c "\\password mes_web_alpha"'
\echo '   sudo -u postgres psql -c "\\password mes_client_nonalpha"'
\echo '   sudo -u postgres psql -c "\\password mes_client_alpha"'
\echo '   sudo -u postgres psql -c "\\password mes_leitura_nonalpha"'
\echo '   sudo -u postgres psql -c "\\password mes_leitura_alpha"'
\echo '   sudo -u postgres psql -c "\\password mes_homolog"'
\echo ' Use senhas diferentes e geradas (ex.: openssl rand -base64 24).'
\echo ' Confira o pg_hba.conf: as linhas existentes precisam aceitar esses'
\echo ' roles a partir da rede da fabrica (scram-sha-256).'
\echo '==================================================================='
