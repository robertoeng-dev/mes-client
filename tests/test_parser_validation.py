# =============================================================================
# test_parser_validation.py — teste standalone da validação de linhas
# =============================================================================
# Roda sem banco e sem pytest:
#   python tests\test_parser_validation.py
#
# Verifica que parse_appended_rows rejeita cabeçalho repetido, linha
# truncada, lixo binário e excesso de colunas, mantendo _line_no alinhado
# com o arquivo físico e o offset avançando até o fim do arquivo.
# =============================================================================

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parser.cyg_parser import parse_appended_rows

HEADER = "Station,PN,barcode,test_result,proj_code,test_time,R1,R2,OV,UV\n"
USL    = "USL,,,,,,10,50,4.6,2.7\n"
LSL    = "LSL,,,,,,9,45,4.4,2.2\n"
UNITS  = "units,,,,,,ohm,ohm,V,V\n"


def good_row(barcode):
    return f"ST01,A06,{barcode},PASSED,A06,2026-05-02 10:00:00,9.8,47.0,4.53,2.60\n"


def initial_state():
    return {"offset": 0, "line_no": 0, "file_size": 0}


def run_cyg_case():
    path = os.path.join(tempfile.gettempdir(), "test_cyg_validation.csv")

    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(HEADER + USL + LSL + UNITS)          # metadados (formato CYG)
        f.write(good_row("PT001"))                   # linha de dados 1 — boa
        f.write(good_row("PT002"))                   # linha 2 — boa
        f.write(good_row("PT003"))                   # linha 3 — boa
        f.write(HEADER)                              # linha 4 — header repetido
        f.write("x,y\n")                             # linha 5 — truncada (2 campos)

    # linha 6 — lixo binário COM vírgulas (passa no check de nº de campos,
    # cai no check de garbage_chars via U+FFFD de errors='replace')
    with open(path, "ab") as f:
        f.write(b"\x93\xfa\x81,ab\xff\xfe,zz\xfa\xff,ok\x81\x9d,ok\n")

    with open(path, "a", encoding="utf-8", newline="") as f:
        f.write(good_row("PT004"))                   # linha 7 — boa
        f.write(good_row("PT005").rstrip("\n") + ",extra1,extra2,extra3\n")  # linha 8 — colunas a mais

    result = parse_appended_rows(path, initial_state(), station_type="CYG")

    line_nos = [r["_line_no"] for r in result["rows"]]
    assert line_nos == [1, 2, 3, 7], f"esperado [1, 2, 3, 7], veio {line_nos}"

    skipped = dict(result["skipped"])
    assert skipped == {
        4: "header_repeat",
        5: "too_few_fields",
        6: "garbage_chars",
        8: "extra_columns",
    }, f"skipped inesperado: {result['skipped']}"

    assert result["new_offset"] == os.path.getsize(path), \
        "offset deve avançar até o fim do arquivo mesmo com linhas rejeitadas"

    # --- caso incremental: append 1 boa + 1 lixo, continua do estado salvo ---
    with open(path, "a", encoding="utf-8", newline="") as f:
        f.write(good_row("PT006"))                   # linha 9 — boa
    with open(path, "ab") as f:
        f.write(b"\x00\x01\x02\xff\xfe\xfd\n")       # linha 10 — lixo sem vírgulas

    state2 = {
        "offset":    result["new_offset"],
        "line_no":   result["new_line_no"],
        "file_size": result["file_size"],
    }
    result2 = parse_appended_rows(path, state2, station_type="CYG")

    line_nos2 = [r["_line_no"] for r in result2["rows"]]
    assert line_nos2 == [9], f"esperado [9], veio {line_nos2}"
    assert len(result2["skipped"]) == 1 and result2["skipped"][0][0] == 10, \
        f"esperado linha 10 rejeitada, veio {result2['skipped']}"
    assert result2["new_offset"] == os.path.getsize(path)

    os.remove(path)
    print("OK  formato CYG: 4 boas, 4 rejeitadas (motivos corretos), incremental OK")


def run_pcm_case():
    path = os.path.join(tempfile.gettempdir(), "test_pcm_validation.csv")

    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(HEADER)
        f.write("Estacao,Material,Codigo,Resultado[0-1],Projeto,Hora,R1(ohm)[9-10],R2(ohm)[45-50],OV(V)[4.4-4.6],UV(V)[2.2-2.7]\n")
        f.write(good_row("PT101"))                   # linha de dados 1 — boa
    with open(path, "ab") as f:
        f.write(b"\x93\xfa\x81,ab\xff\xfe,zz\xfa\xff,ok\x81\x9d,ok\n")  # linha 2 — lixo

    result = parse_appended_rows(path, initial_state(), station_type="PCM_TESTER")

    line_nos = [r["_line_no"] for r in result["rows"]]
    assert line_nos == [1], f"esperado [1], veio {line_nos}"
    assert result["skipped"] == [(2, "garbage_chars")], \
        f"skipped inesperado: {result['skipped']}"

    os.remove(path)
    print("OK  formato PCM_TESTER: 1 boa, 1 rejeitada")


if __name__ == "__main__":
    run_cyg_case()
    run_pcm_case()
    print("\nTodos os testes passaram.")
