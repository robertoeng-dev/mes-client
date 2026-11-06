# =============================================================================
# test_compat_py38.py — o mesmo resultado no Python 3.13 (Win10) e no 3.8 (Win7)
#
# Roda nas duas edições:
#   Win10:  .venv\Scripts\python.exe tests\test_compat_py38.py
#   Win7:   .venv38\Scripts\python.exe tests\test_compat_py38.py   (pacote csvparser)
#
# Cobre o que o Python 3.8 faz diferente e o código comum já trata:
#   - datas ISO 8601 que o fromisoformat do 3.8 recusa (Z, fração curta, compacto)
#   - byte NUL no meio do CSV (o csv do 3.8 aborta o arquivo inteiro)
# =============================================================================
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:                                    # edição Win7: o pacote se chama csvparser
    from csvparser import configuravel
    from csvparser.campos import _parse_test_time
    from csvparser.cyg_parser import parse_appended_rows as cyg_parse
except ImportError:
    from parser import configuravel
    from parser.campos import _parse_test_time
    from parser.cyg_parser import parse_appended_rows as cyg_parse


def caso_datas():
    iso = configuravel.iso_flexivel
    assert iso("2026-09-11T08:15:30") == datetime(2026, 9, 11, 8, 15, 30)
    assert iso("2026-09-11 08:15:30.5") == datetime(2026, 9, 11, 8, 15, 30, 500000)
    assert iso("2026-09-11T08:15:30.123") == datetime(2026, 9, 11, 8, 15, 30, 123000)
    assert iso("2026-09-11T08:15:30Z") == datetime(2026, 9, 11, 8, 15, 30, tzinfo=timezone.utc)
    assert iso("2026-09-11T08:15:30.25-04:00") == datetime(2026, 9, 11, 8, 15, 30, 250000,
                                                           tzinfo=timezone(timedelta(hours=-4)))
    assert iso("20260911T081530") == datetime(2026, 9, 11, 8, 15, 30)
    assert iso("11/09/2026 08:15") is None
    assert iso("lixo") is None
    # formato do P2500S e ISO pelo caminho usado nos parsers
    assert _parse_test_time("20260911081530") == datetime(2026, 9, 11, 8, 15, 30)
    assert _parse_test_time("2026-09-11T08:15:30.5") == datetime(2026, 9, 11, 8, 15, 30, 500000)
    assert _parse_test_time("31/31/2026") is None
    assert configuravel.converter_data("2026-09-11T08:15:30Z") == "2026-09-11 08:15:30"
    assert configuravel.converter_data("11/09/2026 08:15:30", "%d/%m/%Y %H:%M:%S") == "2026-09-11 08:15:30"
    print("OK  datas ISO 8601 (Z, fração curta, compacto) iguais nas duas versões")


def caso_nul_configuravel():
    definicao = {"delimitador": ",", "encoding": "utf-8", "linha_cabecalho": 1, "linha_dados": 2,
                 "max_min": "nenhum", "formato_data": "%Y%m%d%H%M%S",
                 "campos": {"serial_number": "SN", "result_status": "RES", "test_start_time": "TIME"}}
    conteudo = ("SN,RES,TIME,V1,V2\n"
                "S001,PASS,20260911081530,3.7,1.2\n"
                "S\x00\x00\x00,\x00\x00,\x00,\x00,\x00\n"          # linha com lixo binário
                "S002,FAIL,20260911081531,3.6,1.1\n")
    fd, caminho = tempfile.mkstemp(suffix=".csv")
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
        f.write(conteudo)
    try:
        r = configuravel.parse_appended_rows(caminho, {}, definicao)
        seriais = [row["SN"] for row in r["rows"]]
        assert seriais == ["S001", "S002"], seriais
        assert [m for _, m in r["skipped"]] == ["garbage_chars"], r["skipped"]
    finally:
        os.remove(caminho)
    print("OK  NUL no CSV (formato configurável): arquivo lido, linha suja rejeitada como garbage_chars")


def caso_nul_cyg():
    conteudo = ("Station,PN,barcode,test_result,proj_code,test_time,R1,R2,OV,UV\n"
                "USL,,,,,,10,50,4.6,2.7\n"
                "LSL,,,,,,1,5,4.0,2.0\n"
                "units,,,,,,ohm,ohm,V,V\n"
                "1A,PN1,C001,PASS,A08,2026-09-11 08:15:30,5,20,4.3,2.5\n"
                "1A,PN1,\x00\x00\x00,\x00,A08,\x00,5,20,4.3,2.5\n"
                "1A,PN1,C002,FAIL,A08,2026-09-11 08:15:31,5,20,4.3,2.5\n")
    fd, caminho = tempfile.mkstemp(suffix=".csv")
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
        f.write(conteudo)
    try:
        r = cyg_parse(caminho, {"offset": 0, "line_no": 0, "file_size": 0}, station_type="CYG")
        barcodes = [row.get("barcode") for row in r["rows"]]
        assert barcodes == ["C001", "C002"], barcodes
    finally:
        os.remove(caminho)
    print("OK  NUL no CSV (parser dedicado): arquivo lido, linha suja rejeitada")


if __name__ == "__main__":
    print("Python", sys.version.split()[0])
    caso_datas()
    caso_nul_configuravel()
    caso_nul_cyg()
    print("\nTodos os testes passaram.")
