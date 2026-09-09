# Changelog — MES Client

Todas as mudanças notáveis deste projeto são documentadas aqui.
Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.0.0/).

---

## [1.0.4] — 2026-09-09

Correções de confiabilidade de dados e de reprodutibilidade, a partir de uma
auditoria completa do código. Nenhuma mudança de funcionalidade — o
comportamento visível ao operador é o mesmo, exceto onde ele antes perdia dado.

### Corrigido — o repositório não rodava ao ser clonado

- **`.gitignore` removia o pacote `logs/` do repositório.** A entrada `logs/`
  tinha a intenção de ignorar os *arquivos* de log, mas `logs` também é o pacote
  Python que contém o `logger_setup.py`. Como praticamente todo módulo faz
  `from logs.logger_setup import get_logger`, qualquer clone quebrava logo no
  start com `ModuleNotFoundError: No module named 'logs.logger_setup'`.
  A regra passou a ser `logs/*.log` e `logs/*.log.*`, e o pacote foi versionado.
- **O build do `.exe` também não funcionava num clone limpo.** O
  `parser_TE.spec` exigia `config.yaml` em `datas`, e esse arquivo está — com
  razão — no `.gitignore`, por conter IP e senha reais da estação. Agora empacota
  `config.example.yaml`. Junto, foi incluído o `column_mappings.json`, que estava
  faltando no `datas` e fazia o `.exe` cair sempre nos mapeamentos embutidos em
  vez de ler o arquivo do usuário.
- **`assets/make_icon.py`** — o `app.ico` é artefato gerado e não é versionado;
  faltava a forma de recriá-lo. O script desenha o ICO multi-resolução
  (16/32/48/64/256) usado pelo `.exe` e pelo instalador.

### Corrigido — perda e duplicação silenciosa de dados

- **A fila offline era apagada antes de o insert ser confirmado.** O `pop_all()`
  lia os registros e removia o arquivo no mesmo passo; se o `insert_rows`
  seguinte falhasse — conexão caindo entre o `ping` e o insert, timeout, disco
  cheio no servidor — a exceção era apenas logada e os dados sumiam para sempre.
  Substituído pelo par `peek_all()` + `commit()`: a fila só é apagada depois que
  o banco confirmou. Reprocessar é seguro, o insert usa
  `ON CONFLICT DO NOTHING`. O `peek_all()` também pula linhas com JSON
  corrompido (escrita interrompida) em vez de derrubar o reenvio inteiro.
- **A fila offline crescia sem limite com o banco fora.** Quando o `ping`
  falhava, o ciclo seguia adiante mesmo assim, parseava os CSVs, tomava
  `ConnectionError` no insert e empilhava o mesmo lote na fila — a cada
  `scan_interval`. Como o offset só avança após o commit, as mesmas linhas
  voltavam para a fila indefinidamente: uma queda de 4 h gerava centenas de MB
  de duplicatas, e o reenvio depois carregava tudo isso na memória de uma vez.
  Agora, com o banco offline, o monitor não parseia nem empilha — o offset
  preserva a posição e ele apenas espera. O sync continua rodando normalmente.
- **A deduplicação usava só o nome do arquivo.** O índice único é
  `(station_id, source_file, source_line_no)`, mas `source_file` guardava o
  *basename*. Com `log.recursive: true`, dois CSVs de mesmo nome em subpastas
  diferentes (`A17/2026-09-09.csv` e `A16/2026-09-09.csv`) colidiam, e o
  `ON CONFLICT DO NOTHING` descartava o segundo sem erro, sem log e sem alerta.
  `source_file` passou a guardar o caminho relativo a `log.folder`, com `/`.

### Corrigido — outros

- **`_normalize_result` marcava `PENDING` como `FAIL`.** A checagem era por
  substring, e `"NG" in v` casava com `PENDING`, `TESTING`, `RUNNING` e `WRONG`,
  contaminando o yield. Passou a comparar por valor exato, com os conjuntos
  `RESULTADO_PASS` e `RESULTADO_FAIL`. Valor desconhecido é preservado como veio,
  para aparecer no banco e ser investigado — nunca convertido em `FAIL`.
- **`offsets.json` podia ser corrompido por queda de energia.** A escrita não era
  atômica; um `json.dump` interrompido deixava o arquivo pela metade e o
  `JSONDecodeError` no start seguinte impedia o monitor de subir. Agora grava em
  arquivo temporário com `fsync` e publica com `os.replace` (atômico no Windows e
  no Linux). Se ainda assim encontrar um arquivo inválido, recomeça do zero em
  vez de derrubar o monitor — as linhas já inseridas são descartadas pelo
  `ON CONFLICT`.

