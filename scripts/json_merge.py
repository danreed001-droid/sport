#!/usr/bin/env python3
"""Git merge driver for the data files: a field-by-field three-way JSON merge.

The scoring and game-time workflows rebase their commit onto main before
pushing. When another change touched the same file (a hand fix, the sync
Routine, the other workflow), a line-level merge of a slate -- where a whole
game can sit on one line -- used to keep this run's whole line and silently
undo the other change (2026-11-14: a scoring run put back two MLB days that
had just been fixed by hand). This merges the JSON itself instead:

  - a field only one side changed keeps that side's value;
  - a field both sides changed to different values takes this run's (the
    commit being rebased, %B) -- what the line merge did, but per field;
  - lists of games/entries are matched by identity (away/home/time, id, key,
    rule, ...), so a game added on one side is kept.

Registered in .gitattributes (data/**/*.json merge=jsonmerge) and enabled by
the workflows with
  git config merge.jsonmerge.driver "python scripts/json_merge.py %O %A %B"
Without that config git ignores the attribute and merges text as before.
Usage: json_merge.py BASE OURS THEIRS -- writes the result to OURS; exit 0 when
merged, 1 to leave the conflict to git (a side that isn't valid JSON).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MISSING = object()
ID_KEYS = ("id", "espnId", "game_id", "gid", "key", "rule", "n")


def identity(x):
    if not isinstance(x, dict):
        return None
    if "away" in x and "home" in x:
        return ("game", x.get("away"), x.get("home"), x.get("time"))
    for k in ID_KEYS:
        if k in x:
            return (k, json.dumps(x[k], sort_keys=True), json.dumps(x.get("team"), sort_keys=True))
    return None


def merge(o, a, b):
    if a == b:
        return a
    if o == a:
        return b
    if o == b:
        return a
    if isinstance(a, dict) and isinstance(b, dict):
        o = o if isinstance(o, dict) else {}
        out = {}
        for k in list(a) + [k for k in b if k not in a]:
            v = merge(o.get(k, MISSING), a.get(k, MISSING), b.get(k, MISSING))
            if v is not MISSING:
                out[k] = v
        return out
    if isinstance(a, list) and isinstance(b, list):
        ids_a, ids_b = [identity(x) for x in a], [identity(x) for x in b]
        if None not in ids_a + ids_b and len(set(ids_a)) == len(a) and len(set(ids_b)) == len(b):
            o_list = o if isinstance(o, list) else []
            ids_o = {identity(x): x for x in o_list} if all(identity(x) is not None for x in o_list) else {}
            by_b = dict(zip(ids_b, b))
            out = []
            for i, x in zip(ids_a, a):
                if i in by_b:
                    v = merge(ids_o.get(i, MISSING), x, by_b[i])
                elif i in ids_o and ids_o[i] == x:
                    v = MISSING          # this run removed it and the other side didn't touch it
                else:
                    v = x
                if v is not MISSING:
                    out.append(v)
            for i, x in zip(ids_b, b):
                if i not in set(ids_a) and not (i in ids_o and ids_o[i] == x):
                    out.append(x)        # added by this run (or removed by the other side but changed here)
            return out
        if isinstance(o, list) and len(o) == len(a) == len(b):
            return [merge(x, y, z) for x, y, z in zip(o, a, b)]
    return b  # both changed it: this run's value, as before


def render_like(text, data):
    """Write data in the same layout as the file it replaces."""
    if '\n  "games": [\n    {"' in text:
        from sync_ledger import render
        return render(data)
    lines = text.splitlines()
    indent = None
    if len(lines) > 1:
        stripped = lines[1].lstrip(" ")
        indent = len(lines[1]) - len(stripped) or None
    ascii_only = all(ord(c) < 128 for c in text)
    sort_keys = list(data) == sorted(data) if isinstance(data, dict) else False
    if indent is None:
        out = json.dumps(data, separators=(",", ":"), ensure_ascii=ascii_only, sort_keys=sort_keys)
    else:
        out = json.dumps(data, indent=indent, ensure_ascii=ascii_only, sort_keys=sort_keys)
    return out + ("\n" if text.endswith("\n") else "")


def main():
    base_p, ours_p, theirs_p = sys.argv[1:4]
    texts = []
    for p in (base_p, ours_p, theirs_p):
        try:
            with open(p, encoding="utf-8") as f:
                texts.append(f.read())
        except OSError:
            texts.append("")
    try:
        base = json.loads(texts[0]) if texts[0].strip() else MISSING
        ours, theirs = json.loads(texts[1]), json.loads(texts[2])
    except ValueError:
        return 1
    merged = merge(base, ours, theirs)
    with open(ours_p, "w", encoding="utf-8") as f:
        f.write(render_like(texts[1] or texts[2], merged))
    return 0


if __name__ == "__main__":
    sys.exit(main())
