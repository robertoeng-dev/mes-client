# Guia de Deploy — MES Client v1.0.4

Procedimento para implantar/atualizar o MES Client nas estações PCM Tester da
linha de produção (Salcomp Manaus).

## O que muda nesta versão (v1.0.3 → v1.0.4)

Correções de confiabilidade de dados. **Nenhuma mudança de funcionalidade** — as
telas e o fluxo do operador são idênticos. O que muda é o que o cliente faz
quando algo dá errado:

| Situação | Antes | Agora |
|---|---|---|
| Banco cai durante o reenvio da fila offline | Os registros eram apagados do disco antes do INSERT ser confirmado — se ele falhasse, sumiam | A fila só é apagada depois que o banco confirma |
| Banco fica fora por horas | `offline_queue.jsonl` crescia a cada ciclo com as mesmas linhas repetidas | O monitor espera sem empilhar; o offset preserva a posição |
| Dois CSVs de mesmo nome em subpastas (`recursive: true`) | O segundo era descartado em silêncio pela deduplicação | Cada um tem sua chave — os dois entram |
| Coluna de resultado com `PENDING` / `TESTING` | Virava `FAIL` e contaminava o yield | Preservado como veio |
| Queda de energia gravando `offsets.json` | Arquivo corrompido impedia o monitor de subir | Escrita atômica; se ainda assim corromper, recomeça em vez de travar |

### ⚠ Ponto de atenção na migração — `source_file`

A coluna `source_file` passou a guardar o **caminho relativo** a `log.folder`
(ex.: `A17/2026-09-09.csv`) em vez de só o nome do arquivo (`2026-09-09.csv`).
A deduplicação usa `(station_id, source_file, source_line_no)`.

Consequência prática: na primeira execução após a atualização, as linhas dos
CSVs já processados **serão reinseridas**, porque a chave mudou. Escolha uma das
opções antes de subir em produção:

- **Corte pela data** (mais simples) — aceite a reinserção. As duplicatas ficam
  distinguíveis por `created_at` e pelo formato de `source_file`.
- **Migrar os registros antigos** — se o mapeamento de arquivo para subpasta for
  conhecido e sem ambiguidade:
  ```sql
  UPDATE mes_test_results
  SET source_file = 'A17/' || source_file
  WHERE station_id = 'PCM_A17_BR-PCMTEST-01'
    AND source_file NOT LIKE '%/%';
  ```
- **Zerar o offset** — apagar `offsets.json` na estação faz o cliente reler tudo
  já com a chave nova. Só faz sentido se o volume histórico for pequeno.

Se a estação **não** usa `log.recursive: true`, o caminho relativo é igual ao
nome do arquivo e nada muda.

## Antes de instalar em produção

1. **Rodar a regressão contra os CSVs reais da estação**, para confirmar que
   nenhuma linha legítima é rejeitada:
   ```powershell
   cd D:\MES_Client_Complete
   .venv\Scripts\python.exe tests\regression_real_files.py
   ```
   Isso lê os arquivos listados em `offsets.json` (os CSVs reais que a
   estação já processou) do zero e reporta quantas linhas seriam aceitas vs.
   rejeitadas, sem escrever no banco. **Se qualquer linha esperada aparecer
   como rejeitada, pare e investigue antes de prosseguir.**

2. Rodar os testes sintéticos (rápidos, sem banco):
   ```powershell
   .venv\Scripts\python.exe tests\test_parser_validation.py
   .venv\Scripts\python.exe tests\test_correcoes_fase_a.py
   ```

## Instalação (por estação)

1. Copie `installer\Output\MES_Client_Setup_v1.0.4.exe` para a estação (via
   pendrive ou rede).
2. Se já existe uma instalação anterior rodando, feche-a pelo ícone da
   bandeja (STOP/EXIT) antes de instalar por cima.
3. Execute o instalador **como Administrador**.
4. No wizard, confirme modelo, ID da máquina, pasta de CSVs e dados do banco
   — o instalador tenta reaproveitar `config.yaml` existente se já houver um.
5. Ao final, o MES Client inicia automaticamente (ícone na bandeja).

## Verificação pós-instalação

1. Ícone da bandeja **verde** = monitor ativo, dados sendo enviados.
2. Abra o log (`logs\client.log`, ou tela STATUS na bandeja) e confirme:
   ```
   MONITOR INICIADO
   Pasta monitorada: <pasta configurada>
   ```
3. Na tela STATUS, confirme **Versão do Client = 1.0.4**.
4. Linhas como esta são o gate de validação funcionando, não erro do cliente:
   ```
   N linha(s) rejeitada(s) em <arquivo>: #123(garbage_chars), #124(header_repeat) ...
   ```
   Só investigue se o **volume** de rejeições for muito maior que o previsto
   pela regressão do passo anterior.
5. **Novo nesta versão** — teste o comportamento com o banco fora: pare
   momentaneamente a rede ou o serviço do PostgreSQL e confirme que
   `offline_queue.jsonl` **não cresce** enquanto o banco está inacessível. Com o
   banco de volta, a fila é reenviada e só então apagada.
6. Confirme no dashboard (mes-server) que a estação aparece com dados novos
   dentro de alguns minutos.

## Rollback

Se algo der errado, o instalador anterior (`MES_Client_Setup_v1.0.3.exe`,
se ainda disponível) pode ser reinstalado por cima — `config.yaml` da
estação não é sobrescrito pelo instalador quando já existe.

Atenção: ao voltar para a v1.0.3, a chave `source_file` volta a ser o nome curto
do arquivo. Se linhas já foram gravadas com o caminho relativo, elas serão
reinseridas com a chave antiga.

## Homologação de múltiplas estações

Repita "Instalação" e "Verificação pós-instalação" em cada estação
individualmente. Não há dependência entre estações — uma instalação com
problema não afeta as demais.
