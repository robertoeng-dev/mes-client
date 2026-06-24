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

Alguns campos estruturados são **extraídos por nome de coluna**. Se o CSV usar nomes não configurados, o campo fica `NULL` — mas o dado completo **ainda está em `row_data`**, sem perda.

### Campos estruturados e suas prioridades de resolução

| Campo no banco | Prioridade 1 | Prioridade 2 | Prioridade 3 |
|---|---|---|---|
| `serial_number` | Mapeamento do modelo em `column_mappings.json` | Mapeamento DEFAULT | NULL (PCM_TESTER usa chave composta — ver nota) |
| `result_status` | Mapeamento do modelo | Mapeamento DEFAULT | NULL |
| `model_name` | Nome do arquivo (ex: `CYG_A17_20260622.csv` → A17) | Mapeamento DEFAULT | `station.model` do `config.yaml` |
| `test_start_time` | Mapeamento do modelo | Mapeamento DEFAULT | NULL |
| `test_stop_time` | Mapeamento do modelo | Mapeamento DEFAULT | NULL |

> **Nota PCM_TESTER:** o serial é composto automaticamente por `_pcm_serial()` em `file_monitor.py`
> como `machine_no|CH{channel_no}|device_name|test_time` — protocolo fixo do equipamento.

---

## `column_mappings.json` — mapeamento configurável

O arquivo `column_mappings.json` define, para cada modelo (ou `DEFAULT`), quais colunas do CSV
correspondem a cada campo estruturado. É editado pela tela **MAPEAMENTO** na UI, sem abrir código.

```json
{
  "DEFAULT": {
    "serial_number":   ["SerialNumber", "serial_number", "barcode", "device_name"],
    "result_status":   ["test_result", "Test PASS/FAIL STATUS", "Result"],
    "model_name":      ["Model", "model", "proj_code"],
    "test_start_time": ["test_time", "Test Start Time"],
    "test_stop_time":  ["Test Stop Time", "stop_time"]
  },
  "X30": {
    "serial_number":  ["TraceID"],
    "result_status":  ["FinalResult"],
    "test_start_time":["StartTimestamp"]
  }
}
```

**Prioridade de resolução para cada linha:**
1. Procura no mapeamento do modelo específico (ex: `"X30"`)
2. Se não encontrar, usa `"DEFAULT"`
3. Retorna `NULL` se nenhuma coluna da lista existir na linha

O monitor recarrega o JSON **a cada ciclo de scan** — nenhum restart necessário após salvar.

---

## Como adicionar suporte a um novo formato

### Caso 1 — Mesmo equipamento, novo modelo com colunas diferentes

**Sem abrir código.** Abra o popup do tray → **MAPEAMENTO** → EDITAR → ADICIONAR:

```
Modelo:          X30
Campo MES:       Serial / Rastreio
Colunas no CSV:  TraceID, SN_PROD
```

Clique SALVAR. Na próxima varredura, o campo `serial_number` será extraído corretamente do modelo X30.

### Caso 2 — Novo tipo de testador com estrutura própria

**Passo 1:** defina o tipo no `config.yaml` da estação:

```yaml
station:
  type: NOVO_TESTER
```

**Passo 2 (sem código):** configure os mapeamentos de colunas pela tela MAPEAMENTO para cada campo.

**Passo 3 (somente se a estrutura de cabeçalho for diferente):** se o CSV tiver linhas de metadados em
posições diferentes das do CYG, adicione detecção em `parser/cyg_parser.py:detect_csv_format()`:

```python
def detect_csv_format(second_line_values, station_type="AUTO"):
    if station_type == "NOVO_TESTER":
        return "NOVO_TESTER"
    ...
```

E o tratamento correspondente em `read_header_and_meta()`.

### Caso 3 — CSV sem linha de limites (só cabeçalho + dados)

Defina `station_type: AUTO` e o sistema detecta automaticamente. Se a segunda linha não contém padrão
`[número-número]`, trata como CYG: assume que linha 2 é USL, linha 3 é LSL, linha 4 é unidades.

Para evitar confusão: force `station_type: CYG`.

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
| `monitor/file_monitor.py` | Montagem do batch, `_pcm_serial`, `schema_hash`, integração com column_mapper |
| `config/column_mapper.py` | `load_mappings`, `resolve_field`, `detect_unmapped_fields` |
| `column_mappings.json` | Mapeamento de colunas CSV → campos estruturados (editável via UI MAPEAMENTO) |
| `database/db_writer.py` | `upsert_schema()`, `insert_rows()`, schema do banco |
| `spec/spec_validator.py` | Validação de limites LSL/USL por modelo |
| `config.yaml` → `station.type` | Força o formato em vez de detectar automaticamente |
