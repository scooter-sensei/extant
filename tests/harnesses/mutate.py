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
        # Retargeted a second time when claims became self-describing and the
        # ancestry map became keyed by (ref, sha) rather than by sha alone.
        ("merge-claim never fires", collect,
         "        if not merged[key]:\n            findings.append(Finding(",
         "        if False:\n            findings.append(Finding("),
        # Retargeted when ancestry became per-ref: the index is keyed by
        # (repo, ref) now and the prefix lookup moved into _reachable_from.
        ("batched ancestry always answers yes", collect,
         "        return any(full.startswith(rev) for full in index.get(rev[:7], ()))",
         "        return True"),
        # The three rules that used to ask about trunk now ask about the
        # measured integration set, so its two failure directions each get a
        # mutation: naming nothing makes them blind, naming everything makes
        # them permissive.
        ("integration refs collapse to the configured trunk alone", collect,
         "    present = set(out.split())",
         "    present = set()"),
        ("any branch counts as an integration branch", collect,
         "    for name in _INTEGRATION_NAMES:\n"
         "        if name in present and name not in refs:\n"
         "            refs.append(name)",
         "    for name in sorted(present):\n"
         "        if name not in refs:\n"
         "            refs.append(name)"),
        ("merge claims stop checking the ref the claim names", collect,
         "            merged[key] = _reachable_from(repo, sha, ref)",
         "            merged[key] = _reachable_from(repo, sha, TRUNK)"),
        ("a bare word after the merge verb is treated as a branch", collect,
         "            if not quoted:\n"
         "                continue        # a bare word, likelier prose than a ref",
         "            if False:\n"
         "                continue        # a bare word, likelier prose than a ref"),
        ("the ancestry cache stops distinguishing repositories", collect,
         "    key = (str(repo), ref)\n    if key in _ANCESTORS:",
         '    key = ("", ref)\n    if key in _ANCESTORS:'),
        ("a branch counts as merged into itself", collect,
         "    return [ref for ref in _integration_refs(repo)\n"
         "            if ref != exclude and _reachable_from(repo, rev, ref)]",
         "    return [ref for ref in _integration_refs(repo)\n"
         "            if _reachable_from(repo, rev, ref)]"),
        # The installer writes its own merge_claim, which OVERRIDES the default,
        # so a collector that supports named refs still ships single-trunk
        # behaviour if this line regresses. That is exactly what happened.
        ("the installer emits a single-trunk merge_claim again",
         detect.parent / "install.py",
         'rf"(?:{alt})\\s+(?:to|into|in|on)\\s+(`[^`\\n]+`|[\\w.\\-/]+)"',
         'rf"(?:{alt})\\s+(?:to|into|in|on)\\s+`?{{trunk}}`?"'),
        ("live-claim checks EVERY entry, not just the newest", collect,
         '        if kind != "phase" or newest_checked:\n            continue\n'
         "        newest_checked = True\n        if not _LIVE_PHRASES.search(entry):",
         '        if kind != "phase":\n            continue\n'
         "        if not _LIVE_PHRASES.search(entry):"),
        ("branch rule loses the merge-history rescue", collect,
         "            if _branch_exists(repo, branch) or _named_in_merge_history(repo, branch):",
         "            if _branch_exists(repo, branch):"),
        # Retargeted when the tag rule stopped asking about trunk and started
        # asking whether the tag is on ANY integration branch.
        ("release-tag ancestry check dropped", collect,
         '            if not _integrated_by(repo, f"refs/tags/{tag}"):',
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
        # Retargeted when dead-md-anchor grew to check fragments on OTHER
        # files: the fragment is now split off with partition rather than
        # sliced, and slugging moved behind _heading_text.
        ("anchors compared case-sensitively", collect,
         "            fragment = fragment.lower()",
         "            fragment = fragment"),
        ("slug keeps punctuation", collect,
         '    text = re.sub(r"[^\\w\\s-]", "", _heading_text(title))',
         "    text = _heading_text(title)"),
        ("cross-file anchors no longer checked", collect,
         "            offered = _target_anchors(resolved)",
         "            offered = None"),
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
        # Anchored on the CONDITION alone. It used to include the dispatch line
        # that followed, and the rst work inserted a format check between the
        # two, so the pair stopped matching while the behaviour it probes was
        # untouched. A mutation should name the smallest thing it is about.
        ("has_entries ignored (entry rules run on extra docs)", collect,
         "            if (in_archive or not has_entries) and not rule.in_archive:\n"
         "                continue\n",
         "            if in_archive and not rule.in_archive:\n"
         "                continue\n"),

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
        # Retargeted when --suggest-fixes made stdout a patch channel too, so
        # the condition gained a second clause. Caught by --check-only at the
        # commit that moved it, which is the whole reason that mode exists.
        ("sarif diagnostics leak onto stdout", collect,
         '        stream = (sys.stderr if (args.format == "sarif" or args.suggest_fixes)\n'
         "                  else sys.stdout)",
         "        stream = sys.stdout"),
        ("suggested patch shares stdout with the findings", collect,
         '        stream = (sys.stderr if (args.format == "sarif" or args.suggest_fixes)',
         '        stream = (sys.stderr if (args.format == "sarif" or False)'),
        ("fingerprint folds in the line number", collect,
         '                "statusClaim/v1": _fingerprint(\n'
         "                    item.path, item.finding.kind, item.finding.detail),",
         '                "statusClaim/v1": _fingerprint(\n'
         "                    item.path, item.finding.kind,\n"
         '                    f"{item.finding.detail}:{item.finding.line}"),'),
        ("sarif drops partialFingerprints", collect,
         '            "partialFingerprints": {',
         '            "_dropped": {'),
        ("sarif region loses startLine", collect,
         '                    "region": {"startLine": max(1, item.finding.line)},',
         '                    "region": {},'),

        # --- shas ----------------------------------------------------------
        # "secret scan misses openai keys" lived here until 0.14.0 removed the
        # rule. Deleted rather than retargeted: there is no code left for it to
        # name, and a mutation kept alive by pointing it at something else
        # would be testing a different thing under an old label.
        ("bare sha shape drops the letter requirement", collect,
         "def _looks_like_bare_sha(token: str) -> bool:",
         "def _looks_like_bare_sha(token: str) -> bool:\n"
         "    return bool(_SHA_SHAPE.match(token))"),

        # --- config errors -----------------------------------------------------
        ("every TOML error blamed on regex quoting again", collect.parent / "extant_config.py",
         "    hint = next((h for needle, h in _HINTS if needle in text), _GENERIC_HINT)",
         "    hint = _ESCAPE_HINT"),

        # --- consistency (repository-scoped) -------------------------------------
        ("consistency never reports a disagreement", collect,
         "        if len(seen) > 1:",
         "        if False:"),
        ("consistency reports agreement AS disagreement", collect,
         "        if len(seen) > 1:",
         "        if len(seen) >= 1:"),
        ("consistency ignores a missing file", collect,
         "            if not target.is_file():\n"
         "                findings.append(Finding(\n"
         "                    1, \"inconsistent-artifact\",\n"
         "                    f\"consistency check `{name}` reads `{relative}`, \"\n"
         "                    f\"which does not exist\",\n"
         "                ))\n"
         "                continue",
         "            if not target.is_file():\n                continue"),
        ("consistency ignores a pattern that matches nothing", collect,
         "            if match is None:",
         "            if False and match is None:"),
        ("consistency reads the INSTALLED config, not the target repo's", collect,
         "        consistency = _consistency_for(repo)",
         "        consistency = CONFIG.consistency"),

        # --- search --------------------------------------------------------------
        ("search only looks at the live document", collect,
         "    for relative in (PRIMARY_DOC, ARCHIVE_DOC):\n"
         "        path = repo / relative\n"
         "        if not path.is_file():\n"
         "            continue\n"
         "        with open(path, encoding=\"utf-8\", newline=\"\") as fh:",
         "    for relative in (PRIMARY_DOC,):\n"
         "        path = repo / relative\n"
         "        if not path.is_file():\n"
         "            continue\n"
         "        with open(path, encoding=\"utf-8\", newline=\"\") as fh:"),
        ("search becomes case-sensitive", collect,
         "    needle = query.lower()",
         "    needle = query"),
        ("search matches every entry regardless of content", collect,
         '            if kind != "phase" or needle not in entry.lower():',
         '            if kind != "phase":'),

        # --- suggested fixes ------------------------------------------------------
        ("suggest-fixes offers a guess for a merely missing file", collect,
         "        moved = _renamed_to(repo, target)\n"
         "        if moved:\n"
         "            replacements.append((target, moved))",
         "        moved = _renamed_to(repo, target) or target + \".guess\"\n"
         "        if moved:\n"
         "            replacements.append((target, moved))"),
        ("suggest-fixes rewrites prose as well as references", collect,
         '        updated = updated.replace(f"]({old})", f"]({new})")\n'
         '        updated = updated.replace(f"`{old}`", f"`{new}`")',
         "        updated = updated.replace(old, new)"),
        ("suggest-fixes writes the file instead of emitting a patch", collect,
         "    if not replacements:\n        return \"\"",
         "    if not replacements:\n        return \"\"\n"
         "    (base / 'SIDE_EFFECT.txt').write_text('written', encoding='utf-8')"),

        # --- config discovery -----------------------------------------------------
        ("config is no longer searched for upward", detect.parent / "payload/extant_config.py",
         "    for directory in (current, *current.parents):",
         "    for directory in (current,):"),
        ("config search runs past the repository root", detect.parent / "payload/extant_config.py",
         '        if (directory / ".git").exists():\n            return None',
         '        if False:\n            return None'),
        # The 3.9/3.10 fallback. Both mutations are invisible on a modern
        # interpreter, which is the whole difficulty: the tests block the module
        # at import in a subprocess, so they fail here and would not otherwise.
        ("no parser is a hard import error again, not a fallback",
         detect.parent / "payload/extant_config.py",
         "        tomllib = None                                   # type: ignore[assignment]",
         "        raise"),
        ("a config file with no parser fails without saying how to fix it",
         detect.parent / "payload/extant_config.py",
         "    if tomllib is None:\n        raise ValueError(_NO_PARSER.format(path=path))",
         "    if False:\n        raise ValueError(_NO_PARSER.format(path=path))"),

        # --- install snippets ----------------------------------------------------
        # This rule is the newest and had no mutations at all, which is the state
        # every gap starts in. Its two false-positive guards matter more than the
        # positive case: a rule that flags a correct line is how a validator earns
        # a reputation for noise, and both guards are invisible to a test that
        # only checks that a dead pin is reported.
        # Disabled by emptying the loop rather than by blanking the message: the
        # first attempt replaced the text with `"" or f"..."`, which Python
        # evaluates straight back to the f-string. A mutation that changes
        # nothing SURVIVES every time and reads as a gap in the suite, which is
        # the harness lying rather than the tests failing. This shape also
        # leaves the DENOMINATOR at 1 while findings drop to 0, which is the
        # exact "examined but never reports" defect the project cares about.
        ("pinned-ref never fires", collect,
         "    for number, ref in _pinned_refs(repo, text):",
         "    for number, ref in []:"),
        ("pinned-ref ignores the governing repo (flags third-party pins)", collect,
         "        if match and governing == own:",
         "        if match:"),
        ("pinned-ref stops normalising remotes (SSH never matches HTTPS)", collect,
         '    parts = [p for p in url.replace(":", "/").split("/") if p]',
         '    parts = [p for p in url.split("/") if p]'),
        ("pinned-ref keeps the .git suffix, so no remote ever matches", collect,
         '    if url.endswith(".git"):',
         "    if False:"),
        # NOT a no-origin mutation. Removing `if own is None: return []` changes
        # nothing, because `governing == None` never matches and no pin is
        # collected either way - the guard is a short-circuit, not a behaviour.
        # A mutation there survives forever and blames the tests for it. This
        # probes the reported line number instead, which is what a reader
        # actually navigates by.
        ("pinned-ref reports the wrong line number", collect,
         "    governing: str | None = None\n"
         "    for number, line in enumerate(text.splitlines(), start=1):",
         "    governing: str | None = None\n"
         "    for number, line in enumerate(text.splitlines(), start=2):"),

        # --- the installer and its presets ---------------------------------------
        # install.py had no mutations either, and it is where the 0.6.1 bug lived:
        # the preset that exists for projects WITHOUT a status document could not
        # be used on one. Every guard below was added because its absence shipped.
        ("preset document is not consulted when detection finds nothing",
         detect.parent / "install.py",
         "    if preset_doc and (repo / preset_doc).is_file():",
         "    if False and preset_doc and (repo / preset_doc).is_file():"),
        ("preset names extra documents the project does not have",
         detect.parent / "install.py",
         '    extras = [e for e in preset.get("extra_docs", []) if (repo / str(e)).is_file()]',
         '    extras = [str(e) for e in preset.get("extra_docs", [])]'),
        ("preset emits a consistency check whose files are absent",
         detect.parent / "install.py",
         "            if all((repo / f).is_file() for f in sources)",
         "            if True"),
        ("preset stops switching off the features it disables",
         detect.parent / "install.py",
         '    for key in preset.get("disable", []):          # type: ignore[union-attr]',
         "    for key in []:"),

        # --- the baseline -------------------------------------------------------
        # A ratchet is only as good as the things that stop it loosening, so
        # every mutation here breaks a CONSTRAINT rather than the suppression.
        # Suppression working is easy; suppression that cannot quietly grow to
        # cover everything is the whole design.
        ("baseline suppresses by kind, so every future finding is forgiven", collect,
         "                if fingerprint in baselined:",
         "                if any(e[\"kind\"] == finding.kind for e in baselined.values()):"),
        ("baseline stops stating how much it is hiding", collect,
         '            diag(f"{len(located)} new finding(s), {suppressed} suppressed by "',
         '            diag("" or f"{len(located)} new finding(s), {suppressed} hidden by "'),
        ("a missing baseline becomes an empty one", collect,
         "    if not path.is_file():\n        raise ValueError(",
         "    if not path.is_file():\n        return {}\n    if False:\n        raise ValueError("),
        ("re-recording honours the active baseline and shrinks the file", collect,
         "        if (args.baseline or args.baseline_check) and not args.write_baseline:",
         "        if args.baseline or args.baseline_check:"),
        ("baseline-check stops reporting entries that no longer occur", collect,
         "            stale = [entry for fingerprint, entry in sorted(baselined.items())\n"
         "                     if fingerprint not in matched]",
         "            stale = []"),

        # --- the cross-platform agent skill --------------------------------------
        # The newest code, which is where every gap starts. Setup writes agent
        # instructions to two paths from ONE set of observations, so the failure
        # that matters is not either file going missing: it is the two of them
        # describing different documents. This project shipping a document that
        # contradicts another document, via its own installer, would be the exact
        # thing it exists to catch.
        ("the cross-platform skill is never written",
         detect.parent / "install.py",
         "    skill_path = repo / AGENT_SKILL_DEST",
         "    skill_path = repo / (AGENT_SKILL_DEST + '.disabled')"),
        # Renders the Claude template to the standard path. Both files still
        # appear, both name the right document, and the only thing wrong is that
        # a non-Claude agent gets a file whose frontmatter it cannot use - which
        # is invisible to any check that merely counts files.
        ("the agent skill is rendered from the Claude template",
         detect.parent / "install.py",
         "    skill_text, skill_notes = render_command(obs, repo.name, AGENT_SKILL_TEMPLATE)",
         "    skill_text, skill_notes = render_command(obs, repo.name, COMMAND_TEMPLATE)"),
        ("render_command ignores the template it is given",
         detect.parent / "install.py",
         "    text = (SKILL_ROOT / template).read_text(encoding=\"utf-8\")",
         "    text = (SKILL_ROOT / COMMAND_TEMPLATE).read_text(encoding=\"utf-8\")"),
        ("the skill is copied verbatim, so placeholders survive",
         detect.parent / "install.py",
         "    skill_text, skill_notes = render_command(obs, repo.name, AGENT_SKILL_TEMPLATE)",
         "    skill_text, skill_notes = (SKILL_ROOT / AGENT_SKILL_TEMPLATE).read_text("
         "encoding=\"utf-8\"), []"),
        ("an existing hand-edited skill is silently overwritten",
         detect.parent / "install.py",
         "    if skill_path.exists() and not args.force:",
         "    if False:"),

        # --- Git LFS storage -----------------------------------------------
        # This rule talks to git through pipes, and both of its plumbing bugs
        # were invisible in the result: the survey reported 1 of 4 governed
        # files and still found the single real problem, so it looked perfect.
        ("the raw-blob check never fires", collect,
         "        if size is None or sha in pointers:", "        if True:"),
        ("check-attr loses -z, so git quotes any path with a space", collect,
         '["git", "check-attr", "-z", "--stdin", "filter"], cwd=repo,',
         '["git", "check-attr", "--stdin", "filter"], cwd=repo,'),
        ("the NUL join reverts to newlines (the Windows CR bug)", collect,
         'payload = ("\\0".join(blobs) + "\\0").encode("utf-8")',
         'payload = ("\\n".join(blobs) + "\\n").encode("utf-8")'),
        ("the LFS survey reads the index instead of the committed tree", collect,
         '            ["git", "ls-tree", "-r", "-z", "HEAD"], cwd=repo,',
         '            ["git", "ls-files", "-z"], cwd=repo,'),
        ("the LFS gate stops reading .gitattributes", collect,
         '    return any("filter=lfs" in line and not line.lstrip().startswith("#")\n'
         "               for line in text.splitlines())",
         "    return False"),
        # NOT a mutation on the size shortcut. Reading every governed blob
        # instead of only the small ones changes cost, never behaviour, so it
        # survives every time and reads as a gap the tests do not have.

        # --- the game-engine presets ---------------------------------------
        # Raw strings: these anchors contain regex escapes, and an unraw "\d"
        # is a SyntaxWarning today and an error in a future Python. There is a
        # lint in this repository for exactly that.
        ("godot version check moves to the README",
         detect.parent / "install.py",
         r'                "doc/setup_instructions.md": r"Godot version is[^\d]*(\d+\.\d+)",',
         r'                "README.md": r"Godot version is[^\d]*(\d+\.\d+)",'),
        ("unity badge pattern loses the build suffix",
         detect.parent / "install.py",
         r'                "README.md": r"Unity%20Version:-([\d.]+f\d+)",',
         r'                "README.md": r"Unity%20Version:-(\d+\.\d+)",'),

        # --- detect.py ----------------------------------------------------------
        ("find_documents returns only the first match", detect,
         "    return found",
         "    return found[:1]"),
        ("trunk detection ignores origin/HEAD", detect,
         '    head = _git(repo, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD").strip()',
         '    head = ""'),
        # Tag shape is MEASURED, and both directions matter. Ignoring the repo's
        # real prefixes leaves `release-1.2.3` unmatched, so the rule examines
        # nothing on a whole class of project; widening without evidence loosens
        # the pattern for everyone, which is where false positives come from.
        ("release-tag shape ignores the prefixes this repo actually uses", detect,
         '    extra = sorted(p for p in prefixes if p not in ("", "v"))',
         "    extra = []"),
        ("release-tag shape widens without evidence", detect,
         '    extra = sorted(p for p in prefixes if p not in ("", "v"))',
         '    extra = sorted({*prefixes, "release-"} - {"", "v"})'),
    ]


