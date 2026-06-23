# ==============================================================================
# Testar_Instalador_Local.ps1
# Versao de TESTE para rodar em notebook pessoal (sem rede da fabrica)
# Instala em C:\Utility\MES usando PostgreSQL local
# ==============================================================================

#Requires -RunAsAdministrator
$ErrorActionPreference = "Stop"
$Host.UI.RawUI.WindowTitle = "MES Client - Teste Local"

$INSTALL_PATH  = "C:\Utility\MES"
$EXE_NAME      = "MES_Client.exe"
$TASK_NAME     = "MES_Client_Autostart_TEST"
$LOG_FILE      = "$INSTALL_PATH\logs\client.log"
$INSTALLER_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path

function Header {
    Clear-Host
    Write-Host ""
    Write-Host "  ============================================================" -ForegroundColor Magenta
    Write-Host "    MES CLIENT - TESTE LOCAL (notebook/dev)                   " -ForegroundColor Magenta
    Write-Host "    Simula instalacao sem servidor da fabrica                  " -ForegroundColor Magenta
    Write-Host "  ============================================================" -ForegroundColor Magenta
    Write-Host ""
}

function OK   { param([string]$msg) Write-Host "      OK  $msg" -ForegroundColor Green }
function FAIL { param([string]$msg) Write-Host "      ERR $msg" -ForegroundColor Red }
function INFO { param([string]$msg) Write-Host "      ->  $msg" -ForegroundColor Gray }
function WARN { param([string]$msg) Write-Host "      AVS $msg" -ForegroundColor DarkYellow }
function Step { param([int]$n, [string]$msg) Write-Host "  [$n] $msg" -ForegroundColor Yellow }

# ==============================================================================
# COLETA DE DADOS - versao local
# ==============================================================================
Header
Write-Host "  CONFIGURACAO DE TESTE LOCAL" -ForegroundColor White
Write-Host "  ------------------------------------------------------------" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Modelo do produto (ex: A06, A17, A16):" -ForegroundColor Cyan
$model = (Read-Host "  Modelo").Trim().ToUpper()
if (-not $model) { $model = "A17" }

Write-Host ""
Write-Host "  ID da maquina (ex: BR-PCMTEST-01):" -ForegroundColor Cyan
$machine = (Read-Host "  Maquina").Trim().ToUpper()
if (-not $machine) { $machine = "BR-PCMTEST-TEST" }

Write-Host ""
Write-Host "  Host PostgreSQL local [ENTER = localhost]:" -ForegroundColor Cyan
$dbHost = (Read-Host "  DB Host").Trim()
if (-not $dbHost) { $dbHost = "localhost" }

Write-Host ""
Write-Host "  Porta PostgreSQL [ENTER = 5432]:" -ForegroundColor Cyan
$dbPortStr = (Read-Host "  Porta").Trim()
$dbPort = if ($dbPortStr) { $dbPortStr } else { "5432" }

Write-Host ""
Write-Host "  Nome do banco [ENTER = mes_db]:" -ForegroundColor Cyan
$dbName = (Read-Host "  Banco").Trim()
if (-not $dbName) { $dbName = "mes_db" }

Write-Host ""
Write-Host "  Usuario do banco [ENTER = mes_user]:" -ForegroundColor Cyan
$dbUser = (Read-Host "  Usuario").Trim()
if (-not $dbUser) { $dbUser = "mes_user" }

Write-Host ""
Write-Host "  Senha do banco [ENTER = mes123]:" -ForegroundColor Cyan
$dbPass = (Read-Host "  Senha").Trim()
if (-not $dbPass) { $dbPass = "mes123" }

Write-Host ""
Write-Host "  Pasta de CSV para monitorar [ENTER = C:\teste_csv]:" -ForegroundColor Cyan
$csvFolder = (Read-Host "  Pasta CSV").Trim()
if (-not $csvFolder) { $csvFolder = "C:\teste_csv" }

$stationId = "PCM_${model}_${machine}"

Write-Host ""
Write-Host "  ------------------------------------------------------------" -ForegroundColor DarkGray
Write-Host "  RESUMO:" -ForegroundColor White
Write-Host ""
INFO "Station ID : $stationId"
INFO "Banco      : ${dbHost}:${dbPort}/${dbName} (usuario: $dbUser)"
INFO "Pasta CSV  : $csvFolder"
INFO "Instalar   : $INSTALL_PATH"
Write-Host ""
Write-Host "  Confirma? (S/N):" -ForegroundColor Cyan
$confirm = (Read-Host "").Trim().ToUpper()
if ($confirm -ne "S") { WARN "Cancelado."; exit 0 }

