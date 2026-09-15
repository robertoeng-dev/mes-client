# Manual de Instalação — MES Client v1.0.5

Procedimento para instalar, atualizar, verificar e remover o MES Client em uma
estação de teste. Cobre as estações **PCM Tester** (linhas Navajo, Tomahawk…)
e as estações **BW P2500S** da linha **Caiapó** (Teste Funcional M13 e Tab
Cutting, modelo A08), que entram nesta versão.

Salcomp Manaus — Engenharia de Teste. Setembro/2026.

---

## 1. O que você precisa antes de começar

| Item | Detalhe |
|---|---|
| `MES_Client_Setup_v1.0.5.exe` | Instalador único (≈ 23 MB, 100% offline, não baixa nada). Está em `installer\Output\` do repositório ou no pacote de instalação |
| Acesso de **Administrador** na estação | O instalador grava em `C:\Utility\MES` e registra tarefa no Task Scheduler |
| **Host** do PostgreSQL e **senha** do usuário `mes_user` | Peça à engenharia. O instalador não traz nenhum dos dois pré-preenchido, de propósito. **Não anote a senha em papel nem em arquivo** |
| Estação alcança o banco na porta 5432 | Teste antes: `Test-NetConnection <host> -Port 5432` no PowerShell da estação. `TcpTestSucceeded : True` é o que você quer. Se falhar, é firewall ou `pg_hba.conf`: chame TI/DBA **antes** de instalar |
| Pasta onde o testador grava os CSVs | PCM: `D:\Testpad software\CSV\<modelo>`. Caiapó: `D:\battData` (confira na estação, seção 3.2) |
| (Opcional) pasta de rede para cópia dos CSVs | Só se a linha tem esse compartilhamento definido. Vazio = não copia |

### ⚠ Instale logado na conta que a estação usa no dia a dia

O auto-start é uma tarefa agendada disparada **no logon da conta que rodou o
instalador**. Se você instalar com a sua conta de técnico e o operador entra
com outra, o cliente **nunca sobe sozinho** depois de reiniciar. Faça logon na
conta do operador e execute o instalador como Administrador a partir dela
(botão direito → *Executar como administrador*, informe a credencial de admin
no UAC).

Para operação 24h sem intervenção, a estação também precisa de **logon
automático do Windows** nessa conta. Sem isso, um reboot para na tela de
login e o cliente fica parado.

---

## 2. Instalação com wizard (estação a estação)

1. Copie o `MES_Client_Setup_v1.0.5.exe` para a estação (pendrive ou rede).
2. Se já existe um MES Client rodando, feche-o: botão direito no ícone da
   bandeja → **STOP** → **EXIT** (senha de ENGENHARIA). O instalador também
   tenta encerrar, mas fechar antes evita arquivo em uso.
3. Botão direito no instalador → **Executar como administrador**.
4. Preencha as 4 páginas:

### Página 1 — Configuração da Estação

| Campo | PCM Tester | Caiapó — Teste Funcional | Caiapó — Tab Cutting |
|---|---|---|---|
| Tipo da estação / prefixo | `PCM` | `FUNC` | `TABC` |
| Modelo do produto | `A17`, `A06`, `A16`… | `A08` | `A08` |
| ID da máquina | `BR-PCMTEST-01` | `CAIAPO-M13` | `CAIAPO-M13` |
| Tipo do testador | `AUTO` (ou `PCM_TESTER`) | `AUTO` (ou `P2500S`) | `AUTO` |

O **Station ID** é montado como `PREFIXO_MODELO_MAQUINA` — ex.:
`PCM_A17_BR-PCMTEST-01`, `FUNC_A08_CAIAPO-M13`, `TABC_A08_CAIAPO-M13`. Ele
identifica a estação no banco e no dashboard; **não pode mudar depois** sem
quebrar a continuidade do histórico.

`AUTO` reconhece o formato do CSV pelo próprio arquivo (PCM pelo padrão
`[min-max]` na 2ª linha, P2500S pelos `Max`/`Min` repetidos no cabeçalho). Só
force um tipo se o AUTO errar.

### Página 2 — Configuração de Arquivos

| Campo | PCM Tester | Caiapó |
|---|---|---|
| Linha de produção | `NAVAJO`, `TOMAHAWK`… | `CAIAPO` |
| Pasta dos CSVs do testador | `D:\Testpad software\CSV\<modelo>` (sugerida automaticamente) | `D:\battData` (sugerida) — **confirme na estação**, seção 3.2 |

### Página 3 — Banco de Dados

| Campo | Valor |
|---|---|
| Host | IP ou nome do servidor PostgreSQL (fornecido pela engenharia) |
| Porta | `5432` |
| Nome do banco | `mes_db` |
| Usuário | `mes_user` |
| Senha | senha do `mes_user` — vai para `C:\Utility\MES\.env`, nunca para o `config.yaml` |
| Tabela de resultados | `mes_results` (padrão). Só use `mes_test_results` se a engenharia mandar manter uma estação PCM no histórico antigo |

### Página 4 — Cópia dos CSVs para a rede

| Situação | O que preencher |
|---|---|
| Estação PCM com share definido | O instalador sugere `\\<host do banco>\NonAlphaSec2Info\logs\<modelo>`. Confirme ou corrija |
| Caiapó / linha sem share | **Deixe vazio.** A cópia fica desligada (`sync.enabled: false`) |

5. Na tela **Pronto para instalar**, confira o resumo. Repare na linha que
   diz se o instalador vai **gerar** ou **preservar** o `config.yaml` (ver
   seção 5, atualização).
6. **Instalar**. Ao final, deixe marcado *Iniciar MES Client agora*.

### O que o instalador faz na estação

| Ação | Detalhe |
|---|---|
| Copia os arquivos | `MES_Client.exe`, `spec_limits.csv`, `column_mappings.json`, `assets\app.ico` em `C:\Utility\MES` |
| Cria as pastas de runtime | `logs\`, `state\`, `data\` |
| Grava o `.env` | `MES_DB_PASSWORD=<senha>` — **sempre reescrito** |
| Gera o `config.yaml` | **apenas se ainda não existir** |
| Registra o auto-start | Tarefa `MES_Client_Autostart` (gatilho: logon; reinício automático 3× a cada 1 min; não para em bateria/ocioso) |
| Cria o atalho | Área de trabalho de todos os usuários |

### `config.yaml` gerado (exemplo Caiapó — Teste Funcional)

```yaml
database:
  enabled: true
  host: <host>
  port: 5432
  name: mes_db
  user: mes_user
  password: ${MES_DB_PASSWORD}
  table: mes_results
  jsonb_index: false