### Alterado

- **`requirements.txt`** — `watchdog` removido: estava declarado mas não era
  importado em lugar nenhum (o monitoramento é por polling, e continua sendo).
- **`requirements-dev.txt`** — novo. `python-docx` (usado só pelo
  `gerar_documentacao.py`) e `pytest` saíram das dependências de execução; o
  operador na estação não precisa deles.

### Corrigido — a estação não voltava coletando depois de reiniciar

- **A tela de login travava o monitor no arranque.** O `run()` agendava
  `_show_login_then_start`, que bloqueava em `wait_window()` até alguém
  escolher o perfil e clicar ENTRAR — só então `ensure_monitor_running()` era
  chamado. Numa estação que roda 24h e reinicia sozinha, isso significava
  voltar do boot com o ícone na bandeja e **nenhum dado sendo coletado**, sem
  sinal visível de que estava parado. Agora, quando `auth.operador_password`
  está vazio (ou ausente), o cliente entra direto como OPERADOR e inicia o
  monitor. Não há perda de controle: CONFIG, LIMITES, MAPEAMENTO, STOP e EXIT
  continuam passando por `_check_role`, que pede a senha de ENGENHARIA. Definir
  `operador_password` no `config.yaml` faz a tela de login voltar a aparecer.
- **A tarefa de auto-start herdava padrões que impediam a coleta.** O XML não
  declarava as opções de energia, e o Task Scheduler aplicava
  `DisallowStartIfOnBatteries=true` e `StopIfGoingOnBatteries=true`. Numa
  estação ligada a nobreak que se reporta como bateria, o cliente não subiria.
  Agora ambos vão explícitos como `false`, junto de `StopOnIdleEnd=false` e
  `StartWhenAvailable=true`.

### Instalador

- **Atualizar uma estação apagava a configuração dela.** O `GenerateConfig` do
  wizard reescrevia o `config.yaml` incondicionalmente no `ssPostInstall`, e a
  documentação afirmava o contrário. Reinstalar por cima só para atualizar a
  versão zerava os ajustes daquela estação. Agora o `config.yaml` só é gerado
  quando ainda não existe, e a tela "Pronto para instalar" avisa qual dos dois
  casos está acontecendo.
- **A senha do banco era gravada em texto plano no `config.yaml`.** Isso
  contrariava o próprio `config.example.yaml`, que documenta
  `password: ${MES_DB_PASSWORD}` com a observação "NUNCA hardcoded" — mas o
  instalador nunca criava o `.env`. Agora ele grava a senha em
  `C:\Utility\MES\.env` e escreve apenas o placeholder no `config.yaml`. O
  fluxo do técnico não muda: a senha continua sendo digitada uma vez no wizard.
  O `.env` também passou a ser removido na desinstalação.
- **`assets/make_installer_images.py`** — novo. O `installer_banner.bmp` e o
  `installer_header.bmp` são artefatos gerados e não versionados; faltava a
  forma de recriá-los, e sem eles o `.iss` não compila num clone limpo.

### Testes

- **`tests/test_correcoes_fase_a.py`** — novo. Guardas de regressão das
  correções acima, sem precisar de banco: a fila offline sobrevive a um insert
  que falha, dois arquivos de mesmo nome geram chaves distintas, `PENDING` não
  vira `FAIL`, e o `offsets.json` corrompido não derruba o monitor.

---

## [1.0.2] — 2026-06-24 (patch 2)

### Adicionado
- **Tela MAPEAMENTO**: novo editor de `column_mappings.json` acessível pelo tray popup (⇄). Permite definir quais colunas do CSV correspondem a cada campo estruturado do banco (serial, resultado, modelo, tempo) por modelo específico ou como DEFAULT global — sem abrir código fonte
- **`config/column_mapper.py`**: módulo central de resolução de campos. Carrega o JSON, resolve campos por prioridade (modelo específico → DEFAULT → NULL), detecta campos não mapeados para base da Opção C futura
- **`column_mappings.json`**: arquivo de mapeamento padrão com entradas DEFAULT para os formatos CYG e PCM Tester existentes
- **Fundação da Opção C (futura)**: `detect_unmapped_fields()` detecta quando um schema novo não tem mapeamento configurado e registra em `runtime_status["unmapped_fields_alert"]` para futura notificação visual no ícone

