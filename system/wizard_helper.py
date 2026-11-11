# =============================================================================
# wizard_helper.py — modo do MES_Client.exe usado pelo INSTALADOR (2.0.3)
# =============================================================================
#
#   MES_Client.exe --wizard catalogo <entrada.txt> <saida.txt>
#   MES_Client.exe --wizard vincular <entrada.txt> <saida.txt> <ESTACAO>
#
# O Inno Setup não fala com o PostgreSQL. O wizard extrai o exe novo para o
# {tmp} e o chama neste modo, que reaproveita o DBWriter (mesma conexão,
# mesma função mes_vincular_estacao e mesmas regras do banco do cliente).
#
# entrada.txt (gravado pelo wizard, UTF-8): uma chave=valor por linha —
#   host, port, name, user, password, set_role. É APAGADO logo após a leitura
#   (contém a senha). A senha nunca vai na linha de comando.
#
# saida.txt: só ASCII (o Pascal Script lê como ANSI), campos separados por |
#   1ª linha  OK|<nome do PC>|<versão do schema>   ou   ERRO|<mensagem>
#   catalogo: depois, uma linha por fonte ATIVA (planta, seção, linha,
#     estação, fonte e formato ativos):
#     F|planta|planta_nome|secao|secao_nome|linha|linha_nome|estacao|
#       estacao_descricao|tipo_sigla|modelo|fonte|formato|padrao|STATUS|host
#     STATUS = LIVRE, ESTE_PC (vinculada a este PC) ou OCUPADA (outro PC).
#   vincular: OK|<nome do PC>|<station_pk>  ou  RECUSADO|<mensagem do banco>
#
# Roda antes do SingleInstance e sem Tkinter/bandeja: pode rodar com o
# cliente antigo ainda aberto (o instalador só o encerra depois).
# =============================================================================

import os
import sys
import unicodedata

SEP = "|"


def ascii_seguro(valor):
    """Texto -> ASCII sem acento, sem | e sem quebra de linha."""
    if valor is None:
        return ""
    s = unicodedata.normalize("NFKD", str(valor))
    s = s.encode("ascii", "ignore").decode("ascii")
    return s.replace(SEP, "/").replace("\r", " ").replace("\n", " ").strip()


def ler_entrada(caminho):
    """Lê chave=valor (UTF-8 com ou sem BOM; ANSI como reserva) e apaga o arquivo."""
    bruto = open(caminho, "rb").read()
    try:
        os.remove(caminho)
    except OSError:
        pass
    try:
        texto = bruto.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = bruto.decode("cp1252", "replace")
    dados = {}
    for linha in texto.splitlines():
        if "=" in linha:
            k, v = linha.split("=", 1)
            dados[k.strip().lower()] = v.strip("\r\n")
    return dados


def config_da_entrada(dados):
    db = {
        "host": dados.get("host", "").strip(),
        "port": int(dados.get("port") or 5432),
        "name": dados.get("name", "").strip(),
        "user": dados.get("user", "").strip(),
        "connect_timeout": 8,
    }
    if dados.get("password"):
        db["password"] = dados["password"]
    if dados.get("set_role", "").strip():
        db["set_role"] = dados["set_role"].strip()
    return {"database": db, "cliente": {"host_id": ""}}


def status_slot(host_vinculado, host_pc):
    if not host_vinculado:
        return "LIVRE"
    return "ESTE_PC" if str(host_vinculado).strip().upper() == host_pc else "OCUPADA"


