@echo off
:: =============================================================================
:: build_win7.bat - gera o MES_Client.exe e o instalador da EDICAO WINDOWS 7
::                  do Proteus Client 2.0
::
:: Roda DENTRO da pasta gerada por win7\gerar_edicao_win7.py (padrao:
:: WINDOWS7_v2.0\src). Nao rode na pasta do projeto: la' o pacote ainda se
:: chama "parser", que colide com o modulo embutido do Python 3.8.
::
:: Pre-requisitos na maquina de build (Windows 10/11 serve):
::   - Python 3.8.10 32 bits (python.org/ftp/python/3.8.10/python-3.8.10.exe)
::     Ultimo instalador oficial compativel com Windows 7. O build usa 32 bits
::     porque o mesmo exe roda em Win7 32 e 64 bits.
::   - Inno Setup 6 (ISCC.exe)
::   - installer\prereqs\Windows6.1-KB2999226-x86.msu e -x64.msu (o gerador copia)
::
:: Ajuste PY38 e ISCC abaixo se estiverem em outro lugar.
:: =============================================================================
setlocal
cd /d "%~dp0"

if not exist "csvparser\__init__.py" (
    echo [ERRO] Esta pasta nao e' a edicao Win7 gerada. Rode antes:
    echo        python win7\gerar_edicao_win7.py
    exit /b 1
)

set "PY38=%LOCALAPPDATA%\Programs\Python\Python38-32\python.exe"
set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"

if not exist ".venv38\Scripts\python.exe" (
    if not exist "%PY38%" (
        echo [ERRO] Python 3.8 32 bits nao encontrado em "%PY38%"
        exit /b 1
    )
    echo Criando .venv38...
    "%PY38%" -m venv .venv38 || exit /b 1
    .venv38\Scripts\python.exe -m pip install --only-binary=:all: -r requirements-win7.txt || exit /b 1
)

echo.
echo === Testes (Python 3.8) ===
set PYTHONIOENCODING=utf-8
.venv38\Scripts\python.exe tests\test_parser_validation.py || exit /b 1
.venv38\Scripts\python.exe tests\test_correcoes_fase_a.py  || exit /b 1
.venv38\Scripts\python.exe tests\test_compat_py38.py       || exit /b 1

echo.
echo === PyInstaller ===
.venv38\Scripts\python.exe -m PyInstaller --noconfirm --clean --distpath dist --workpath build MES_Client_Win7.spec || exit /b 1

echo.
echo === Inno Setup (edicao WIN7) ===
"%ISCC%" /Q installer\MES_Client_Setup_Win7.iss || exit /b 1

echo.
echo Pronto: installer\Output\Proteus_Client_Setup_v2.0.0-win7.exe
endlocal