station:
  id: FUNC_A08_CAIAPO-M13
  type: AUTO
  model: A08
  line: CAIAPO

log:
  folder: D:/battData
  recursive: false

operation:
  mode: both

sync:
  enabled: false
  destination_folder: ""
  mode: diff

parser:
  scan_interval: 5

spec_check:
  enabled: false
  file: spec_limits.csv

auth:
  operador_password: ""
  engenharia_password: "admin"
```

Para estações PCM, `recursive` e `spec_check.enabled` saem `true` (o TestPad
grava em subpastas por modelo e o `spec_limits.csv` cobre esses modelos).

---

## 3. Caiapó (BW P2500S) — o que é diferente

### 3.1 Formato do CSV

O P2500S grava um arquivo por dia (`AAAAMMDD_A08.csv`), 46 colunas: 6 fixas
(`BARCODE.1`, `BARCODE.2`, `MODELNAME`, `PRD_CD`, `TESTTIME`, `TESTRESULT`),
13 triplas `Max, Min, MEDIÇÃO` e `Station` (o canal: `1A`…`4B`). Os dados
começam na linha 2, não há linhas de limite. A v1.0.5 reconhece isso
sozinha (formato `P2500S`); as colunas `Max`/`Min` viram `OCV_Max`,
`OCV_Min` etc. no banco.

Linhas curtas do tipo `Scan at operation…` (5 campos) são rejeitadas pelo
parser com o motivo `too_few_fields`. **Isso é normal** e aparece no log como
aviso — não é erro.

O valor `-1.000` em qualquer medição é o sentinela de "não medido" do
equipamento (falha de contato), não uma reprova de produto. O cliente grava
como veio; a interpretação é do dashboard.

### 3.2 De qual pasta ler — confira antes de instalar

Os arquivos que o P2500S copia para `DATA\TestData\Line2_MC2` no servidor
saem com **45 campos** e perdem a coluna `Station`. Sem ela, o dashboard por
canal não existe. Na estação, rode:

```powershell
(Get-Content "D:\battData\$(Get-Date -Format yyyyMMdd)_A08.csv" -TotalCount 2)[1].Split(',').Count
```

| Resultado | Pasta a informar na página 2 |
|---|---|
| `46` | `D:\battData` (a pasta local tem o canal — use ela) |
| `45` | `\\172.21.75.50\bw-p2500s\Parente\M13-logs Caiapo` (a única cópia que preserva o canal) |

Se apontar para uma pasta de rede, a conta da estação precisa ter leitura
nela e a rede precisa estar de pé para o cliente ler; a fila offline cobre o
banco, não a origem dos CSVs.

### 3.3 Tab Cutting

Mesmo instalador, prefixo `TABC`, pasta `\\172.21.75.50\bw-p2500s\DATA\TestData\Line1_MC1\<AAAAMM>` (ou local, se existir). 19 colunas, sem canal. O bloco
`A08` do `column_mappings.json` serve para as duas estações (os 6 primeiros
campos são iguais).

### 3.4 Pré-requisito no banco (uma vez, pelo DBA/engenharia)

A tabela `mes_results` e a view `v_mes_results` precisam existir antes da
primeira estação Caiapó subir. O DDL idempotente está em
`caiapo_deploy\001_mes_results.sql` (executar como `mes_user`). Se a tabela
não existir, o cliente fica com ícone vermelho e o log mostra
`relation "mes_results" does not exist`.

---

## 4. Instalação silenciosa (várias estações)

Todos os campos do wizard aceitam parâmetro de linha de comando. Com
`/SILENT` nenhuma tela aparece.

```powershell
# Caiapó — Teste Funcional (rodar como Administrador, logado na conta do operador)
.\MES_Client_Setup_v1.0.5.exe /SILENT /PREFIX=FUNC /MODEL=A08 /MACHINE=CAIAPO-M13 `
    /TESTER=AUTO /LINE=CAIAPO /CSV="D:\battData" /SYNC="" `
    /DBHOST=<host> /DBPASS=<senha do mes_user>

