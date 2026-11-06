-- =============================================================================
-- 001_ajuste_postgresql.sql — memoria e conexoes do servidor brmaomits01
--
-- Base (levantamento de 05/11/2026): 4 vCPU, 3,3 GiB de RAM, swap 3,8 GiB,
-- disco virtual QEMU de 120 GB (tipo fisico desconhecido), PostgreSQL 18.6.
-- A RAM e' dividida com o app web (Django/gunicorn, ~300 MB) e o Samba.
--
-- Roda como superusuario:
--     sudo -u postgres psql -v ON_ERROR_STOP=1 -f 001_ajuste_postgresql.sql
-- e depois REINICIA o PostgreSQL (shared_buffers e max_connections so mudam
-- com restart):
--     sudo systemctl restart postgresql@18-main
--     sudo systemctl status postgresql@18-main --no-pager
--
-- Grava em postgresql.auto.conf via ALTER SYSTEM (nao edita postgresql.conf).
-- Para desfazer qualquer item:  ALTER SYSTEM RESET <parametro>;  + restart.
-- =============================================================================

\set ON_ERROR_STOP 1

\echo 'ANTES:'
SELECT name, setting, unit FROM pg_settings
WHERE name IN ('shared_buffers','effective_cache_size','work_mem','maintenance_work_mem','max_connections')
ORDER BY name;

ALTER SYSTEM SET shared_buffers       = '768MB';  -- ~23% da RAM (era 128MB, padrao de fabrica)
ALTER SYSTEM SET effective_cache_size = '2GB';    -- estimativa de cache do SO para o planejador
ALTER SYSTEM SET work_mem             = '16MB';   -- por operacao de ordenacao/hash
ALTER SYSTEM SET maintenance_work_mem = '256MB';  -- VACUUM / CREATE INDEX
ALTER SYSTEM SET max_connections      = 150;      -- era 100; estacoes + app web + dashboards
-- random_page_cost fica no padrao (4) ate o TI confirmar se o disco da VM e' SSD;
-- se for, use: ALTER SYSTEM SET random_page_cost = 1.1;

\echo ''
\echo 'Gravado em postgresql.auto.conf. Agora reinicie:'
\echo '    sudo systemctl restart postgresql@18-main'
\echo 'e confira com:'
\echo '    sudo -u postgres psql -c "SHOW shared_buffers" -c "SHOW max_connections"'
