# =============================================================================
# test_correcoes_fase_a.py — guardas de regressão das correções da Fase A
# =============================================================================
# Roda sem banco e sem pytest:
#   .venv\Scripts\python.exe tests\test_correcoes_fase_a.py
#
# Cobre as correções que dá para verificar sem PostgreSQL:
#   02  fila offline: peek_all() não apaga; só commit() apaga
#   04  source_file: caminho relativo, não basename
#   06  _normalize_result: comparação exata (PENDING não é FAIL)
#   07  offsets.json: escrita atômica e recuperação de arquivo corrompido
#
# A correção 03 (não empilhar com o banco fora) é observada na bancada:
# com o banco offline, offline_queue.jsonl não pode crescer.
# =============================================================================

import os
import sys
import json
import shutil
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

falhas = []


def checar(condicao, descricao):
    if condicao:
        print(f"   ok    {descricao}")
    else:
        print(f"   FALHA {descricao}")
        falhas.append(descricao)


# -----------------------------------------------------------------------------
# 02 — fila offline: peek não apaga, commit apaga
# -----------------------------------------------------------------------------

def teste_fila_offline():
    print("\n02  Fila offline — peek_all() preserva, commit() apaga")

    from buffer.queue_buffer import OfflineQueue

    tmp = tempfile.mkdtemp(prefix="mes_fila_")
    try:
        q = OfflineQueue()
        q.file_path = os.path.join(tmp, "offline_queue.jsonl")

        q.push_many([{"serial": "PT001"}, {"serial": "PT002"}, {"serial": "PT003"}])
        checar(q.count() == 3, "push_many gravou 3 registros")

        pending = q.peek_all()
        checar(len(pending) == 3, "peek_all devolveu os 3 registros")
        checar(pending[0]["serial"] == "PT001", "conteudo preservado na ordem")

        # Cenário do bug: o insert falhou depois do peek. Sem commit, a fila
        # tem de continuar intacta — antes, pop_all ja' tinha apagado o arquivo
        # e esses registros sumiam para sempre.
        checar(os.path.exists(q.file_path), "arquivo AINDA existe apos peek_all (insert falhou)")
        checar(q.count() == 3, "os 3 registros continuam na fila para a proxima rodada")

        # Agora o insert deu certo
        q.commit()
        checar(not os.path.exists(q.file_path), "commit() apagou a fila")
        checar(q.count() == 0, "fila vazia depois do commit")

        # Linha corrompida no fim (queda de energia durante o append)
        q.push_many([{"serial": "PT010"}])
        with open(q.file_path, "a", encoding="utf-8") as f:
            f.write('{"serial": "PT011", "trunc')      # JSON pela metade
        recuperados = q.peek_all()
        checar(len(recuperados) == 1 and recuperados[0]["serial"] == "PT010",
               "linha corrompida e' pulada, o resto da fila e' preservado")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# -----------------------------------------------------------------------------
# 04 — source_file relativo: dois arquivos de mesmo nome não colidem
# -----------------------------------------------------------------------------

def teste_source_key():
    print("\n04  source_file — caminho relativo, nao basename")

    log_folder = os.path.join(tempfile.gettempdir(), "mes_origem")
    a17 = os.path.join(log_folder, "A17", "2026-09-09.csv")
    a16 = os.path.join(log_folder, "A16", "2026-09-09.csv")

    # Mesma expressão usada em file_monitor.py dentro do loop de arquivos
    def source_key(full_path):
        return os.path.relpath(full_path, log_folder).replace("\\", "/")

    k17, k16 = source_key(a17), source_key(a16)

    checar(os.path.basename(a17) == os.path.basename(a16),
           "os dois arquivos tem o MESMO basename (era o caso que colidia)")
    checar(k17 != k16, "as chaves de origem sao diferentes — nao colidem mais no indice unico")
    checar(k17 == "A17/2026-09-09.csv", f"chave normalizada com barra: {k17}")
    checar("\\" not in k17, "sem barra invertida — mesma chave em Windows e Linux")

    # E o monitor precisa continuar chamando isso de dentro do loop
    fm = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "monitor", "file_monitor.py")
    codigo = open(fm, encoding="utf-8").read()
    checar('"source_file":     source_key,' in codigo,
           "file_monitor grava source_key no lote (nao file_name)")


# -----------------------------------------------------------------------------
# 06 — _normalize_result por valor exato
# -----------------------------------------------------------------------------

def teste_normalize_result():
    print("\n06  _normalize_result — comparacao exata")

    from monitor.file_monitor import _normalize_result

    casos = [
        ("PASSED",  "PASS"),
        ("PASS",    "PASS"),
        ("ok",      "PASS"),
        ("  pass ", "PASS"),
        ("FAILED",  "FAIL"),
        ("NG",      "FAIL"),
        ("PENDING", "PENDING"),     # o bug: virava FAIL por conter "NG"
        ("RUNNING", "RUNNING"),
        ("TESTING", "TESTING"),
        ("WRONG",   "WRONG"),
        ("",        None),
        (None,      None),
    ]

    for entrada, esperado in casos:
        obtido = _normalize_result(entrada)
        checar(obtido == esperado, f"{entrada!r} -> {obtido!r} (esperado {esperado!r})")


# -----------------------------------------------------------------------------
# 07 — offsets.json: escrita atômica e tolerância a arquivo corrompido
# -----------------------------------------------------------------------------

def teste_offset_manager():
    print("\n07  offsets.json — escrita atomica e recuperacao")

    import config.loader as loader
    from state.offset_manager import OffsetManager

    tmp = tempfile.mkdtemp(prefix="mes_offsets_")
    original = loader.get_base_path
    try:
        loader.get_base_path = lambda: tmp

        om = OffsetManager()
        checar(os.path.exists(om.file), "offsets.json criado na primeira execucao")

        om.update(r"D:\origem\A17\2026-09-09.csv", 6037, 83, 6037)
        estado = om.get(r"D:\origem\A17\2026-09-09.csv")
        checar(estado["offset"] == 6037 and estado["line_no"] == 83,
               "estado gravado e lido de volta corretamente")

        checar(not [f for f in os.listdir(tmp) if f.endswith(".tmp")],
               "nenhum arquivo .tmp deixado para tras")

        # Arquivo corrompido: antes levantava JSONDecodeError e o monitor nao subia
        with open(om.file, "w", encoding="utf-8") as f:
            f.write('{"D:\\\\origem": {"offset": 12')      # JSON truncado
        om2 = OffsetManager()
        vazio = om2.get("qualquer.csv")
        checar(vazio == {"offset": 0, "line_no": 0, "file_size": 0},
               "offsets.json corrompido nao derruba o monitor — recomeca do zero")

        om2.update("novo.csv", 10, 1, 10)
        with open(om2.file, encoding="utf-8") as f:
            checar(json.load(f)["novo.csv"]["offset"] == 10,
                   "volta a gravar normalmente depois da recuperacao")
    finally:
        loader.get_base_path = original
        shutil.rmtree(tmp, ignore_errors=True)


# -----------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 70)
    print("Guardas de regressao — correcoes da Fase A")
    print("=" * 70)

    teste_fila_offline()
    teste_source_key()
    teste_normalize_result()
    teste_offset_manager()

    print("\n" + "=" * 70)
    if falhas:
        print(f"{len(falhas)} FALHA(S):")
        for f in falhas:
            print(f"  - {f}")
        sys.exit(1)

    print("Todas as verificacoes passaram.")
