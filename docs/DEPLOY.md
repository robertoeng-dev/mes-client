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
   bandeja (STOP → EXIT, senha de ENGENHARIA) antes de instalar por cima.
3. Execute o instalador **como Administrador** (botão direito → Executar como
   administrador). Ele precisa disso para gravar em `C:\Utility\MES` e para
   registrar a tarefa no Task Scheduler.
4. Preencha o wizard:

   | Página | Campo | Exemplo |
   |---|---|---|
   | Estação | Modelo do produto | `A17` |
   | Estação | ID da máquina | `BR-PCMTEST-01` |
   | Arquivos | Linha de produção | `NAVAJO` |
   | Arquivos | Pasta dos CSVs do TestPad | `D:\Testpad software\CSV\A17` |
   | Banco | Host, porta, banco, usuário | padrão da fábrica |
   | Banco | Senha | senha do `mes_user` |

   O `Station ID` é montado automaticamente como `PCM_{MODELO}_{MÁQUINA}` —
   confira na tela de resumo antes de confirmar.
5. Ao final, o MES Client inicia automaticamente (ícone na bandeja).

### O que o instalador faz na estação

| Ação | Detalhe |
|---|---|
| Copia os arquivos | `MES_Client.exe`, `spec_limits.csv`, `column_mappings.json`, `assets\app.ico` em `C:\Utility\MES` |
| Cria as pastas de runtime | `logs\`, `state\`, `data\` |
| Grava o `.env` | `MES_DB_PASSWORD=<senha digitada>` — **sempre reescrito** |
| Gera o `config.yaml` | **apenas se ainda não existir** — veja abaixo |
| Registra o auto-start | Tarefa `MES_Client_Autostart` no Task Scheduler, com reinício automático (3 tentativas, 1 min) |
| Cria o atalho | Área de trabalho de todos os usuários |

### ⚠ Instalação nova x atualização

**A partir da v1.0.4 o instalador preserva o `config.yaml` de uma estação já
configurada.** Reinstalar por cima para atualizar a versão não apaga mais os
ajustes feitos naquela estação. A tela "Pronto para instalar" avisa qual dos
dois casos está acontecendo — leia antes de confirmar.

Consequência prática: se você **quer** reconfigurar uma estação (mudou o
modelo, mudou a pasta de CSVs), o wizard sozinho não basta. Apague o
`C:\Utility\MES\config.yaml` antes de instalar, ou edite pela tela
CONFIGURAÇÃO do próprio cliente.

O `.env` é exceção: ele é sempre reescrito com a senha digitada no wizard,
porque a senha do banco pode ter mudado.

### ⚠ Onde fica a senha do banco

**A senha nunca é gravada no `config.yaml`.** Ele guarda só o placeholder, e o
valor real fica em `C:\Utility\MES\.env`:

```
MES_DB_PASSWORD=senha_real_aqui
```

Se o `.env` for apagado, o cliente não sobe — o `config/loader.py` levanta
erro dizendo qual variável está faltando. Para trocar a senha sem reinstalar,
edite o `.env` e reinicie o cliente.

Isso vale a partir da v1.0.4. Estações instaladas com versões anteriores têm a
senha em texto plano dentro do `config.yaml`; ao atualizar, o `config.yaml`
antigo é preservado e continua funcionando, mas a senha continua exposta lá.

**Para migrar uma estação já instalada**, sem reinstalar, rode como
Administrador na própria estação:

```powershell
# confira primeiro, sem alterar nada
powershell -ExecutionPolicy Bypass -File Migrar_Senha_Para_Env.ps1 -Simular