Header
Write-Host "  EXECUTANDO TESTE LOCAL - $stationId" -ForegroundColor White
Write-Host "  ------------------------------------------------------------" -ForegroundColor DarkGray
Write-Host ""

# ==============================================================================
# [1] Instalar arquivos
# ==============================================================================
Step 1 "Instalando arquivos em $INSTALL_PATH..."
@("$INSTALL_PATH", "$INSTALL_PATH\logs", "$INSTALL_PATH\state", "$INSTALL_PATH\data") |
    ForEach-Object { New-Item -ItemType Directory -Path $_ -Force | Out-Null }

$srcExe = Join-Path $INSTALLER_DIR $EXE_NAME
if (-not (Test-Path $srcExe)) {
    FAIL "$EXE_NAME nao encontrado em: $INSTALLER_DIR"
    FAIL "Coloque este script na mesma pasta do MES_Client.exe"
    Read-Host | Out-Null; exit 1
}
Copy-Item $srcExe "$INSTALL_PATH\$EXE_NAME" -Force
OK "MES_Client.exe copiado"

$srcSpec = Join-Path $INSTALLER_DIR "spec_limits.csv"
if (Test-Path $srcSpec) {
    Copy-Item $srcSpec "$INSTALL_PATH\spec_limits.csv" -Force
    OK "spec_limits.csv copiado"
} else {
    WARN "spec_limits.csv nao encontrado - opcional para teste"
}

# ==============================================================================
# [2] Gerar config.yaml
# ==============================================================================
Step 2 "Gerando config.yaml para teste..."
$csvFolderYaml = $csvFolder -replace '\\', '/'

$yaml = @"
database:
  enabled: true
  host: $dbHost
  port: $dbPort
  name: $dbName
  user: $dbUser
  password: $dbPass
  table: mes_test_results

station:
  id: $stationId
  type: PCM_TESTER
  model: $model
  line: TESTE_LOCAL

log:
  folder: $csvFolderYaml
  recursive: true

operation:
  mode: both

sync:
  enabled: false

parser:
  scan_interval: 5

spec_check:
  enabled: true
  file: spec_limits.csv

auth:
  operador_password: ""
  engenharia_password: "admin"
"@

[System.IO.File]::WriteAllText("$INSTALL_PATH\config.yaml", $yaml, [System.Text.Encoding]::UTF8)
OK "config.yaml gerado (sync desabilitado para teste local)"

# ==============================================================================
# [3] Criar pasta CSV de teste (se nao existir)
# ==============================================================================
Step 3 "Preparando pasta de CSV de teste..."
if (-not (Test-Path $csvFolder)) {
    New-Item -ItemType Directory -Path $csvFolder -Force | Out-Null
    OK "Pasta criada: $csvFolder"
    INFO "Para testar, copie um arquivo .csv de PCM Tester para esta pasta"
} else {
    $cnt = (Get-ChildItem -Path $csvFolder -Filter "*.csv" -Recurse -ErrorAction SilentlyContinue).Count
    OK "Pasta ja existe. CSVs encontrados: $cnt"
}

# ==============================================================================
# [4] Testar conexao PostgreSQL (via psql se disponivel)
# ==============================================================================
Step 4 "Testando conexao com PostgreSQL em ${dbHost}:${dbPort}..."
$psqlPath = (Get-Command psql -ErrorAction SilentlyContinue)?.Source
if ($psqlPath) {
    $env:PGPASSWORD = $dbPass
    $result = & psql -h $dbHost -p $dbPort -U $dbUser -d $dbName -c "SELECT 1;" 2>&1
    if ($LASTEXITCODE -eq 0) {
        OK "PostgreSQL acessivel e banco '$dbName' existe"
    } else {
        WARN "PostgreSQL respondeu com erro: $result"
        WARN "Crie o banco com: createdb -h $dbHost -U $dbUser $dbName"
        WARN "O MES Client tentara criar as tabelas automaticamente"
    }
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
} else {
    WARN "psql nao encontrado no PATH - teste de banco ignorado"
    WARN "Instale o PostgreSQL e adicione ao PATH para testar"
    WARN "Download: https://www.postgresql.org/download/windows/"
}

