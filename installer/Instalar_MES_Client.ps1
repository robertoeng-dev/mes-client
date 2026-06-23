# ==============================================================================
# Instalar_MES_Client.ps1
# MES Client — Instalador Automático de Estação PCM Tester
# Salcomp — Engenharia de Teste | Manaus
# ==============================================================================
# Como usar:
#   1. Copie esta pasta para um pendrive ou compartilhamento de rede
#   2. Na estação alvo, abra PowerShell como Administrador
#   3. Execute:  .\Instalar_MES_Client.ps1
# ==============================================================================

#Requires -RunAsAdministrator
$ErrorActionPreference = "Stop"
$Host.UI.RawUI.WindowTitle = "MES Client — Instalador"

# ==============================================================================
# CONSTANTES DE INFRAESTRUTURA
# Altere aqui se o servidor ou credenciais mudarem
# ==============================================================================
$SERVER_IP     = "172.21.70.184"
$SAMBA_SHARE   = "\\$SERVER_IP\NonAlphaSec2Info"
$SAMBA_USER    = "mesclient"
$SAMBA_PASS    = "mes@2026"
$DB_HOST       = $SERVER_IP
$DB_PORT       = 5432
$DB_NAME       = "mes_db"
$DB_USER       = "mes_user"
$DB_PASS       = "mes123"
$INSTALL_PATH  = "C:\Utility\MES"
$EXE_NAME      = "MES_Client.exe"
$TASK_NAME     = "MES_Client_Autostart"
$LOG_FILE      = "$INSTALL_PATH\logs\client.log"
$INSTALLER_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path

# ==============================================================================
# FUNÇÕES DE OUTPUT
# ==============================================================================
function Header {
    Clear-Host
    Write-Host ""
    Write-Host "  ╔══════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "  ║         MES CLIENT — INSTALADOR DE ESTAÇÃO              ║" -ForegroundColor Cyan
    Write-Host "  ║         Salcomp — Engenharia de Teste — Manaus          ║" -ForegroundColor Cyan
    Write-Host "  ╚══════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
    Write-Host ""
}

function Step { param([int]$n, [string]$msg)
    Write-Host "  [$n] $msg" -ForegroundColor Yellow
}

function OK   { param([string]$msg) Write-Host "      ✔  $msg" -ForegroundColor Green }
function FAIL { param([string]$msg) Write-Host "      ✘  $msg" -ForegroundColor Red }
function INFO { param([string]$msg) Write-Host "      →  $msg" -ForegroundColor Gray }
function WARN { param([string]$msg) Write-Host "      ⚠  $msg" -ForegroundColor DarkYellow }

function Pause-Continue {
    Write-Host ""
    Write-Host "  Pressione ENTER para continuar..." -ForegroundColor DarkGray
    Read-Host | Out-Null
}

# ==============================================================================
# PASSO 0 — COLETA DE DADOS DA ESTAÇÃO
# ==============================================================================
function Get-StationInfo {
    Header
    Write-Host "  CONFIGURAÇÃO DA ESTAÇÃO" -ForegroundColor White
    Write-Host "  ─────────────────────────────────────────────────────────" -ForegroundColor DarkGray
    Write-Host ""

    # Modelo
    Write-Host "  Modelo do produto (ex: A06, A17, A16):" -ForegroundColor Cyan
    $model = (Read-Host "  Modelo").Trim().ToUpper()
    if (-not $model) { FAIL "Modelo não pode ser vazio."; exit 1 }

    # Número da máquina
    Write-Host ""
    Write-Host "  ID da máquina (ex: BR-PCMTEST-01):" -ForegroundColor Cyan
    $machine = (Read-Host "  Máquina").Trim().ToUpper()
    if (-not $machine) { FAIL "ID da máquina não pode ser vazio."; exit 1 }

    # Linha de produção
    Write-Host ""
    Write-Host "  Linha de produção (ex: NAVAJO, TOMAHAWK):" -ForegroundColor Cyan
    $line = (Read-Host "  Linha").Trim().ToUpper()
    if (-not $line) { $line = "NAVAJO" }

    # Pasta CSV
    $defaultCsv = "D:\Testpad software\CSV\$model"
    Write-Host ""
    Write-Host "  Pasta dos CSVs do TestPad [ENTER para usar padrão]:" -ForegroundColor Cyan
    Write-Host "  Padrão: $defaultCsv" -ForegroundColor DarkGray
    $csvInput = (Read-Host "  Pasta CSV").Trim()
    $csvFolder = if ($csvInput) { $csvInput } else { $defaultCsv }

    # Resumo
    Write-Host ""
    Write-Host "  ─────────────────────────────────────────────────────────" -ForegroundColor DarkGray
    Write-Host "  RESUMO DA CONFIGURAÇÃO:" -ForegroundColor White
    Write-Host ""
    $stationId = "PCM_${model}_${machine}"
    INFO "Station ID   : $stationId"
    INFO "Modelo       : $model"
    INFO "Linha        : $line"
    INFO "Pasta CSV    : $csvFolder"
    INFO "Destino Sync : $SAMBA_SHARE\logs\$model"
    INFO "Banco        : $DB_HOST`:$DB_PORT/$DB_NAME"
    INFO "Instalar em  : $INSTALL_PATH"
    Write-Host ""
    Write-Host "  Confirma? (S/N):" -ForegroundColor Cyan
    $confirm = (Read-Host "").Trim().ToUpper()
    if ($confirm -ne "S") {
        WARN "Instalação cancelada pelo usuário."
        exit 0
    }

    return @{
        Model     = $model
        Machine   = $machine
        Line      = $line
        CsvFolder = $csvFolder
        StationId = $stationId
        SyncDest  = "$SAMBA_SHARE\logs\$model"
    }
}

