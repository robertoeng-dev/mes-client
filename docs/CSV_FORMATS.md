# Suporte a Múltiplos Formatos de CSV

> **Resumo:** o MES Client aceita INSERT de qualquer CSV — com qualquer número de colunas e qualquer nome de cabeçalho — sem alterar o banco de dados. Esta página explica como isso funciona e como adicionar suporte a um novo modelo ou estação.

---

## Arquitetura em duas camadas

O processamento de CSV é separado em duas responsabilidades:

```
CSV (qualquer formato)
        │
        ▼
  parser/cyg_parser.py
  Lê TODAS as colunas que existirem → dict {coluna: valor}
  Não conhece os nomes antecipadamente — pega o que vier.
        │
        ▼
  monitor/file_monitor.py
  Tenta EXTRAIR campos conhecidos (serial, resultado, tempo...)
  O restante vai inteiro como dado bruto.
        │
        ▼
  database/db_writer.py → PostgreSQL
  Colunas estruturadas + JSONB com todo o conteúdo da linha
```

---

## Schema do banco — por que é flexível

A tabela principal **não tem uma coluna por medição**. O schema é fixo e não muda com novos formatos:

```sql
CREATE TABLE mes_test_results (
    id              BIGSERIAL PRIMARY KEY,
    created_at      TIMESTAMP,
    station_id      TEXT,          -- da config.yaml
    model_name      TEXT,          -- detectado ou da config.yaml
    version_name    TEXT,
    serial_number   TEXT,          -- extraído (pode ser NULL se coluna desconhecida)
    result_status   TEXT,          -- PASS / FAIL / NULL
    test_start_time TEXT,
    test_stop_time  TEXT,
    source_file     TEXT,
    source_line_no  INTEGER,
    schema_hash     TEXT,          -- identifica a estrutura do CSV
    row_data        JSONB          -- TODAS as colunas da linha, sem exceção
);
```

O campo `row_data JSONB` armazena o dicionário completo de cada linha — independente de quantas ou quais colunas existam. Uma linha com 8 colunas e outra com 80 colunas inserem sem nenhuma diferença.

---

## Catálogo automático de schemas (`mes_csv_schemas`)

Cada combinação única de cabeçalhos gera um hash MD5 e é registrada automaticamente:

```python
# monitor/file_monitor.py
def _schema_hash(headers):
    return hashlib.md5("|".join(headers).encode()).hexdigest()
```

A tabela `mes_csv_schemas` guarda, para cada schema detectado:

| Coluna | Conteúdo |
|---|---|
| `schema_hash` | Hash MD5 dos cabeçalhos (chave única) |
| `model_name` | Modelo associado |
| `columns_json` | Lista completa de colunas |
| `upper_limits_json` | Limites superiores por coluna (USL) |
| `lower_limits_json` | Limites inferiores por coluna (LSL) |
| `units_json` | Unidades por coluna |
| `first_seen` / `last_seen` | Quando o schema foi visto pela primeira vez e mais recentemente |

Um CSV do modelo A06 com 45 colunas e um do A17 com 60 colunas geram hashes diferentes e schemas separados no catálogo — sem conflito, na mesma tabela.

---

## Formatos suportados nativamente

| `station.type` no config.yaml | Formato | Estrutura |
|---|---|---|
| `PCM_TESTER` | PCM Tester | Linha 1: cabeçalhos. Linha 2: limites embutidos no texto `"Tensão(V)[3.75-3.85]"`. Linha 3+: dados |
| `CYG` | CYG / NAVAJO | Linha 1: cabeçalhos. Linha 2: USL. Linha 3: LSL. Linha 4: unidades. Linha 5+: dados |
| `FT` | Functional Test | Detectado como CYG (mesmo esquema de cabeçalho) |
| `AUTO` | Detecção automática | Heurística: se linha 2 contém `[número-número]` → PCM_TESTER, caso contrário → CYG |

---

## O que funciona automaticamente com qualquer CSV

| Comportamento | Resultado |
|---|---|
| Colunas a mais | Todas vão para `row_data` JSONB |
| Colunas a menos | As que faltam simplesmente não aparecem em `row_data` |
| Cabeçalhos com nomes desconhecidos | Aceitos normalmente — armazenados como estão |
| Novo modelo/estação | Schema catalogado automaticamente em `mes_csv_schemas` |
| Arquivo com schema diferente do anterior | Novo `schema_hash`, tratado como schema distinto |

---

## O que pode resultar em NULL (e como corrigir)

Alguns campos estruturados são **extraídos por nome de coluna**. Se o CSV usar nomes fora das listas abaixo, o campo extrai como `NULL` — mas o dado completo **ainda está em `row_data`**, sem perda.

### Campos extraídos e nomes reconhecidos

**`serial_number`** — `monitor/file_monitor.py:_resolve_serial_or_trace()`

```python
# PCM_TESTER: compõe chave composta (não tem serial único)
f"{machine_no}|CH{channel_no}|{device_name}|{test_time}"

# CYG / outros:
row.get("SerialNumber")
or row.get("serial_number")
or row.get("barcode")
or row.get("device_name")
```

**`result_status`** — `_resolve_result()`

```python
# PCM_TESTER:
row.get("test_result")

# CYG / outros:
row.get("Test PASS/FAIL STATUS")
or row.get("test_result")
or row.get("Result")
```

