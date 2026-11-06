# =============================================================================
# gerar_edicao_win7.py — gera a EDIÇÃO WINDOWS 7 do Proteus Client a partir
# deste projeto (edição Windows 10). Uma fonte só de código; a Win7 é derivada.
#
#   python win7\gerar_edicao_win7.py                 -> ..\WINDOWS7_v2.0\src
#   python win7\gerar_edicao_win7.py <pasta_destino>
#
# O que muda na cópia (e só isto):
#   1. pacote parser\ -> csvparser\  (no Python 3.8 o nome "parser" é um
#      módulo embutido e ganha do pacote do projeto: o exe não acharia
#      parser.cyg_parser)
#   2. imports "from parser..." / "import parser..." reescritos para csvparser
#   3. MES_Client_Win7.spec, build_win7.bat e requirements-win7.txt na raiz
#   4. instalador: sai o da edição Windows 10 (installer\MES_Client_Setup.iss)
#      e entra o da Win7 (win7\installer\MES_Client_Setup_Win7.iss), para
#      não haver como compilar o instalador errado na pasta Win7
#   5. installer\prereqs\*.msu (UCRT KB2999226) copiados — não vão para o git;
#      vêm de win7\prereqs\ ou da edição anterior WINDOWS7_v1.0.5\src
#
# A pasta destino é recriada a cada execução; só .venv38 é preservada (criar o
# venv do 3.8 demora e não muda). Compatível com Python 3.8.
# =============================================================================
import os
import re
import shutil
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
PROJETO = os.path.dirname(AQUI)
RAIZ = os.path.dirname(PROJETO)
DESTINO_PADRAO = os.path.join(RAIZ, "WINDOWS7_v2.0", "src")

# Nunca copiados: dados de cada PC, builds, caches e a própria pasta win7
IGNORAR_PASTAS = {".venv", ".venv38", "dist", "build", "__pycache__", "win7", "Output", ".git"}
IGNORAR_ARQUIVOS = {"config.yaml", ".env", "offsets.json", "offline_queue.jsonl", "client.log",
                    "cadastro_cache.json", "parser_TE.spec", "build_and_publish.bat"}
PRESERVAR_NO_DESTINO = {".venv38"}

IMPORT_RE = re.compile(rb"(?m)^([ \t]*)(from|import)([ \t]+)parser(?=[.\s])")
MSU = ("Windows6.1-KB2999226-x86.msu", "Windows6.1-KB2999226-x64.msu")


def limpar_destino(destino):
    os.makedirs(destino, exist_ok=True)
    for nome in os.listdir(destino):
        if nome in PRESERVAR_NO_DESTINO:
            continue
        caminho = os.path.join(destino, nome)
        if os.path.isdir(caminho):
            shutil.rmtree(caminho)
        else:
            os.remove(caminho)


def copiar_arvore(destino):
    copiados = 0
    for raiz, pastas, arquivos in os.walk(PROJETO):
        pastas[:] = [p for p in pastas if p not in IGNORAR_PASTAS]
        rel = os.path.relpath(raiz, PROJETO)
        partes = [] if rel == "." else rel.split(os.sep)
        if partes and partes[0] == "parser":
            partes[0] = "csvparser"
        alvo = os.path.join(destino, *partes)
        os.makedirs(alvo, exist_ok=True)
        for nome in arquivos:
            if nome in IGNORAR_ARQUIVOS or nome.endswith(".pyc"):
                continue
            shutil.copy2(os.path.join(raiz, nome), os.path.join(alvo, nome))
            copiados += 1
    return copiados


def reescrever_imports(destino):
    """Troca o pacote nos imports. Trabalha em bytes para manter CRLF/LF de cada arquivo."""
    alterados = []
    for raiz, pastas, arquivos in os.walk(destino):
        pastas[:] = [p for p in pastas if p not in PRESERVAR_NO_DESTINO]
        for nome in arquivos:
            if not nome.endswith(".py"):
                continue
            caminho = os.path.join(raiz, nome)
            with open(caminho, "rb") as f:
                antes = f.read()
            depois = IMPORT_RE.sub(rb"\1\2\3csvparser", antes)
            if depois != antes:
                with open(caminho, "wb") as f:
                    f.write(depois)
                alterados.append(os.path.relpath(caminho, destino))
    return alterados