def linhas_catalogo(catalogo, host_pc):
    """Fontes ativas do catálogo no formato da saída (sem o prefixo OK)."""
    ativos = ("planta_ativa", "secao_ativa", "linha_ativa", "estacao_ativa", "fonte_ativa", "formato_ativo")
    saida = []
    for r in catalogo:
        if not all(r.get(k) for k in ativos):
            continue
        campos = ["F", r.get("planta_codigo"), r.get("planta_nome"), r.get("secao_codigo"), r.get("secao_nome"),
                  r.get("linha_codigo"), r.get("linha_nome"), r.get("estacao_codigo"), r.get("estacao_descricao"),
                  r.get("tipo_sigla"), r.get("modelo_atual"), r.get("fonte_codigo"), r.get("formato_codigo"),
                  r.get("padrao_arquivo"), status_slot(r.get("host_vinculado"), host_pc), r.get("host_vinculado")]
        saida.append(SEP.join(ascii_seguro(c) for c in campos))
    return saida


def _conectar(config):
    from database.db_writer import DBWriter
    from state.app_context import runtime_status
    w = DBWriter(config=config)
    if w.conn is None:
        raise ConnectionError(runtime_status.snapshot().get("last_error") or "sem conexao com o banco")
    return w


def explicar_falha(texto, db):
    """Erro de conexão do libpq -> frase curta para o técnico."""
    t = str(texto)
    if "password authentication failed" in t or "no password supplied" in t:
        return "Senha recusada para o usuario %s. Confira a senha (e o usuario)." % db.get("user")
    if "does not exist" in t and "database" in t:
        return "O banco %s nao existe no servidor. Confira o nome do banco." % db.get("name")
    if "role" in t and "does not exist" in t:
        return "O usuario %s nao existe no servidor." % db.get("user")
    if "permission denied for database" in t or "not permitted to log in" in t:
        return "O usuario %s nao tem acesso ao banco %s." % (db.get("user"), db.get("name"))
    if "timeout" in t or "could not connect" in t or "Connection refused" in t or "could not translate host" in t:
        return "O servidor %s:%s nao respondeu (rede, firewall ou endereco errado)." % (db.get("host"), db.get("port"))
    return t


def executar(acao, entrada, estacao=None):
    """Devolve a lista de linhas da saída. Nunca levanta exceção."""
    from database.db_writer import CadastroRecusado, SCHEMA_SUPORTADO
    config = {"database": {}}
    try:
        config = config_da_entrada(ler_entrada(entrada))
        w = _conectar(config)
    except Exception as e:
        return ["ERRO" + SEP + ascii_seguro("Sem conexao com o banco: " + explicar_falha(e, config["database"]))]
    try:
        versao = w.versao_schema()
        if versao != SCHEMA_SUPORTADO:
            return ["ERRO" + SEP + ascii_seguro("Banco sem o cadastro 2.0 (schema %s; esperado %s). "
                                                 "Confira o nome do banco." % (versao, SCHEMA_SUPORTADO))]
        cab = SEP.join(["OK", ascii_seguro(w.host_id), str(versao)])
        if acao == "catalogo":
            return [cab] + linhas_catalogo(w.listar_catalogo(), w.host_id)
        if acao == "vincular":
            try:
                pk = w.vincular(estacao)
            except CadastroRecusado as e:
                return ["RECUSADO" + SEP + ascii_seguro(e.mensagem)]
            return [SEP.join(["OK", ascii_seguro(w.host_id), str(pk)])]
        return ["ERRO" + SEP + "acao desconhecida: " + ascii_seguro(acao)]
    except Exception as e:
        return ["ERRO" + SEP + ascii_seguro(str(e))]
    finally:
        w.close()


def main(argv):
    """argv = sys.argv. Código de saída: 0 se gravou a saída, 2 se não."""
    try:
        i = argv.index("--wizard")
        acao, entrada, saida = argv[i + 1], argv[i + 2], argv[i + 3]
        estacao = argv[i + 4].strip().upper() if len(argv) > i + 4 else None
    except (ValueError, IndexError):
        return 2
    if acao == "vincular" and not estacao:
        linhas = ["ERRO|informe o codigo da estacao"]
    else:
        linhas = executar(acao, entrada, estacao)
    try:
        with open(saida, "w", encoding="ascii", errors="replace", newline="\r\n") as f:
            f.write("\n".join(linhas) + "\n")
    except OSError:
        return 2
    return 0
