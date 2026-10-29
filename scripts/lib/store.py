"""JSON-file document store: one file per US-Eastern game date per sport,
mirroring the Diamond Ledger Artifact DB's <sport>/<date> documents — but
committed to this git repo instead of living in a Claude Artifact.
"""
import glob
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _dir(collection):
    return os.path.join(REPO_ROOT, "data", collection)


def _path(collection, date_str):
    return os.path.join(_dir(collection), f"{date_str}.json")


def read_doc(collection, date_str):
    path = _path(collection, date_str)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        # A half-written or hand-broken file shouldn't take every script down
        # with it; treat it as missing and say so in the run log.
        print(f"WARNING: skipping unreadable {path}: {e}", file=sys.stderr)
        return None


def write_doc(collection, date_str, data):
    os.makedirs(_dir(collection), exist_ok=True)
    path = _path(collection, date_str)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)  # atomic: a killed run never leaves half a file


def list_docs(collection):
    os.makedirs(_dir(collection), exist_ok=True)
    docs = []
    for path in sorted(glob.glob(os.path.join(_dir(collection), "*.json"))):
        date_str = os.path.splitext(os.path.basename(path))[0]
        try:
            with open(path, "r", encoding="utf-8") as f:
                docs.append((date_str, json.load(f)))
        except (OSError, ValueError) as e:
            print(f"WARNING: skipping unreadable {path}: {e}", file=sys.stderr)
    return docs