# ==============================================================================
# PASSO 1 — VERIFICAR REDE
# ==============================================================================
function Test-Network {
    Step 1 "Verificando conectividade com o servidor ($SERVER_IP)..."
    try {
        $ping = Test-Connection -ComputerName $SERVER_IP -Count 2 -Quiet -ErrorAction Stop
        if ($ping) {
            OK "Servidor acessível: $SERVER_IP"
        } else {
            FAIL "Servidor inacessível: $SERVER_IP"
            FAIL "Verifique a rede corporativa e tente novamente."
            exit 1
        }
    } catch {
        FAIL "Erro ao testar rede: $_"
        exit 1
    }
}

# ==============================================================================
# PASSO 2 — MAPEAR SAMBA
# ==============================================================================
function Map-Samba {
    Step 2 "Mapeando compartilhamento Samba..."

    # Remove mapeamento antigo (se existir) silenciosamente
    net use * /delete /y 2>$null | Out-Null

    try {
        # Testa acesso sem mapear drive (mais robusto que net use)
        $result = net use "\\$SERVER_IP\NonAlphaSec2Info" /user:$SAMBA_USER $SAMBA_PASS 2>&1
        if ($LASTEXITCODE -eq 0) {
            OK "Samba conectado: $SAMBA_SHARE"
        } else {
            # Tenta sem senha (já autenticado na rede)
            $result2 = net use "\\$SERVER_IP\NonAlphaSec2Info" 2>&1
            if ($LASTEXITCODE -eq 0) {
                OK "Samba conectado (autenticação de rede): $SAMBA_SHARE"
            } else {
                WARN "Não foi possível conectar ao Samba automaticamente."
                WARN "Verifique manualmente: $SAMBA_SHARE"
                WARN "Usuário: $SAMBA_USER | Senha: $SAMBA_PASS"
                WARN "Continuando instalação sem Samba..."
            }
        }
    } catch {
        WARN "Erro ao mapear Samba: $_ — continuando..."
    }
}

# ==============================================================================
# PASSO 3 — INSTALAR ARQUIVOS
# ==============================================================================
function Install-Files { param($info)
    Step 3 "Instalando arquivos em $INSTALL_PATH..."

    # Cria estrutura de diretórios
    @("$INSTALL_PATH", "$INSTALL_PATH\logs", "$INSTALL_PATH\state", "$INSTALL_PATH\data") |
        ForEach-Object {
            New-Item -ItemType Directory -Path $_ -Force | Out-Null
        }

    # Copia EXE
    $srcExe = Join-Path $INSTALLER_DIR $EXE_NAME
    if (-not (Test-Path $srcExe)) {
        FAIL "$EXE_NAME não encontrado em: $INSTALLER_DIR"
        FAIL "Coloque o instalador na mesma pasta do MES_Client.exe"
        exit 1
    }
    Copy-Item $srcExe "$INSTALL_PATH\$EXE_NAME" -Force
    OK "MES_Client.exe copiado"

    # Copia spec_limits.csv
    $srcSpec = Join-Path $INSTALLER_DIR "spec_limits.csv"
    if (Test-Path $srcSpec) {
        Copy-Item $srcSpec "$INSTALL_PATH\spec_limits.csv" -Force
        OK "spec_limits.csv copiado"
    } else {
        WARN "spec_limits.csv não encontrado — crie manualmente se necessário"
    }
}

