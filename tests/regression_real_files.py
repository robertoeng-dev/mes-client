# Regressão: roda o parser (com validação) do zero sobre os CSVs reais
# listados em offsets.json e mostra quantas linhas seriam aceitas/rejeitadas.
# Não escreve nada no banco — só parse.
#   python tests\regression_real_files.py

import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parser.cyg_parser import parse_appended_rows

base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(base, "offsets.json"), "r", encoding="utf-8") as f:
    offsets = json.load(f)

for path in offsets:
    if not os.path.exists(path):
        print(f"AUSENTE  {path}")
        continue

    result = parse_appended_rows(
        path,
        {"offset": 0, "line_no": 0, "file_size": 0},
        station_type="PCM_TESTER",
    )
    rows, skipped = result["rows"], result["skipped"]
    print(f"\n{os.path.basename(path)}: {len(rows)} aceitas, {len(skipped)} rejeitadas")
    for line_no, reason in skipped[:10]:
        print(f"   linha {line_no}: {reason}")
    if len(skipped) > 10:
        print(f"   ... +{len(skipped) - 10}")
