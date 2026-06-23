# ==============================================================================
# Desinstalar_MES_Client.ps1 - Remove o MES Client da estacao
# ==============================================================================

#Requires -RunAsAdministrator
$ErrorActionPreference = "SilentlyContinue"

$INSTALL_PATH = "C:\Utility\MES"
$TASK_NAME    = "MES_Client_Autostart"
$EXE_NAME     = "MES_Client.exe"

Write-Host ""
Write-Host "  MES CLIENT - DESINSTALADOR" -ForegroundColor Red
Write-Host "  -------------------------------------" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Confirma a desinstalacao? (S/N):" -ForegroundColor Yellow
$confirm = (Read-Host "").Trim().ToUpper()
if ($confirm -ne "S") { Write-Host "  Cancelado."; exit 0 }

Write-Host "  -> Encerrando MES Client..." -ForegroundColor Gray
Get-Process | Where-Object {
    try { $_.MainModule.FileName -like "*MES_Client*" } catch { $false }
} | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

Write-Host "  -> Removendo tarefa agendada..." -ForegroundColor Gray
Unregister-ScheduledTask -TaskName $TASK_NAME -Confirm:$false -ErrorAction SilentlyContinue

$desktopPath = [Environment]::GetFolderPath("CommonDesktopDirectory")
Remove-Item "$desktopPath\MES Client.lnk" -Force -ErrorAction SilentlyContinue

if (Test-Path $INSTALL_PATH) {
    Write-Host "  -> Deseja remover TODOS os arquivos incluindo logs? (S/N):" -ForegroundColor Yellow
    $removeLogs = (Read-Host "").Trim().ToUpper()
    if ($removeLogs -eq "S") {
        Remove-Item $INSTALL_PATH -Recurse -Force
        Write-Host "  OK  Pasta removida: $INSTALL_PATH" -ForegroundColor Green
    } else {
        Remove-Item "$INSTALL_PATH\$EXE_NAME" -Force -ErrorAction SilentlyContinue
        Remove-Item "$INSTALL_PATH\config.yaml" -Force -ErrorAction SilentlyContinue
        Write-Host "  OK  EXE e config removidos. Logs mantidos em: $INSTALL_PATH\logs" -ForegroundColor Green
    }
}

# Desconecta compartilhamento Samba (ignora erros se nao mapeado)
$sambaCon = "\\172.21.70.184\NonAlphaSec2Info"
$conMap = Get-SmbMapping -RemotePath $sambaCon -ErrorAction SilentlyContinue
if ($conMap) {
    Remove-SmbMapping -RemotePath $sambaCon -Force -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "  OK  Desinstalacao concluida." -ForegroundColor Green
Write-Host ""
Write-Host "  Pressione ENTER para fechar."
Read-Host | Out-Null
