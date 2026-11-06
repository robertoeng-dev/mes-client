# Auxiliar do test_paridade.py — roda o pipeline do cliente v1.0.5 (cópia do
# backup, passada como argumento) e imprime o resultado em JSON.
# NÃO rodar direto: o test_paridade.py chama em subprocesso.
#   python _paridade_v105.py <pasta_v105> <station_type> <modelo_config> <arquivo>...
import json
import os
import sys

src = sys.argv[1]
sys.path.insert(0, src)
os.chdir(src)

from config.column_mapper import load_mappings, resolve_field          # noqa: E402
from parser.cyg_parser import parse_appended_rows, detect_model_from_filename  # noqa: E402
import monitor.file_monitor as fm                                        # noqa: E402

station_type, config_model = sys.argv[2], sys.argv[3]
mappings = load_mappings()
saida = {}
for caminho in sys.argv[4:]:
    p = parse_appended_rows(caminho, {"offset": 0, "line_no": 0, "file_size": 0}, station_type)
    rows = p["rows"]
    fmod, fver = detect_model_from_filename(caminho)
    model = fm._resolve_model_name(fmod, config_model, rows, mappings) if rows else None
    version = fm._resolve_version_name(fver, rows) if rows else None
    lote = []
    for row in rows:
        serial = (fm._pcm_serial(row) if station_type == "PCM_TESTER"
                  else resolve_field("serial_number", row, model, mappings))
        ini = fm._parse_test_time(resolve_field("test_start_time", row, model, mappings))
        fim = fm._parse_test_time(resolve_field("test_stop_time", row, model, mappings))
        lote.append({
            "model_name": model, "version_name": version, "serial_number": serial,
            "result_status": fm._normalize_result(resolve_field("result_status", row, model, mappings)),
            "test_start_time": ini.isoformat(sep=" ") if ini else None,
            "test_stop_time": fim.isoformat(sep=" ") if fim else None,
            "source_line_no": row["_line_no"], "schema_hash": fm._schema_hash(p["schema"]["headers"]),
            "row_data": row,
        })
    saida[os.path.basename(caminho)] = {
        "lote": lote, "skipped": p["skipped"], "new_offset": p["new_offset"],
        "new_line_no": p["new_line_no"], "format": p["schema"]["format"],
        "upper": p["schema"]["upper_map"], "lower": p["schema"]["lower_map"],
    }
json.dump(saida, sys.stdout)