# ==============================================================================
# [5] Registrar autostart (task name diferente para nao conflitar)
# ==============================================================================
Step 5 "Registrando tarefa de teste no Task Scheduler..."
try {
    Unregister-ScheduledTask -TaskName $TASK_NAME -Confirm:$false -ErrorAction SilentlyContinue
    $action   = New-ScheduledTaskAction -Execute "$INSTALL_PATH\$EXE_NAME" -WorkingDirectory $INSTALL_PATH
    $trigger  = New-ScheduledTaskTrigger -AtLogOn
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit 0
    Register-ScheduledTask -TaskName $TASK_NAME -Action $action -Trigger $trigger `
                    -Settings $settings -RunLevel Highest -Force | Out-Null
    OK "Tarefa '$TASK_NAME' criada"
} catch {
    WARN "Tarefa nao criada: $_ - nao critica para o teste"
}

# ==============================================================================
# [6] Iniciar MES Client
# ==============================================================================
Step 6 "Iniciando MES Client..."
try {
    Start-Process "$INSTALL_PATH\$EXE_NAME" -WorkingDirectory $INSTALL_PATH
    OK "MES Client iniciado"
    INFO "Aguardando 10 segundos para o log aparecer..."
    Start-Sleep -Seconds 10
} catch {
    FAIL "Nao foi possivel iniciar: $_"
}

# ==============================================================================
# [7] Verificar log
# ==============================================================================
Step 7 "Verificando log de inicializacao..."
if (Test-Path $LOG_FILE) {
    $lines = Get-Content $LOG_FILE -Tail 40 -ErrorAction SilentlyContinue
    Write-Host ""
    Write-Host "  --- ULTIMAS LINHAS DO LOG ---" -ForegroundColor DarkGray
    $lines | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
    Write-Host "  --- FIM DO LOG ---" -ForegroundColor DarkGray
    Write-Host ""

    $hasDB    = $lines | Select-String "banco" -Quiet
    $hasStart = $lines | Select-String "MONITOR" -Quiet
    $hasError = $lines | Select-String "ERROR|ERRO|Traceback" -Quiet

    if ($hasDB)    { OK "Mencao ao banco encontrada no log" } else { WARN "Sem mencao ao banco no log ainda" }
    if ($hasStart) { OK "MONITOR mencionado no log"         } else { WARN "MONITOR ainda nao apareceu no log" }
    if ($hasError) { WARN "ATENCAO: erros encontrados no log - verifique acima" }
} else {
    WARN "Log ainda nao existe: $LOG_FILE"
    WARN "Aguarde o MES Client abrir e verifique o icone na bandeja do sistema"
}

# ==============================================================================
# RESULTADO FINAL
# ==============================================================================
Write-Host ""
Write-Host "  ============================================================" -ForegroundColor Magenta
Write-Host "  RESULTADO DO TESTE LOCAL" -ForegroundColor White
Write-Host "  ============================================================" -ForegroundColor Magenta
Write-Host ""
INFO "Arquivos   : $INSTALL_PATH"
INFO "config.yaml: $INSTALL_PATH\config.yaml"
INFO "Log        : $LOG_FILE"
Write-Host ""
Write-Host "  CHECKLIST MANUAL:" -ForegroundColor White
Write-Host "  [ ] Icone apareceu na bandeja do Windows (system tray)" -ForegroundColor Gray
Write-Host "  [ ] Clicar no icone abre o STATUS" -ForegroundColor Gray
Write-Host "  [ ] STATUS mostra banco como CONECTADO ou tentando" -ForegroundColor Gray
Write-Host "  [ ] Copiar um CSV de PCM Tester para: $csvFolder" -ForegroundColor Gray
Write-Host "  [ ] Log mostra: linhas processadas" -ForegroundColor Gray
Write-Host ""
Write-Host "  Config gerado em: $INSTALL_PATH\config.yaml" -ForegroundColor DarkGray
Write-Host "  Edite o arquivo se precisar ajustar DB host/porta/senha" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  ============================================================" -ForegroundColor Magenta
Write-Host "  Pressione ENTER para fechar." -ForegroundColor Green
Read-Host | Out-Null