# ==============================================================================
# PASSO 4 — GERAR config.yaml
# ==============================================================================
function Write-Config { param($info)
    Step 4 "Gerando config.yaml para $($info.StationId)..."

    $csvFolderYaml = $info.CsvFolder -replace '\\', '/'
    $syncDestYaml  = $info.SyncDest  -replace '\\\\', '\\\\'

    $yaml = @"
database:
  enabled: true
  host: $DB_HOST
  port: $DB_PORT
  name: $DB_NAME
  user: $DB_USER
  password: $DB_PASS
  table: mes_test_results

station:
  id: $($info.StationId)
  type: PCM_TESTER
  model: $($info.Model)
  line: $($info.Line)

log:
  folder: $csvFolderYaml
  recursive: true

operation:
  mode: both

sync:
  enabled: true
  destination_folder: $($info.SyncDest)
  mode: diff

parser:
  scan_interval: 5

spec_check:
  enabled: true
  file: spec_limits.csv

auth:
  operador_password: ""
  engenharia_password: "admin"
"@

    $yaml | Out-File -FilePath "$INSTALL_PATH\config.yaml" -Encoding utf8 -Force
    OK "config.yaml gerado para $($info.StationId)"
    INFO "Pasta CSV  : $($info.CsvFolder)"
    INFO "Sync para  : $($info.SyncDest)"
}

# ==============================================================================
# PASSO 5 — CRIAR TAREFA DE INICIALIZAÇÃO AUTOMÁTICA
# ==============================================================================
function Register-Autostart {
    Step 5 "Registrando inicialização automática (Task Scheduler)..."

    try {
        # Remove tarefa antiga se existir
        Unregister-ScheduledTask -TaskName $TASK_NAME -Confirm:$false -ErrorAction SilentlyContinue

        $action   = New-ScheduledTaskAction -Execute "$INSTALL_PATH\$EXE_NAME" -WorkingDirectory $INSTALL_PATH
        $trigger  = New-ScheduledTaskTrigger -AtLogOn
        $settings = New-ScheduledTaskSettingsSet `
            -ExecutionTimeLimit 0 `
            -RestartCount 3 `
            -RestartInterval (New-TimeSpan -Minutes 1) `
            -StartWhenAvailable

        Register-ScheduledTask `
            -TaskName  $TASK_NAME `
            -Action    $action `
            -Trigger   $trigger `
            -Settings  $settings `
            -RunLevel  Highest `
            -Force | Out-Null

        OK "Tarefa '$TASK_NAME' criada — inicia automaticamente no login"
    } catch {
        WARN "Não foi possível criar a tarefa agendada: $_"
        WARN "Crie um atalho manual na pasta de Inicialização do Windows."
    }
}

# ==============================================================================
# PASSO 6 — CRIAR ATALHO NA ÁREA DE TRABALHO (todos os usuários)
# ==============================================================================
function Create-Shortcut {
    Step 6 "Criando atalho na Área de Trabalho..."
    try {
        $desktopPath = [Environment]::GetFolderPath("CommonDesktopDirectory")
        $shortcutPath = "$desktopPath\MES Client.lnk"
        $wsh = New-Object -ComObject WScript.Shell
        $shortcut = $wsh.CreateShortcut($shortcutPath)
        $shortcut.TargetPath       = "$INSTALL_PATH\$EXE_NAME"
        $shortcut.WorkingDirectory = $INSTALL_PATH
        $shortcut.Description      = "MES Client — Monitor de Teste PCM"
        $shortcut.IconLocation     = "$INSTALL_PATH\$EXE_NAME"
        $shortcut.Save()
        OK "Atalho criado em: $shortcutPath"
    } catch {
        WARN "Atalho não pôde ser criado: $_"
    }
}

# ==============================================================================
# PASSO 7 — VALIDAR PASTA CSV
# ==============================================================================
function Test-CsvFolder { param($info)
    Step 7 "Validando pasta de CSVs: $($info.CsvFolder)..."

    if (Test-Path $info.CsvFolder) {
        $csvCount = (Get-ChildItem -Path $info.CsvFolder -Filter "*.csv" -Recurse -ErrorAction SilentlyContinue).Count
        OK "Pasta existe. CSVs encontrados: $csvCount"
        if ($csvCount -eq 0) {
            WARN "Nenhum CSV encontrado ainda — aguarde produção ou verifique o caminho."
        }
    } else {
        WARN "Pasta não encontrada: $($info.CsvFolder)"
        WARN "Verifique o caminho após instalar o TestPad."
        WARN "O monitor começará a processar assim que a pasta existir."
    }
}