**`model_name`** — `_resolve_model_name()`

```python
# 1ª prioridade: nome do arquivo (ex: CYG_X30_20260622.csv → "X30")
# 2ª prioridade: coluna da linha
row.get("Model") or row.get("model") or row.get("proj_code")
# 3ª prioridade: station.model do config.yaml
```

**`test_start_time`** — `_resolve_test_start()`

```python
row.get("test_time")          # PCM_TESTER
or row.get("Test Start Time") # CYG
```

---

## Como adicionar suporte a um novo formato

### Caso 1 — Mesmo tipo de testador, coluna com nome diferente

Edite apenas `monitor/file_monitor.py`. Adicione o novo nome como fallback:

```python
# Exemplo: novo modelo usa "SN" no lugar de "SerialNumber"
def _resolve_serial_or_trace(row, station_type):
    ...
    return (
        row.get("SerialNumber")
        or row.get("serial_number")
        or row.get("barcode")
        or row.get("device_name")
        or row.get("SN")           # ← adiciona aqui
    )
```

**Não muda o banco. Não muda o parser. Não muda o config.yaml.**

### Caso 2 — Novo tipo de testador com estrutura própria

**Passo 1:** adicione o novo tipo no `config.yaml` de cada estação desse tipo:

```yaml
station:
  type: NOVO_TESTER   # nome que você escolher
```

**Passo 2:** adicione um bloco nas funções `_resolve_*` em `file_monitor.py`:

```python
def _resolve_serial_or_trace(row, station_type):
    if station_type == "NOVO_TESTER":
        return row.get("TraceID") or row.get("SN_PROD")
    ...

def _resolve_result(row, station_type):
    if station_type == "NOVO_TESTER":
        return _normalize_result(row.get("FinalResult"))
    ...
```

**Passo 3 (opcional):** se a estrutura de cabeçalho for diferente (linhas de metadados em posições diferentes), adicione a detecção em `parser/cyg_parser.py:detect_csv_format()`:

```python
def detect_csv_format(second_line_values, station_type="AUTO"):
    if station_type == "NOVO_TESTER":
        return "NOVO_TESTER"
    ...
```

E o tratamento correspondente em `read_header_and_meta()`.

### Caso 3 — CSV sem linha de limites (só cabeçalho + dados)

Defina `station_type: AUTO` e o sistema detecta automaticamente. Se a segunda linha não contém padrão `[número-número]`, trata como CYG: assume que linha 2 é USL, linha 3 é LSL, linha 4 é unidades — e se essas linhas forem dados reais, os limites ficarão incorretos no catálogo, mas **o INSERT dos dados funciona normalmente**.

Para evitar isso, force o tipo: `station_type: CYG` pula as linhas de metadados mesmo sem conteúdo válido nelas.

---

## Diagrama de decisão — o que acontece com um CSV novo

```
CSV novo detectado
        │
        ▼
  Lê cabeçalhos ──────────────────────────────────────────────────────────
        │                                                                  │
        ▼                                                                  │
  schema_hash = MD5(cabeçalhos)                                           │
        │                                                                  │
        ▼                                                                  ▼
  Hash já existe                                            Hash novo
  em mes_csv_schemas?                                            │
        │                                                         ▼
       SIM                                              Insere em mes_csv_schemas
        │                                               (colunas, limites, unidades)
        └──────────────┬──────────────────────────────────────────┘
                       │
                       ▼
              Para cada linha de dados:
                       │
                       ├─ Tenta extrair serial, resultado, tempo, modelo
                       │   (usando listas de nomes conhecidos)
                       │
                       ├─ Monta row_data = {todos os campos da linha}
                       │
                       └─ INSERT em mes_test_results
                           ON CONFLICT DO NOTHING
                           (deduplicação por station_id + arquivo + nº de linha)
```

---

## Consultando dados de formatos diferentes no PostgreSQL

Como todos os campos estão em `row_data JSONB`, você pode consultar qualquer coluna sem precisar de colunas fixas no schema:

```sql
-- Busca por coluna específica do CSV (qualquer nome)
SELECT station_id, model_name, row_data->>'Voltage_Step3'
FROM mes_test_results
WHERE model_name = 'A17';

-- Filtra por valor dentro do JSONB
SELECT COUNT(*) FROM mes_test_results
WHERE row_data->>'test_result' = 'FAIL'
  AND created_at > NOW() - INTERVAL '8 hours';

-- Lista todos os schemas de CSV já detectados
SELECT model_name, columns_json, first_seen
FROM mes_csv_schemas
ORDER BY first_seen DESC;

-- Compara schemas de dois modelos
SELECT a.model_name, a.columns_json, b.model_name, b.columns_json
FROM mes_csv_schemas a, mes_csv_schemas b
WHERE a.model_name = 'A06' AND b.model_name = 'A17';
```

---

## Arquivos relevantes

| Arquivo | Responsabilidade |
|---|---|
| `parser/cyg_parser.py` | Leitura incremental, detecção de formato, extração de cabeçalhos/limites |
| `monitor/file_monitor.py` | Funções `_resolve_*`, montagem do batch, schema_hash |
| `database/db_writer.py` | `upsert_schema()`, `insert_rows()`, schema do banco |
| `spec/spec_validator.py` | Validação de limites LSL/USL por modelo |
| `config.yaml` → `station.type` | Força o formato em vez de detectar automaticamente |
