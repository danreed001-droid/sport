#!/usr/bin/env python3
"""Syntax-checks the inline JavaScript of every built page (run by
.github/workflows/pages.yml after build_site.py, before deploying). A broken
script blanks the pick sheet, so a failure here stops the deploy and the
last good site stays live. Needs node (on GitHub's runners); skips with a
warning without it.

Usage: python scripts/check_site_js.py [site_dir]   (default: _site)
"""
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile


def main():
    site = sys.argv[1] if len(sys.argv) > 1 else "_site"
    if not shutil.which("node"):
        print("::warning::node not found; skipping the JavaScript syntax check")
        return
    bad = 0
    for page in sorted(glob.glob(os.path.join(site, "*.html"))):
        with open(page, encoding="utf-8") as f:
            scripts = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", f.read(), re.S)
        code = "\n;\n".join(s for s in scripts if s.strip())
        if not code:
            continue
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as tmp:
            tmp.write(code)
        r = subprocess.run(["node", "--check", tmp.name], capture_output=True, text=True)
        os.unlink(tmp.name)
        if r.returncode:
            bad += 1
            print(f"::error file={page}::JavaScript syntax error in {os.path.basename(page)}:\n{r.stderr.strip()}")
        else:
            print(f"{os.path.basename(page)}: JavaScript OK")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