# aplica
powershell -ExecutionPolicy Bypass -File Migrar_Senha_Para_Env.ps1
```

O script lê a senha literal do `config.yaml`, grava no `.env`, troca a linha
pelo placeholder e guarda um backup `config.yaml.bak-<data>`. É idempotente —
rodar de novo numa estação já migrada não faz nada. Se a instalação não estiver
em `C:\Utility\MES`, passe `-Caminho "D:\outro\lugar"`.

Depois, valide reiniciando o cliente e conferindo no `logs\client.log` a linha
`Conexão com banco estabelecida`.

> **Cuidado com o BOM.** Se for criar ou editar o `.env` à mão, salve como
> UTF-8 **sem BOM**. O Bloco de Notas e o `Set-Content -Encoding utf8` do
> PowerShell 5.1 gravam BOM, que até a v1.0.4 grudava no nome da primeira
> chave e fazia o cliente não encontrar a senha. A v1.0.4 lê com `utf-8-sig` e
> tolera isso, mas estações com versão anterior não.

### Se o cliente não abre

A partir da v1.0.4, uma falha antes da primeira janela é registrada em
`logs\client.log` e mostrada num diálogo com o tipo do erro. Antes, o processo
morria calado — sem janela, sem log — e o sintoma na estação era simplesmente
"não abre". Se acontecer numa estação em versão antiga, os suspeitos usuais
são `config.yaml` malformado, `.env` ausente ou com BOM, e pasta de CSVs
inexistente.

## Auto-start: a estação voltando a coletar depois de reiniciar

O instalador registra a tarefa **`MES_Client_Autostart`** no Task Scheduler.
Três detalhes decidem se ela realmente cumpre o papel.

### 1. O gatilho é logon, não boot

`<LogonTrigger />` dispara quando **um usuário faz logon**, não quando a
máquina liga. Isso é o correto para este app: ele é uma interface gráfica com
ícone na bandeja e precisa de uma sessão de desktop — como serviço do Windows
ele não teria onde desenhar o ícone.

Consequência: se a estação reinicia e para na tela de login do Windows, o
cliente **não sobe**. Para operação desacompanhada, configure o **logon
automático** do Windows na conta da estação.

### 2. A tarefa fica amarrada à conta que instalou

O `schtasks` grava o SID do usuário que rodou o instalador em
`<Principal><UserId>`, com `LogonType InteractiveToken`. A tarefa só dispara
quando **aquela conta** faz logon.

> **Regra prática: instale logado na conta que a estação realmente usa.**
> Se você instalar com a sua conta de técnico e o operador entrar com outra,
> o cliente nunca sobe sozinho.

Para conferir em qual conta a tarefa ficou:

```powershell
schtasks /Query /TN "MES_Client_Autostart" /V /FO LIST | findstr /C:"Run As User"
```

Para corrigir sem reinstalar, apague e recrie a tarefa logado na conta certa:

```powershell
schtasks /Delete /TN "MES_Client_Autostart" /F
```

e reinstale, ou recrie a tarefa manualmente apontando para
`C:\Utility\MES\MES_Client.exe`.

### 3. Sem senha de operador, o cliente entra sozinho

Até a v1.0.3, o cliente subia e **ficava parado na tela de login** — o monitor
só começava quando alguém clicava ENTRAR. Uma estação reiniciada de madrugada
passava a noite inteira sem coletar, com o ícone aparentemente normal.

A partir da v1.0.4, se `auth.operador_password` estiver vazio ou ausente no
`config.yaml`, o cliente entra direto como OPERADOR e o monitor começa. O log
registra a decisão:

```
Auth: OPERADOR sem senha configurada - iniciando sem tela de login.
```

As ações restritas continuam protegidas: CONFIG, LIMITES, MAPEAMENTO, STOP e
EXIT pedem a senha de ENGENHARIA. **Se você definir `operador_password`, a
tela de login volta a aparecer** — e aí a estação passa a exigir intervenção
humana após cada reinicialização. Para operação 24h, deixe vazio.

### O que a tarefa não cobre

`RestartOnFailure` (3 tentativas, 1 min) só reage se o processo **terminar**.
Um travamento com o processo vivo — o sintoma registrado em 03/09/2026:
processo em pé, 0 s de CPU, sem escrever `client.log` nem `offsets.json` — não
é detectado. Até existir um watchdog, o sinal de saúde confiável é o
`last_insert_time` na tela STATUS ou a data de modificação do `client.log`.

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
se ainda disponível) pode ser reinstalado por cima.

Atenção: o instalador **v1.0.3 sobrescreve o `config.yaml`** da estação com os
valores do wizard — esse comportamento só foi corrigido na v1.0.4. Antes de
fazer rollback, salve uma cópia do `C:\Utility\MES\config.yaml`.

Atenção: ao voltar para a v1.0.3, a chave `source_file` volta a ser o nome curto
do arquivo. Se linhas já foram gravadas com o caminho relativo, elas serão
reinseridas com a chave antiga.

## Homologação de múltiplas estações

Repita "Instalação" e "Verificação pós-instalação" em cada estação
individualmente. Não há dependência entre estações — uma instalação com
problema não afeta as demais.
