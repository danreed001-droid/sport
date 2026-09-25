#!/usr/bin/env python3
"""Builds the Diamond Ledger HTML report.

Reads real scored data from data/<sport>/*.json and renders it into
scripts/report/template.html. With --demo, reads the bundled sample dataset
(scripts/demo/demo_data.json) instead — the two paths never mix, so a demo
run can never be mistaken for real results.

Usage:
  python scripts/build_report.py [--demo] [--out report.html]
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from lib import sports, store, report  # noqa: E402

REPORT_DIR = os.path.join(os.path.dirname(__file__), "report")
TEMPLATE_PATH = os.path.join(REPORT_DIR, "template.html")
DEMO_DATA_PATH = os.path.join(os.path.dirname(__file__), "demo", "demo_data.json")
DEFAULT_OUT = os.path.join(os.path.dirname(__file__), "..", "report.html")


def build_real_payload():
    leagues = {}
    for sport_key, cfg in sports.SPORTS.items():
        docs = store.list_docs(cfg["collection"])
        games = []
        for date_str, doc in docs:
            if not doc.get("scored"):
                continue
            for g in doc.get("games", []):
                g = dict(g)
                g["date"] = date_str
                games.append(g)
        leagues[sport_key] = report.html_payload(cfg["label"], cfg["kind"], games)
    return {"generatedAt": "REAL", "leagues": leagues}


def main():
    demo = "--demo" in sys.argv
    out_path = DEFAULT_OUT
    if "--out" in sys.argv:
        out_path = sys.argv[sys.argv.index("--out") + 1]

    if demo:
        with open(DEMO_DATA_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)
    else:
        payload = build_real_payload()
        empty = all(not lg["games"] for lg in payload["leagues"].values())
        if empty:
            print("No scored games in data/ yet — the report will render with empty leagues.")
            print("Run with --demo to preview the design with sample data instead.")

    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        template = f.read()

    data_json = json.dumps(payload, separators=(",", ":")).replace("</script", "<\\/script")
    assert template.count("__LEDGER_DATA_JSON__") == 1
    html = template.replace("__LEDGER_DATA_JSON__", data_json)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Wrote {out_path} ({'demo' if demo else 'real'} data, {len(payload['leagues'])} leagues).")


if __name__ == "__main__":
    main()
