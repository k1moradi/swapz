#!/usr/bin/env python3
"""One-time user-requested branch cleanup, only after all histories reach main."""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = json.loads((ROOT / "docs/branch-consolidation-2026-10-13.json").read_text())
REPO = "k1moradi/swapz"
API = "https://api.github.com/repos/" + REPO
TOKEN = os.environ.get("GITHUB_TOKEN")
MAIN_SHA = os.environ.get("GITHUB_SHA")
if not TOKEN or not MAIN_SHA or os.environ.get("GITHUB_REF") != "refs/heads/main":
    sys.exit("BLOCKED: only a permissioned main-branch Actions push/dispatch may prune")
def api(method, path):
    req = urllib.request.Request(
        API + path, method=method, headers={
            "Authorization": "Bearer " + TOKEN,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            return json.loads(response.read()) if method == "GET" else response.status
    except urllib.error.HTTPError as e:
        raise RuntimeError("%s %s: HTTP %s: %s" %
                           (method, path, e.code, e.read().decode()[:350])) from e

expected = MANIFEST["branch_heads"]
if expected["main"] != MANIFEST["premerge_main_sha"] or len(expected) != 68:
    sys.exit("BLOCKED: manifest is inconsistent")
current_main = api("GET", "/git/ref/heads/main")["object"]["sha"]
if current_main != MAIN_SHA:
    sys.exit("BLOCKED: main advanced since current workflow revision")
actual = {}
page = 1
while True:
    batch = api("GET", "/branches?per_page=100&page=" + str(page))
    if not batch:
        break
    actual.update({b["name"]: b["commit"]["sha"] for b in batch})
    page += 1
if "main" not in actual or actual["main"] != MAIN_SHA:
    sys.exit("BLOCKED: current main ref does not match pinned Actions revision")
unexpected = sorted(set(actual) - set(expected))
moved = sorted(name for name, sha in actual.items()
               if name != "main" and expected.get(name) != sha)
if unexpected or moved:
    sys.exit("BLOCKED: unexpected branches %s, moved branch tips %s" %
             (unexpected, moved))
# The merge commit has every original HEAD in its ancestry. Check this
# for all 67 refs BEFORE issuing the first destructive operation.
for name, sha in sorted(expected.items()):
    if name == "main":
        if subprocess.run(["git", "merge-base", "--is-ancestor", sha, MAIN_SHA],
                          check=False).returncode:
            sys.exit("BLOCKED: original main is not ancestor")
    else:
        if subprocess.run(["git", "merge-base", "--is-ancestor", sha, MAIN_SHA],
                          check=False).returncode:
            sys.exit("BLOCKED: branch history not preserved: " + name)
print("PRECHECK PASS: %d historical branch heads preserved in main" % len(expected),
      flush=True)
errors = []
for name in sorted(actual):
    if name == "main":
        continue
    # Reverify identity immediately before deletion. An external push
    # between the original snapshot and deletion must never be discarded.
    encoded = urllib.parse.quote(name, safe="/")
    try:
        now = api("GET", "/git/ref/heads/" + encoded)["object"]["sha"]
        if now != expected[name]:
            raise RuntimeError("branch tip moved before delete")
        status = api("DELETE", "/git/refs/heads/" + encoded)
        if status != 204:
            raise RuntimeError("unexpected delete status: " + str(status))
        print("DELETED", name, expected[name], flush=True)
    except Exception as exc:
        errors.append((name, str(exc)))
        print("PRESERVED / ERROR", name, str(exc), flush=True)
remaining = {}
page = 1
while True:
    batch = api("GET", "/branches?per_page=100&page=" + str(page))
    if not batch:
        break
    remaining.update({b["name"]: b["commit"]["sha"] for b in batch})
    page += 1
print("FINAL BRANCH COUNT:", len(remaining), "remaining:", sorted(remaining), flush=True)
if errors or set(remaining) != {"main"}:
    sys.exit("INCOMPLETE: some refs remain or could not be safely deleted: " + str(errors))
print("SUCCESS: only main remains; no force deletion and no history loss", flush=True)
