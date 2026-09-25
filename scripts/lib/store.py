"""JSON-file document store: one file per US-Eastern game date per sport,
mirroring the Diamond Ledger Artifact DB's <sport>/<date> documents — but
committed to this git repo instead of living in a Claude Artifact.
"""
import glob
import json
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _dir(collection):
    return os.path.join(REPO_ROOT, "data", collection)


def _path(collection, date_str):
    return os.path.join(_dir(collection), f"{date_str}.json")


def read_doc(collection, date_str):
    path = _path(collection, date_str)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_doc(collection, date_str, data):
    os.makedirs(_dir(collection), exist_ok=True)
    with open(_path(collection, date_str), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def list_docs(collection):
    os.makedirs(_dir(collection), exist_ok=True)
    docs = []
    for path in sorted(glob.glob(os.path.join(_dir(collection), "*.json"))):
        date_str = os.path.splitext(os.path.basename(path))[0]
        with open(path, "r", encoding="utf-8") as f:
            docs.append((date_str, json.load(f)))
    return docs