def install_restore_guard(backups: dict[Path, str]) -> None:
    """Put the source back if this process is killed part-way through.

    try/finally covers exceptions and nothing else. A campaign interrupted
    between writing a mutation and restoring it leaves BROKEN CODE ON DISK,
    indistinguishable from a deliberate edit - and it happened: a run stopped
    mid-mutation left `"dead-sha": 1` in the denominator, which would have been
    committed as a validator that always claims to have examined one reference.

    Restoring on SIGINT and SIGTERM closes the window that matters. A SIGKILL
    cannot be caught by anything, which is why the finished run also verifies
    the tree and says so.
    """
    import atexit
    import signal

    def restore(*_args: object) -> None:
        for path, original in backups.items():
            try:
                if path.read_text(encoding="utf-8") != original:
                    with open(path, "w", encoding="utf-8", newline="\n") as fh:
                        fh.write(original)
                    print(f"\nrestored {path.name} after interruption", file=sys.stderr)
            except OSError:
                pass

    atexit.register(restore)
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, lambda *_a: (restore(), sys.exit(130)))
        except (ValueError, OSError, AttributeError):
            pass    # not the main thread, or the platform lacks the signal


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
    parser.add_argument("--check-only", action="store_true",
                        help="verify every mutation still matches, run no tests")
    args = parser.parse_args()

    root = Path(args.repo).resolve()
    skill = root / "plugin/skills/extant"
    mutations = build_mutations(skill / "payload/extant_collect.py", skill / "detect.py")

    # Existence FIRST. Reading before checking raised FileNotFoundError and
    # the careful message below never printed.
    paths = {path for _l, path, _o, _n in mutations}
    missing = [p for p in paths if not p.is_file()]
    if missing:
        for path in missing:
            print(f"missing source file: {path}")
        return 1
    backups = {path: path.read_text(encoding="utf-8") for path in paths}

    if args.check_only:
        # Seconds rather than half an hour, because it runs no tests. Mutations
        # rot alongside the code they point at: one silently stopped probing
        # anything when ancestry moved to a batched rev-list, and that was only
        # discovered at the next full campaign. This is cheap enough for CI, so
        # the rot is caught by the commit that causes it.
        stale = [f"{label} (matched {backups[path].count(old)}x)"
                 for label, path, old, _new in mutations
                 if backups[path].count(old) != 1]
        print(f"checked {len(mutations)} mutations against the current source: "
              f"{len(mutations) - len(stale)} match exactly once, {len(stale)} do not")
        for entry in stale:
            print(f"  STALE  {entry}")
        if stale:
            print()
            print("A mutation that matches nothing probes nothing, and a campaign")
            print("containing one reports a clean result it did not earn. Retarget")
            print("each of the above at the code that replaced what it named.")
        return 1 if stale else 0

    install_restore_guard(backups)

    print("NOTE: this rewrites the source in place, one mutation at a time.")
    print("      Do not edit the repository while it runs, and do not run it")
    print("      against a tree you have uncommitted work in.\n")

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
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(original.replace(old, new, 1))
        try:
            green = run_suite(root, args.python)
        finally:
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(original)
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