def sobras_de_parser(destino):
    """Qualquer referência ao pacote antigo que a regex não pegou (ex.: string 'parser.x')."""
    sobras = []
    padrao = re.compile(rb"(?m)^[ \t]*(from|import)[ \t]+parser\b|[\"']parser\.[a-z_]+[\"']")
    for raiz, pastas, arquivos in os.walk(destino):
        pastas[:] = [p for p in pastas if p not in PRESERVAR_NO_DESTINO]
        for nome in arquivos:
            if nome.endswith((".py", ".spec")):
                caminho = os.path.join(raiz, nome)
                with open(caminho, "rb") as f:
                    for n, linha in enumerate(f.read().splitlines(), 1):
                        if padrao.search(linha):
                            sobras.append("%s:%d" % (os.path.relpath(caminho, destino), n))
    return sobras


def copiar_kit_win7(destino):
    for nome in ("MES_Client_Win7.spec", "build_win7.bat", "requirements-win7.txt"):
        shutil.copy2(os.path.join(AQUI, nome), os.path.join(destino, nome))
    instalador = os.path.join(destino, "installer")
    win10_iss = os.path.join(instalador, "MES_Client_Setup.iss")
    if os.path.exists(win10_iss):
        os.remove(win10_iss)
    shutil.copy2(os.path.join(AQUI, "installer", "MES_Client_Setup_Win7.iss"), instalador)
    prereqs = os.path.join(instalador, "prereqs")
    os.makedirs(prereqs, exist_ok=True)
    fontes = [os.path.join(AQUI, "prereqs"),
              os.path.join(RAIZ, "WINDOWS7_v1.0.5", "src", "installer", "prereqs")]
    faltando = []
    for msu in MSU:
        origem = next((os.path.join(p, msu) for p in fontes if os.path.isfile(os.path.join(p, msu))), None)
        if origem:
            shutil.copy2(origem, os.path.join(prereqs, msu))
        else:
            faltando.append(msu)
    return faltando


def main():
    destino = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else DESTINO_PADRAO
    if os.path.commonpath([destino, PROJETO]) == PROJETO:
        sys.exit("ERRO: o destino não pode ficar dentro do projeto (%s)" % PROJETO)

    print("Origem :", PROJETO)
    print("Destino:", destino)
    limpar_destino(destino)
    n = copiar_arvore(destino)
    alterados = reescrever_imports(destino)
    faltando = copiar_kit_win7(destino)
    with open(os.path.join(destino, "EDICAO_WIN7_GERADA.txt"), "w", encoding="utf-8") as f:
        f.write("Pasta GERADA por mes-client-main\\win7\\gerar_edicao_win7.py.\n"
                "Não edite aqui: corrija no projeto e gere de novo.\n"
                "Build: build_win7.bat (Python 3.8.10 32 bits + Inno Setup 6).\n")

    print("%d arquivos copiados; parser\\ -> csvparser\\; imports reescritos em %d arquivos" % (n, len(alterados)))
    for a in alterados:
        print("   ", a)
    sobras = sobras_de_parser(destino)
    erro = False
    if sobras:
        print("ERRO: referências ao pacote 'parser' que ficaram para trás:")
        for s in sobras:
            print("   ", s)
        erro = True
    if faltando:
        print("ERRO: pré-requisitos do instalador não encontrados: %s" % ", ".join(faltando))
        print("      coloque os .msu em %s" % os.path.join(AQUI, "prereqs"))
        erro = True
    if erro:
        sys.exit(1)
    print("Pronto. Próximo passo: %s\\build_win7.bat" % destino)


if __name__ == "__main__":
    main()
