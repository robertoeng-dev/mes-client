# Proteus Client — Edição Windows 7 SP1

Esta pasta guarda **tudo o que é só da edição Windows 7**. A edição Windows 10/11 fica na raiz do projeto (`parser_TE.spec`, `installer/MES_Client_Setup.iss`). As duas edições **não se misturam**:

| | Windows 10/11 | Windows 7 SP1 |
|---|---|---|
| Python | 3.13 (64 bits) | 3.8.10 (32 bits; roda em Win7 32 e 64 bits) |
| Pacote do parser | `parser/` | `csvparser/` (no 3.8, `parser` é um módulo embutido do Python) |
| Spec do PyInstaller | `parser_TE.spec` | `win7/MES_Client_Win7.spec` (PyInstaller 5.13.2, sem UPX) |
| Instalador | `installer/MES_Client_Setup.iss` | `win7/installer/MES_Client_Setup_Win7.iss` |
| Arquivo gerado | `Proteus_Client_Setup_v2.0.0.exe` | `Proteus_Client_Setup_v2.0.0-win7.exe` |
| Windows mínimo | 8.1 (`MinVersion=6.3`) | 7 SP1 (`MinVersion=6.1sp1`) |
| Pré-requisitos | nenhum | KB2533623 (conferido) e UCRT KB2999226 (embutido) |
| Nome no Painel de Controle | Proteus Client | Proteus Client (Windows 7) |

O **código é um só**. A edição Win7 é **gerada** a partir do projeto, nunca editada à mão. Uma correção feita no projeto vale para as duas na próxima geração.

## Arquivos

| Arquivo | Para quê |
|---|---|
| `gerar_edicao_win7.py` | Copia o projeto para `..\WINDOWS7_v2.0\src`, renomeia `parser/` para `csvparser/`, reescreve os imports e troca o instalador Win10 pelo Win7 |
| `MES_Client_Win7.spec` | Spec do PyInstaller 5.13.2 com os módulos `csvparser.*` |
| `build_win7.bat` | Roda os testes no Python 3.8, gera o exe e compila o instalador |
| `requirements-win7.txt` | Versões com wheel `cp38-win32` |
| `installer/MES_Client_Setup_Win7.iss` | Instalador da edição Win7 (mesmas telas da Win10, mais os blocos `[WIN7]`) |
| `prereqs/` (fora do git) | Os `.msu` do KB2999226 (x86 e x64), da Microsoft |

## Como gerar o instalador Win7

Na máquina de build (Windows 10/11, com Python 3.8.10 32 bits e Inno Setup 6):

```bat
python win7\gerar_edicao_win7.py
```

```bat
..\WINDOWS7_v2.0\src\build_win7.bat
```

O resultado fica em `..\WINDOWS7_v2.0\src\installer\Output\Proteus_Client_Setup_v2.0.0-win7.exe`.

Os pacotes `Windows6.1-KB2999226-x86.msu` e `-x64.msu` não vão para o GitHub, porque são binários da Microsoft. O gerador procura os dois em `win7\prereqs\` e, se não achar, em `..\WINDOWS7_v1.0.5\src\installer\prereqs\`. Num clone limpo, baixe-os do Microsoft Update Catalog (KB2999226) e coloque-os em `win7\prereqs\`.

## Testes da edição Win7

O `build_win7.bat` roda `test_parser_validation`, `test_correcoes_fase_a` e `test_compat_py38` no Python 3.8 e para o build se algum falhar. O `test_cliente_f2` (precisa do banco de homologação) roda à mão:

```bat
set MES_AMOSTRAS=D:\...\Logs-Amostras
.venv38\Scripts\python.exe tests\test_cliente_f2.py
```