# PCM Tester (mantém o comportamento das versões anteriores)
.\MES_Client_Setup_v1.0.5.exe /SILENT /PREFIX=PCM /MODEL=A17 /MACHINE=BR-PCMTEST-03 `
    /LINE=NAVAJO /CSV="D:\Testpad software\CSV\A17" `
    /SYNC="\\<host>\NonAlphaSec2Info\logs\A17" /DBHOST=<host> /DBPASS=<senha>
```

| Parâmetro | Padrão | Obrigatório no silencioso? |
|---|---|---|
| `/PREFIX` | `PCM` | não (`PCM`, `FUNC` ou `TABC`) |
| `/MODEL` | `A17` | não |
| `/MACHINE` | `BR-PCMTEST-01` | não |
| `/TESTER` | `AUTO` | não |
| `/LINE` | `NAVAJO` | não |
| `/CSV` | sugestão por tipo | não |
| `/SYNC` | vazio (desligado) | não |
| `/DBHOST` | — | **sim** (a menos que já exista `config.yaml`) |
| `/DBPORT` `/DBNAME` `/DBUSER` | `5432` `mes_db` `mes_user` | não |
| `/DBPASS` | — | **sim** |
| `/TABLE` | `mes_results` | não |

Sem `/DBHOST` ou `/DBPASS` o instalador **aborta com mensagem** em vez de
gravar um config incompleto. Com `/SILENT` o cliente **não** é iniciado ao
final; inicie pelo atalho ou faça logoff/logon (a tarefa dispara).

**Nunca grave a linha com `/DBPASS` em `.bat`, `.ps1` ou histórico.** Se
precisar de um script para várias estações, leia a senha com `Read-Host
-AsSecureString` na hora ou de uma variável de ambiente da sessão.

---

## 5. Atualizar uma estação que já tem o MES Client

Rode o instalador novo por cima. **O `config.yaml` da estação é preservado**
(a tela "Pronto para instalar" avisa). O `.env` é reescrito com a senha
digitada — digite a mesma, ou a nova se ela mudou.

Consequência: os campos do wizard são **ignorados** numa atualização. Para
reconfigurar (mudou o modelo, a pasta, a tabela), escolha um:

- edite pela tela **CONFIGURAÇÃO** do próprio cliente (senha de ENGENHARIA), ou
- apague `C:\Utility\MES\config.yaml` **antes** de rodar o instalador.

### ⚠ Estações PCM vindas da v1.0.3 ou anterior

Duas mudanças pedem decisão antes de atualizar:

1. **Chave de deduplicação** (`source_file`) passou a ser o caminho relativo.
   Na primeira execução as linhas dos CSVs já processados podem ser
   **reinseridas**. Leia "Ponto de atenção na migração" em `DEPLOY.md` e
   decida entre corte por data, migração SQL ou zerar o offset.
2. **Tabela.** O `config.yaml` preservado continua apontando para
   `mes_test_results`. Isso é aceitável para manter o histórico PCM lá; se a
   engenharia decidir unificar em `mes_results`, mude na tela CONFIGURAÇÃO.

---

## 6. Verificação pós-instalação (5 minutos, obrigatória)

1. **Ícone na bandeja verde.** Vermelho = banco ou share inacessível; amarelo
   = monitor parado (STOP).
2. Abra `C:\Utility\MES\logs\client.log` (ou STATUS → ABRIR LOG) e confirme,
   nesta ordem:
   ```
   Auth: OPERADOR sem senha configurada - iniciando sem tela de login.
   Conexão com banco estabelecida
   MONITOR INICIADO
   Pasta monitorada: <a pasta que você informou>
   Station Type: AUTO
   ```
3. Tela **STATUS**: `Versão do Client = 1.0.5`, `Station ID` correto,
   `last_insert_time` avançando a cada scan (5 s) quando há teste rodando.
4. Avisos como `N linha(s) rejeitada(s) em <arquivo>: #12(too_few_fields)`
   são o filtro funcionando. Só investigue se **quase tudo** estiver sendo
   rejeitado (aí a pasta ou o tipo do testador estão errados).
