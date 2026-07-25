"""Mutation campaign: break the code on purpose and see if the suite notices.

    python tests/harnesses/mutate.py

A mutation that SURVIVES means the behaviour changed and no test complained,
which is a gap in the suite rather than a bug in the code. That is the only
mechanical way to answer "does this test actually pin anything", which
CONTRIBUTING.md asks for and which nothing else here enforces.

Every mutation asserts it applied. A substitution that silently misses leaves
the code correct, the suite green, and reports SURVIVED - a false alarm
indistinguishable from a real gap, and exactly the failure this project is
about. NOT APPLIED is therefore reported as a harness fault, never as a result.

This found six gaps the 168-test suite could not, including two tests that a
broken implementation satisfied. It is slow by nature: one full suite run per
mutation. Expect roughly half an hour.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def build_mutations(collect: Path, detect: Path) -> list[tuple[str, Path, str, str]]:
    """(label, file, find, replace). Each must match exactly once."""
    return [
        # --- rule logic ------------------------------------------------------
        # Retargeted when ancestry moved from a per-claim merge-base call to a
        # batched rev-list. The old string named a line that no longer exists,
        # so this mutation silently stopped probing anything - reported as a
        # HARNESS FAULT rather than as a pass, which is the only reason it was
        # noticed. Mutations rot alongside the code they point at.
        ("merge-claim never fires", collect,
         "        if not merged[sha]:\n            findings.append(Finding(",
         "        if False:\n            findings.append(Finding("),
        ("batched ancestry always answers yes", collect,
         "                merged[sha] = any(full.startswith(sha)\n"
         "                                  for full in index.get(sha[:7], ()))",
         "                merged[sha] = True"),
        ("live-claim checks EVERY entry, not just the newest", collect,
         '        if kind != "phase" or newest_checked:\n            continue\n'
         "        newest_checked = True\n        if not _LIVE_PHRASES.search(entry):",
         '        if kind != "phase":\n            continue\n'
         "        if not _LIVE_PHRASES.search(entry):"),
        ("branch rule loses the merge-history rescue", collect,
         "            if _branch_exists(repo, branch) or _named_in_merge_history(repo, branch):",
         "            if _branch_exists(repo, branch):"),
        ("release-tag ancestry check dropped", collect,
         '            if not _is_merged(repo, f"refs/tags/{tag}"):',
         "            if False:"),
        ("path/branch guard removed (a file becomes a phantom branch)", collect,
         "            if _looks_like_a_path(repo, branch):\n"
         "                continue  # a file reference caught by a path-shaped pattern",
         "            if False:\n"
         "                continue  # a file reference caught by a path-shaped pattern"),
        ("path guard over-broad: skips anything containing a dot", collect,
         "    return bool(_FILEISH.search(token)) or (repo / token).exists()",
         '    return "." in token or (repo / token).exists()'),
        ("live-claim loses the path guard", collect,
         "            if _looks_like_a_path(repo, branch):\n                continue\n"
         "            exists = _branch_exists(repo, branch)",
         "            if False:\n                continue\n"
         "            exists = _branch_exists(repo, branch)"),

        # --- markdown --------------------------------------------------------
        ("external links get checked (needs the network)", collect,
         '            if _EXTERNAL.match(raw) or raw.startswith("#"):\n'
         '                continue\n            target = raw.split("#", 1)[0]',
         '            if raw.startswith("#"):\n'
         '                continue\n            target = raw.split("#", 1)[0]'),
        ("anchors compared case-sensitively", collect,
         "            fragment = raw[1:].lower()",
         "            fragment = raw[1:]"),
        ("slug keeps punctuation", collect,
         '    text = re.sub(r"[^\\w\\s-]", "", text)',
         "    text = text"),
        ("rename chains no longer followed", collect,
         "    while current in mapping:",
         "    if current in mapping:"),
        ("rename map narrowed by a pathspec again (a shipped bug)", collect,
         '        out = _git(repo, "log", "--diff-filter=R", "--name-status",\n'
         '                   "--format=", "-n", "200")',
         '        out = _git(repo, "log", "--diff-filter=R", "--name-status",\n'
         '                   "--format=", "-n", "200", "--", "nonexistent-path")'),
        ("claim rules stop ignoring fenced code", collect,
         "def _prose(text: str) -> str:",
         "def _prose(text: str) -> str:\n    return text"),
        ("case check accepts any spelling", collect,
         "    return (True, None) if actual == normalised else (False, actual)",
         "    return True, None"),

        # --- scoping / registry ----------------------------------------------
        # Indentation is written out in full rather than trimmed. A shorter
        # string is a SUBSTRING of the real line when the block moves inward,
        # so it keeps matching and silently mutates something adjacent. That
        # happened here when validate() gained a try/finally: one of these two
        # stopped matching outright and the other kept matching by accident.
        ("archive exemption ignored", collect,
         "            if (in_archive or not has_entries) and not rule.in_archive:\n"
         "                continue",
         "            if False:\n                continue"),
        ("has_entries ignored (entry rules run on extra docs)", collect,
         "            if (in_archive or not has_entries) and not rule.in_archive:\n"
         "                continue\n"
         "            findings += rule.check(repo, text)",
         "            if in_archive and not rule.in_archive:\n"
         "                continue\n"
         "            findings += rule.check(repo, text)"),

        # --- denominator ------------------------------------------------------
        ("denominator lies: dead-sha always 1", collect,
         '        "dead-sha": backticked + bare,',
         '        "dead-sha": 1,'),
        ("denominator drops a rule entirely", collect,
         '        "dead-md-anchor": sum(1 for raw in links if raw.startswith("#")),',
         ""),

        # --- selftest ---------------------------------------------------------
        ("selftest reports FIRED unconditionally", collect,
         "        if findings:\n            fired += 1",
         "        if True:\n            fired += 1"),
        ("every probe returns None", collect,
         "        probed = rule.probe(repo, text)  # type: ignore[operator]",
         "        probed = None"),

        # --- output formats ---------------------------------------------------
        ("github property escaping removed", collect,
         '        out = out.replace(":", "%3A").replace(",", "%2C")',
         "        pass"),
        ("github message escaping removed", collect,
         '    out = value.replace("%", "%25").replace("\\r", "%0D").replace("\\n", "%0A")',
         "    out = value"),
        ("sarif diagnostics leak onto stdout", collect,
         '        stream = sys.stderr if args.format == "sarif" else sys.stdout',
         "        stream = sys.stdout"),
        ("fingerprint folds in the line number", collect,
         '                "handoffClaim/v1": _fingerprint(\n'
         "                    item.path, item.finding.kind, item.finding.detail),",
         '                "handoffClaim/v1": _fingerprint(\n'
         "                    item.path, item.finding.kind,\n"
         '                    f"{item.finding.detail}:{item.finding.line}"),'),
        ("sarif drops partialFingerprints", collect,
         '            "partialFingerprints": {',
         '            "_dropped": {'),
        ("sarif region loses startLine", collect,
         '                    "region": {"startLine": max(1, item.finding.line)},',
         '                    "region": {},'),

        # --- secrets and shas --------------------------------------------------
        ("secret scan misses openai keys", collect,
         '    re.compile(r"\\bsk-[A-Za-z0-9_-]{20,}\\b"),',
         '    re.compile(r"\\bZZZNOMATCHZZZ\\b"),'),
        ("bare sha shape drops the letter requirement", collect,
         "def _looks_like_bare_sha(token: str) -> bool:",
         "def _looks_like_bare_sha(token: str) -> bool:\n"
         "    return bool(_SHA_SHAPE.match(token))"),

        # --- config errors -----------------------------------------------------
        ("every TOML error blamed on regex quoting again", collect.parent / "handoff_config.py",
         "    hint = next((h for needle, h in _HINTS if needle in text), _GENERIC_HINT)",
         "    hint = _ESCAPE_HINT"),

        # --- detect.py ----------------------------------------------------------
        ("find_documents returns only the first match", detect,
         "    return found",
         "    return found[:1]"),
        ("trunk detection ignores origin/HEAD", detect,
         '    head = _git(repo, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD").strip()',
         '    head = ""'),
    ]


def run_suite(root: Path, python: str) -> bool:
    proc = subprocess.run(
        [python, "-m", "pytest", "-x", "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return proc.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]),
                        help="package root (defaults to this checkout)")
    parser.add_argument("--python", default=sys.executable,
                        help="interpreter used to run the suite")
    args = parser.parse_args()

    root = Path(args.repo).resolve()
    skill = root / "plugin/skills/handoff"
    mutations = build_mutations(skill / "payload/handoff_collect.py", skill / "detect.py")

    backups = {path: path.read_text(encoding="utf-8")
               for _l, path, _o, _n in mutations}
    for path in backups:
        if not path.is_file():
            print(f"missing source file: {path}")
            return 1

    print("baseline: ", end="", flush=True)
    if not run_suite(root, args.python):
        print("SUITE IS ALREADY RED - aborting, every result below would be noise")
        return 1
    print("green\n")

    survived: list[str] = []
    killed: list[str] = []
    not_applied: list[str] = []
    for i, (label, path, old, new) in enumerate(mutations, 1):
        original = backups[path]
        if original.count(old) != 1:
            not_applied.append(f"{label} (matched {original.count(old)}x)")
            print(f"{i:>2}/{len(mutations)}  NOT APPLIED  {label}")
            continue
        path.write_text(original.replace(old, new, 1), encoding="utf-8", newline="\n")
        try:
            green = run_suite(root, args.python)
        finally:
            path.write_text(original, encoding="utf-8", newline="\n")
        (survived if green else killed).append(label)
        print(f"{i:>2}/{len(mutations)}  "
              f"{'SURVIVED **' if green else 'killed     '}  {label}")

    print(f"\nchecked {len(mutations)} mutations: {len(killed)} killed, "
          f"{len(survived)} SURVIVED, {len(not_applied)} not applied")
    if survived:
        print("\nTEST GAPS - behaviour changed and no test noticed:")
        for label in survived:
            print(f"  - {label}")
    if not_applied:
        print("\nHARNESS FAULTS - these prove nothing and must be repaired:")
        for label in not_applied:
            print(f"  - {label}")

    restored = all(p.read_text(encoding="utf-8") == b for p, b in backups.items())
    print(f"\nsource restored: {'clean' if restored else '** NOT RESTORED **'}")
    if not restored:
        return 2
    return 1 if (survived or not_applied) else 0


if __name__ == "__main__":
    sys.exit(main())
