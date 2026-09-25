"""Reproduce bounded audit counterexamples using the archived pinned source."""
from dataclasses import asdict
import json
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import argparse
import subprocess

HERE = Path(__file__).resolve().parent
arguments = argparse.ArgumentParser(description=__doc__)
arguments.add_argument("--source-checkout", type=Path, required=True)
source_checkout = arguments.parse_args().source_checkout
pin = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source_checkout, text=True).strip()
assert pin == "4f5bbf561208e436f488b086ebf34924cd435530", pin
for package in ("lovdata-loader", "lovdata-publisher"):
    sys.path.insert(0, str(source_checkout / package / "src"))

from bs4 import BeautifulSoup
from lovdata_loader.coverage import law_coverage
from lovdata_loader.parser import parse_amendment, parse_effective_date, parse_section
from lovdata_publisher.formatter import format_section
from lovdata_publisher.manifests import generate_amendments_jsonl

source = (HERE / "mixed-section-source.xml").read_bytes()
section = asdict(parse_section(BeautifulSoup(source, "html.parser").section))
rendered = format_section(section)
change = BeautifulSoup('<article class="change" data-repeal-part="forskrift/2020-01-01-1/§1"><article class="defaultP">§1 oppheves</article></article>', "html.parser").article
with tempfile.TemporaryDirectory(prefix="history-audit-probe-") as temporary:
    db = Path(temporary) / "projection.db"
    with sqlite3.connect(db) as connection:
        connection.execute("CREATE TABLE amendment_acts (refid TEXT,title TEXT,short_title TEXT,ministry TEXT,date_published TEXT,date_in_force TEXT,date_in_force_resolved TEXT,journal_number TEXT)")
        connection.execute("CREATE TABLE amendments (id INTEGER,act_refid TEXT,change_type TEXT,target TEXT,target_law TEXT,instruction TEXT,new_text TEXT)")
        connection.execute("INSERT INTO amendment_acts VALUES (?,?,?,?,?,?,?,?)", ("act/1", "Title", "", "", "2024-05-06", "Kongen bestemmer", "2024-05-06", ""))
        connection.executemany("INSERT INTO amendments VALUES (?,?,?,?,?,?,?)", [(1,"act/1","change","§1","lov/2020-01-01-1","I"*301,"N"*5001),(2,"act/1","unknown","","","unresolved","")])
    connection.close()
    out = Path(temporary) / "display.jsonl"
    count = generate_amendments_jsonl(str(db), str(out))
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
result = {
    "source_commit": "4f5bbf561208e436f488b086ebf34924cd435530",
    "mixed_section": {"source_order": re.findall(r"ALPHA|BRAVO|CHARLIE", source.decode()), "rendered_order": re.findall(r"ALPHA|BRAVO|CHARLIE", rendered), "bag_of_tokens_coverage": law_coverage(source, {"sections":[section]})["coverage"]},
    "deferred_commencement": list(parse_effective_date("Kongen bestemmer", "2024-05-06")),
    "unknown_commencement": list(parse_effective_date("ukjent", "2024-05-06")),
    "structured_regulation_repeal_target": parse_amendment(change).target_law,
    "display_projection": {"input_amendments":2,"output_amendments":count,"instruction_original":301,"instruction_exported":len(rows[0]["instruction"]),"new_text_original":5001,"new_text_exported":len(rows[0]["new_text"])},
}
expected = json.loads((HERE / "pinned-probes.json").read_text(encoding="utf-8"))
assert result == expected, (result, expected)
print(json.dumps(result, ensure_ascii=False, indent=2))
