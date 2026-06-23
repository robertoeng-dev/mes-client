@echo off
:: Abre o instalador PowerShell com privilégios de Administrador automaticamente
:: Basta dar dois cliques neste arquivo

powershell -Command "Start-Process powershell -ArgumentList '-ExecutionPolicy Bypass -File ""%~dp0Instalar_MES_Client.ps1""' -Verb RunAs"