### Alterado
- **`monitor/file_monitor.py`**: funções `_resolve_serial_or_trace`, `_resolve_result`, `_resolve_test_start`, `_resolve_test_stop` removidas; substituídas por `column_mapper.resolve_field()` — nomes de colunas agora lidos de `column_mappings.json` em vez de hardcoded no código
- **`_resolve_model_name`** agora aceita `mappings` e usa `resolve_field("model_name", ...)` para o lookup por linha — sem lista hardcoded
- **Mapeamentos recarregados a cada ciclo do monitor**: nova configuração salva via UI entra em vigor sem reiniciar o monitor
- **PCM Tester serial**: mantido como composição fixa (`_pcm_serial`) por ser protocolo do equipamento; todos os outros campos (resultado, tempo) agora usam o mapper configurável

### Corrigido
- **Tela ACESSO RESTRITO não recebia teclado no .exe compilado** (STOP e EXIT): raiz do problema era o `popup.destroy()` acontecer *antes* de criar o auth dialog — o Windows transferia o foreground para outra aplicação antes de `_check_role` ser chamado; corrigido invertendo a ordem no `on_click`: `cb()` é chamado primeiro (agenda o auth dialog via `after(0)`), popup fecha via `after(10)` — auth dialog é criado enquanto popup ainda é o foreground do nosso processo
- **`_bring_to_front` refatorado**: removido `AttachThreadInput` (podia bloquear o event loop do Tkinter ao sincronizar com a thread da janela em foco, ex. VS Code); substituído por `SPI_SETFOREGROUNDLOCKTIMEOUT=0` temporário — abordagem documentada e sem risco de deadlock
- **Retry de foco**: `_check_role` reaplica `_bring_to_front` + `focus_set` 120 ms após o primeiro `grab_set`, cobrindo edge cases de timing

### Documentação
- `docs/CSV_FORMATS.md` atualizado: seção "Como adicionar suporte" reescrita para refletir fluxo sem código; nova seção sobre `column_mappings.json`
- `README.md` atualizado: tabela de funcionalidades e arquitetura incluem MAPEAMENTO e `column_mappings.json`
- Tela AJUDA atualizada com seção MAPEAMENTO e `column_mappings.json` na lista de arquivos de configuração

---

## [1.0.1] — 2026-06-23

### Adicionado
- **Popup dark premium no system tray**: clique direito no ícone abre menu dark customizado com cabeçalho "MES CLIENT", status ao vivo (● RUNNING / STOPPED), ícones simbólicos e efeito hover — substitui completamente o menu nativo cinza do Windows
- **Todos os alertas e confirmações convertidos para dark UI** (`_dark_msg`): substituiu todos os `messagebox` por dialogs customizados com header colorido por tipo (ℹ info / ⚠ warning / ✖ error / ? yesno), botões SIM/NÃO ou OK, tamanho auto-ajustável ao conteúdo
- **Dialog dark de confirmação de saída**: botão "SIM, ENCERRAR" vermelho escuro, "CANCELAR" cinza, sem dependência de janela pai (sem bug de messagebox sumindo com root withdrawn)
- **`_bring_to_front(win)`**: usa `AttachThreadInput` + `SetForegroundWindow` do Win32 para forçar foco mesmo quando o app está em background — resolve problema exclusivo do Windows 11 que bloqueia `focus_force()` de processos sem foco ativo

### Corrigido
- **EXIT não encerrava o aplicativo**: `messagebox` com `root` withdrawn some imediatamente no .exe compilado (PyInstaller + `console=False`) — substituído por `Toplevel` customizado com `-topmost` e `grab_set`
- **"Acesso restrito" abria sem os campos de senha** na primeira tentativa (STOP/EXIT via tray sem nenhuma janela ativa prévia): Windows 11 bloqueava `focus_force()` do processo em background — corrigido com `AttachThreadInput` + `SetForegroundWindow` + `update_idletasks()` + `lift()`
- **`iconphoto()` sem try/except em `_check_role`**: se falhasse silenciosamente no .exe, nenhum widget abaixo era criado — adicionado `try/except`
- **Janela ABOUT não abria centralizada**: `_style_window` posicionava no topo (y=4%); adicionado `update_idletasks()` + override de geometria para centro exato da tela
- **ABOUT abria atrás de outras janelas**: adicionado `attributes("-topmost", True)`

### Alterado
- **Clique direito** no ícone da bandeja agora abre o popup dark (antes: menu nativo cinza)
- **Clique esquerdo** no ícone da bandeja não faz nada (antes: abria popup dark)
- Menu nativo do pystray removido; comportamento dos cliques reescrito via patch do `_message_handlers[WM_NOTIFY]`
- `_check_role` agora usa `-topmost True` sempre (antes: só sem parent), posicionamento centralizado e `update_idletasks()` antes do `grab_set()`