# ==============================================================================
# PASSO 8 — INICIAR O MES CLIENT PARA VALIDAÇÃO
# ==============================================================================
function Start-MesClient {
    Step 8 "Iniciando MES Client para validação..."
    try {
        Start-Process "$INSTALL_PATH\$EXE_NAME" -WorkingDirectory $INSTALL_PATH
        OK "MES Client iniciado"
        INFO "Aguardando 8 segundos para o log aparecer..."
        Start-Sleep -Seconds 8
    } catch {
        FAIL "Não foi possível iniciar o MES Client: $_"
    }
}

# ==============================================================================
# PASSO 9 — VALIDAR LOG
# ==============================================================================
function Test-Log {
    Step 9 "Validando log de inicialização..."

    if (-not (Test-Path $LOG_FILE)) {
        WARN "Log ainda não existe: $LOG_FILE"
        WARN "Aguarde alguns segundos e verifique manualmente."
        return
    }

    $logContent = Get-Content $LOG_FILE -Tail 30 -ErrorAction SilentlyContinue
    $checks = @(
        @{ Pattern = "Conexão com banco estabelecida";           Label = "Conexão PostgreSQL" },
        @{ Pattern = "Estrutura do banco validada";              Label = "Tabelas criadas/validadas" },
        @{ Pattern = "MONITOR INICIADO";                         Label = "Monitor iniciado" }
    )

    foreach ($check in $checks) {
        $found = $logContent | Select-String -Pattern $check.Pattern -Quiet
        if ($found) {
            OK $check.Label
        } else {
            WARN "$($check.Label) — não confirmado ainda (verifique o log)"
        }
    }
}

# ==============================================================================
# RELATÓRIO FINAL
# ==============================================================================
function Show-Report { param($info)
    Write-Host ""
    Write-Host "  ══════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "  RELATÓRIO DE INSTALAÇÃO" -ForegroundColor White
    Write-Host "  ══════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host ""
    INFO "Estação    : $($info.StationId)"
    INFO "Instalado  : $INSTALL_PATH"
    INFO "Config     : $INSTALL_PATH\config.yaml"
    INFO "Log        : $LOG_FILE"
    INFO "Autostart  : Task Scheduler — '$TASK_NAME'"
    Write-Host ""
    Write-Host "  CHECKLIST DE HOMOLOGAÇÃO:" -ForegroundColor White
    Write-Host ""
    Write-Host "  [ ] Ícone verde na bandeja do Windows" -ForegroundColor Gray
    Write-Host "  [ ] STATUS mostra: RUNNING" -ForegroundColor Gray
    Write-Host "  [ ] Log: Conexão com banco estabelecida" -ForegroundColor Gray
    Write-Host "  [ ] Log: MONITOR INICIADO" -ForegroundColor Gray
    Write-Host "  [ ] Log: SYNC: arquivo copiado" -ForegroundColor Gray
    Write-Host "  [ ] Log: Lote inserido com sucesso" -ForegroundColor Gray
    Write-Host "  [ ] SELECT COUNT(*) FROM mes_test_results; aumentou" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  ──────────────────────────────────────────────────────────" -ForegroundColor DarkGray
    Write-Host "  Para verificar o banco (execute no servidor):" -ForegroundColor DarkGray
    Write-Host "  psql -h $SERVER_IP -U $DB_USER -d $DB_NAME -c `"SELECT COUNT(*) FROM mes_test_results;`"" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  Senha do banco: $DB_PASS" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  ══════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "  Instalação concluída! Pressione ENTER para fechar." -ForegroundColor Green
    Write-Host ""
    Read-Host | Out-Null
}

# ==============================================================================
# MAIN — FLUXO PRINCIPAL
# ==============================================================================
try {
    Header

    # Coleta dados da estação
    $info = Get-StationInfo

    Header
    Write-Host "  INSTALANDO — $($info.StationId)" -ForegroundColor White
    Write-Host "  ─────────────────────────────────────────────────────────" -ForegroundColor DarkGray
    Write-Host ""

    Test-Network
    Map-Samba
    Install-Files  $info
    Write-Config   $info
    Register-Autostart
    Create-Shortcut
    Test-CsvFolder $info
    Start-MesClient
    Test-Log

    Show-Report $info

} catch {
    Write-Host ""
    FAIL "ERRO INESPERADO: $_"
    Write-Host ""
    Write-Host "  Pressione ENTER para fechar." -ForegroundColor DarkGray
    Read-Host | Out-Null
    exit 1
}