5. No banco (DBeaver, como `mes_user` ou usuário de leitura):
   ```sql
   SELECT count(*), max(created_at), count(channel) AS com_canal
   FROM mes_results
   WHERE station_id = 'FUNC_A08_CAIAPO-M13';
   ```
   `count` crescendo e, na M13 lendo da pasta certa, `com_canal = count`.
   Para PCM em `mes_test_results`, troque a tabela e o `station_id`.
6. **Teste de reinício**: reinicie a estação. Com logon automático, o cliente
   tem que voltar sozinho em até 1 minuto após o desktop aparecer. Se não
   voltar, veja a seção 8, item "não sobe após reiniciar".
7. Anote na planilha de estações: `station_id`, data, versão, pasta lida.

---

## 7. Desinstalar

Painel de Controle → Programas → **MES Client** → Desinstalar, ou
`C:\Utility\MES\unins000.exe`. O desinstalador encerra o processo, remove a
tarefa `MES_Client_Autostart`, apaga `config.yaml` e `.env` (a senha não fica
para trás) e **preserva** `logs\`, `state\` e `data\` para auditoria. Apague
essas pastas à mão se não precisar mais delas.

---

## 8. Diagnóstico rápido

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| Ícone vermelho e log com `Falha ao conectar no banco ... 5432` | Rede/firewall/`pg_hba.conf`, host errado, senha errada | `Test-NetConnection <host> -Port 5432`; confira o `.env`; peça ao DBA liberar a sub-rede da linha |
| Log com `relation "mes_results" does not exist` | DDL não executado no banco | Seção 3.4 |
| Ícone verde mas `count(*)` não cresce | Pasta errada, `recursive` errado ou testador não gerando CSV hoje | Confira `Pasta monitorada` no log e se o CSV do dia existe lá |
| `serial_number`/`result_status` NULL no banco (Caiapó) | `column_mappings.json` sem o bloco `A08` (instalação antiga) | Reinstale a v1.0.5 ou cole o bloco pela tela MAPEAMENTO |
| Sem coluna `channel` no banco (Caiapó) | Lendo de `Line2_MC2` (45 campos) | Seção 3.2 — trocar a pasta |
| Quase todas as linhas rejeitadas com `header_repeat`/`too_few_fields` | Tipo do testador forçado errado | Volte para `AUTO` na tela CONFIGURAÇÃO |
| Não sobe após reiniciar | Tarefa criada em outra conta, ou sem logon automático | `schtasks /Query /TN MES_Client_Autostart /V /FO LIST \| findstr "Run As User"`; reinstale logado na conta certa |
| Processo vivo, ícone normal, mas `client.log` parado há horas | Travamento silencioso (visto em 03/09/2026) | Encerre pelo Gerenciador de Tarefas; a tarefa reinicia em 1 min. O sinal de saúde confiável é a data do `client.log`, não o ícone |
| Cliente não abre e não há log | `.env` ausente/com BOM, `config.yaml` malformado, pasta de CSV inexistente | A v1.0.5 mostra um diálogo com o erro; corrija o arquivo apontado |
| `offline_queue.jsonl` crescendo sem parar | Versão anterior à 1.0.4 | Atualize; na 1.0.4+ a fila não infla com o banco fora |

Arquivos que importam para suporte: `C:\Utility\MES\logs\client.log`,
`config.yaml`, `state\offsets.json`, `offline_queue.jsonl` (se existir).
**Nunca envie o `.env`.**

---

## 9. Checklist de uma instalação Caiapó (imprimir)

- [ ] `001_mes_results.sql` executado no banco (uma vez)
- [ ] Logado na conta do operador; logon automático configurado
- [ ] `Test-NetConnection <host> -Port 5432` = True **na estação**
- [ ] Contagem de campos da 2ª linha do CSV do dia = 46 (senão, pasta de rede)
- [ ] Instalador rodado como Administrador: `FUNC` / `A08` / `CAIAPO-M13` / `AUTO` / `CAIAPO` / pasta / host / senha / `mes_results` / sync vazio
- [ ] Ícone verde; log com `MONITOR INICIADO`; STATUS mostra 1.0.5
- [ ] `SELECT count(*) ... FUNC_A08_CAIAPO-M13` crescendo; `count(channel) = count(*)`
- [ ] Reinício da estação: cliente voltou sozinho
- [ ] Registrado na planilha de estações