---

## [1.0.0] — 2026-06-23

### Adicionado
- **Instalador profissional Inno Setup 6**: wizard com 4 páginas de configuração (estação, arquivos, banco, confirmação), tema dark com banner e header customizados, geração automática de `config.yaml`, registro no Task Scheduler, atalho na Área de Trabalho e desinstalador integrado
- **Instalador PowerShell alternativo** (`Instalar_MES_Client.ps1`): para deploy sem GUI do Inno Setup
- **Script de teste local** (`Testar_Instalador_Local.ps1`): permite testar sem acesso ao servidor da fábrica
- **Botão "?" (ajuda) na tela LIMITES**: todas as telas agora têm acesso à ajuda integrada
- **Sistema de foco modal completo**: `_bind_focus_lock` + `transient` + `grab_set` chain — usuário não pode clicar fora de janelas modais
- **Janela AJUDA**: todas as seções renderizando corretamente com suporte a abertura dentro de modais ativos
- **Comentários extensivos** em todos os módulos Python para facilitar manutenção
- **Ícone ICO multi-size** gerado programaticamente (16, 32, 48, 256px) com formato ICO binário correto
- **Imagens dark premium** para o wizard Inno Setup geradas com Pillow (gradiente, tipografia)

### Corrigido
- **AJUDA renderizava só a primeira seção**: conflito de keyword argument `pady` no dicionário `PAD` causava `TypeError` silencioso no Tkinter — removido `pady=0` do dict
- **Botão "?" retornava "feche a janela atual"**: `_open_ajuda` usava `_try_open_window` que bloqueava quando CONFIG/STATUS tinha grab ativo — reescrito com chain de grab manual
- **Tela de autenticação piscando ao abrir**: `_bind_focus_lock` da janela parent brigava com o diálogo de auth pelo foco — adicionado `self.auth_dialog` como exceção no focus lock
- **EXIT congelava o aplicativo**: após fechar diálogo de auth, código fazia `self.root.grab_set()` numa janela `withdraw()` (oculta), interceptando todos os eventos — corrigido para só restaurar grab em janelas modais reais
- **Codificação UTF-8 nos scripts PowerShell**: caracteres especiais (—, ╔, ║) causavam erros de parsing no PowerShell 5.1 — substituídos por ASCII puro
- **`Read-Host ""`** não aceita string vazia no PowerShell 5.1 — substituído por `Read-Host " "`
- **Operador `?.` não disponível no PowerShell 5.1** — substituído por bloco `if/else` explícito
- **Arquivo `app.ico` com 0 bytes**: geração com Pillow produzia ICO inválido — reescrito com `struct.pack` para ICO binário correto

### Alterado
- Tela de autenticação (`_check_role`) reformulada: painel de cabeçalho `#1a2744`, suporte a Escape, `transient()` configurado, grab chain corrigido
- Seção de inicialização automática migrada de "pasta Startup do Windows" para **Task Scheduler** (mais robusto, suporta restart automático)
- `WizardResizable=no` substituído por `WizardSizePercent=100` (Inno Setup 6.7 deprecou o antigo)

---

## [0.9.0] — 2026-06-15

### Adicionado
- Sistema de login com perfis OPERADOR e ENGENHARIA
- Elevação pontual: OPERADOR pode executar ações restritas informando senha de ENGENHARIA sem trocar de sessão
- Tela LIMITES: editor tabular de `spec_limits.csv` com add/delete/edit por linha
- Tela AJUDA com documentação inline de todas as funcionalidades
- Tray icon dinâmico: verde (sucesso), vermelho (erro), amarelo (aguardando)
- Fila offline JSONL com reprocessamento automático

### Adicionado (Core)
- Parser incremental com controle de offset por arquivo (sem releitura de dados já processados)
- Detecção automática de formato CSV: PCM Tester vs CYG
- Deduplicação no banco por `(source_file, source_line_no)` via `ON CONFLICT DO NOTHING`
- Sincronização de arquivos em modo diff (só copia o que mudou)
- Validação de limites LSL/USL contra `spec_limits.csv`
- Criação automática de banco e tabelas na primeira execução
- Single instance lock (impede múltiplas instâncias simultâneas)
- Logging rotativo (`RotatingFileHandler`, 1 MB por arquivo, 5 backups)

---

## [0.1.0] — 2026-05-01

### Adicionado
- Estrutura inicial do projeto
- Parser básico de CSV PCM Tester
- Conexão com PostgreSQL
- Interface mínima de system tray
