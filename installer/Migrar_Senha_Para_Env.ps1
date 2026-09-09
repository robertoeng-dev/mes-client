# =============================================================================
# Migrar_Senha_Para_Env.ps1 - tira a senha do banco de dentro do config.yaml
# =============================================================================
#
# ASCII puro de proposito: o PowerShell 5.1 le' .ps1 como ANSI quando nao ha
# BOM, e acentos quebram o parser.
#
# Estacoes instaladas ate' a v1.0.3 ficaram com a senha do PostgreSQL em texto
# plano dentro do config.yaml, porque o instalador antigo escrevia o valor
# literal. A partir da v1.0.4 a senha mora no .env e o config guarda apenas o
# placeholder.
#
# Este script converte uma estacao ja' instalada, sem reinstalar nada:
#
#   1. le' a senha literal do config.yaml
#   2. grava .env com MES_DB_PASSWORD
#   3. troca a linha do config.yaml pelo placeholder
#   4. guarda um backup do config.yaml antes de alterar
#
# USO (como Administrador, na estacao):
#   powershell -ExecutionPolicy Bypass -File Migrar_Senha_Para_Env.ps1
#   powershell -ExecutionPolicy Bypass -File Migrar_Senha_Para_Env.ps1 -Caminho "D:\MES"
#   powershell -ExecutionPolicy Bypass -File Migrar_Senha_Para_Env.ps1 -Simular
#
# E' idempotente: rodar de novo numa estacao ja' migrada nao faz nada.
# =============================================================================

param(
    [string]$Caminho = "C:\Utility\MES",
    [switch]$Simular
)

$ErrorActionPreference = "Stop"

$cfgPath = Join-Path $Caminho "config.yaml"
$envPath = Join-Path $Caminho ".env"

Write-Host ""
Write-Host "Migracao da senha do banco para .env" -ForegroundColor Cyan
Write-Host ("-" * 60)
Write-Host "  Estacao: $Caminho"

if (-not (Test-Path $cfgPath)) {
    Write-Host "  config.yaml nao encontrado. Nada a fazer." -ForegroundColor Yellow
    exit 1
}

$linhas = Get-Content $cfgPath
$idx    = -1
$senha  = $null

for ($i = 0; $i -lt $linhas.Count; $i++) {
    # Apenas a chave 'password:' indentada dentro de database:
    if ($linhas[$i] -match '^(\s+)password:\s*(.+?)\s*$') {
        $valor = $Matches[2].Trim()

        if ($valor -like '*MES_DB_PASSWORD*') {
            Write-Host "  Ja' usa o placeholder - estacao ja' migrada." -ForegroundColor Green
            if (Test-Path $envPath) {
                Write-Host "  .env presente. Nada a fazer." -ForegroundColor Green
                exit 0
            }
            Write-Host "  ATENCAO: config aponta para MES_DB_PASSWORD mas .env NAO existe." -ForegroundColor Red
            Write-Host "  O cliente nao vai subir. Crie o .env com a senha correta:" -ForegroundColor Yellow
            Write-Host "    MES_DB_PASSWORD=<senha>" -ForegroundColor Yellow
            exit 1
        }

        # Remove aspas se houver
        $senha = $valor.Trim("'").Trim('"')
        $idx   = $i
        break
    }
}

if ($idx -lt 0) {
    Write-Host "  Nenhuma linha 'password:' encontrada no config.yaml." -ForegroundColor Yellow
    exit 1
}

if (-not $senha) {
    Write-Host "  A linha 'password:' esta' vazia. Nada a migrar." -ForegroundColor Yellow
    exit 1
}

Write-Host "  Senha literal encontrada na linha $($idx + 1)."

if ($Simular) {
    Write-Host ""
    Write-Host "  [SIMULACAO] Seria feito:" -ForegroundColor Yellow
    Write-Host "    - backup  : config.yaml.bak-<data>"
    Write-Host "    - criado  : .env com MES_DB_PASSWORD"
    Write-Host "    - alterado: linha $($idx + 1) para o placeholder"
    Write-Host ""
    Write-Host "  Nada foi alterado." -ForegroundColor Yellow
    exit 0
}

# --- backup antes de qualquer escrita ---
$bak = "$cfgPath.bak-" + (Get-Date -Format "yyyyMMdd-HHmmss")
Copy-Item $cfgPath $bak -Force
Write-Host "  Backup: $bak" -ForegroundColor Gray

# --- .env ---
# Se ja' existir um .env, preserva as outras chaves e so' ajusta a nossa.
$envLinhas = @()
if (Test-Path $envPath) {
    $envLinhas = @(Get-Content $envPath | Where-Object { $_ -notmatch '^\s*MES_DB_PASSWORD\s*=' })
}
$envLinhas += "MES_DB_PASSWORD=$senha"

# SEM BOM. 'Set-Content -Encoding utf8' no PowerShell 5.1 grava BOM, e o BOM
# gruda no nome da primeira chave do .env: a variavel vira ﻿MES_DB_PASSWORD
# e o cliente nao encontra a senha. Escrevemos com UTF8Encoding($false).
[IO.File]::WriteAllText($envPath,
                        ($envLinhas -join "`r`n") + "`r`n",
                        (New-Object Text.UTF8Encoding($false)))
Write-Host "  .env gravado com MES_DB_PASSWORD (sem BOM)." -ForegroundColor Green

# --- config.yaml: troca o literal pelo placeholder, preservando a indentacao ---
$linhas[$idx] = $linhas[$idx] -replace '^(\s+password:\s*).+$', ('${1}' + '${MES_DB_PASSWORD}')
# Tambem sem BOM - vale para o YAML pelo mesmo motivo do .env
[IO.File]::WriteAllText($cfgPath,
                        ($linhas -join "`r`n") + "`r`n",
                        (New-Object Text.UTF8Encoding($false)))
Write-Host "  config.yaml agora usa o placeholder." -ForegroundColor Green

Write-Host ""
Write-Host "Migracao concluida." -ForegroundColor Green
Write-Host "Reinicie o MES Client para validar:" -ForegroundColor Yellow
Write-Host "  taskkill /F /IM MES_Client.exe" -ForegroundColor Gray
Write-Host "  schtasks /Run /TN MES_Client_Autostart" -ForegroundColor Gray
Write-Host "Confira em logs\client.log a linha 'Conexao com banco estabelecida'." -ForegroundColor Gray
Write-Host ""
