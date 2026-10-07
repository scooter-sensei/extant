"""What install.py prints and the three files it renders, compared WHOLE on
repositories built to reach its branches.

D7 found 503 of install.py's 1,272 mutants surviving the whole suite: the
tests asserted single keys of the config (`config_of(repo)["trunk"]`) and
single phrases of the output, so a mutant that changed another key, a
confidence, a quoting branch or a rendered command went unseen. These
compare everything. The installer runs as a subprocess, as
test_install_presets.py runs it: the exit code and the files it leaves
behind are the contract.

The wording is compared too. The installer's prose states what each setting
will DO, and `closing_advice` records one sentence that was false in 39 of 39
benchmark installs; a claim about behaviour is what extant exists to keep
true. Each fixed paragraph is written ONCE below, so a rewording is one edit.

The command and the agent skill are compared against their TEMPLATES with
the four values substituted, so the tests pin what the installer decides
without restating the templates' prose. The payload's file list is read from
the payload tree for the same reason.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import install
from detect import Observation
from test_detect_outputs import STATUS, _tickets_and_remotes
from test_install_presets import config_of, make_repo

SKILL_ROOT = Path(install.__file__).resolve().parent
INSTALLER = SKILL_ROOT / "install.py"
TEMPLATES = SKILL_ROOT / "payload" / "commands"
FILES = (".extant.toml", ".claude/commands/extant.md", ".agents/skills/extant/SKILL.md")


def _run(repo: Path, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    """The installer as a user runs it - and from OUTSIDE the repository,
    which is how the skill runs it (`--repo` names the target). Every other
    installer test runs it from inside, where a git call that drops `repo`
    and falls back to the working directory still reads the right history;
    from here it reads none."""
    return subprocess.run([sys.executable, str(INSTALLER), "--repo", str(repo), *args],
                          cwd=repo.parent, capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          env={**os.environ, **env})


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def _read(path: Path) -> str:
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


def _swap(text: str, old: str, new: str) -> str:
    """`text` with `old` replaced once - and `old` must be there, because a
    replace that matches nothing returns its input and the test would then
    compare against the wrong expectation without saying so."""
    assert text.count(old) == 1, old
    return text.replace(old, new)


def _rendered(template: str, **values: str) -> str:
    """The template with each `{{KEY}}` replaced - what render_command is
    specified to produce - and nothing left unsubstituted."""
    text = _read(TEMPLATES / template)
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    assert not re.search(r"\{\{[A-Z_]+\}\}", text), "a placeholder the test did not name"
    return text


def _actions(verb: str) -> list[str]:
    """copy_payload's actions for a fresh tree (install.py:736-783), from the
    payload as it is on disk: the files, then the tree's count and members,
    sorted. `verb` is "copied" or "would copy"."""
    lines = [f"{verb} {dst}" for _src, dst in install.PAYLOAD]
    for src_rel, dst_rel in install.PAYLOAD_TREES:
        root = SKILL_ROOT / src_rel
        members = sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)
        lines.append(f"{src_rel}/: {len(members)} file(s) to place")
        lines += [f"{verb} {dst_rel}/{p.relative_to(root).as_posix()}" for p in members]
    return lines


def _skipped() -> list[str]:
    """copy_payload's actions over an identical install: each file skipped,
    the tree's count line kept."""
    return [line if line.endswith("file(s) to place")
            else line.replace("copied ", "", 1) + ": already present and identical, skipped"
            for line in _actions("copied")]


def _indented(lines: list[str]) -> list[str]:
    return [f"  {line}" for line in lines]


HOOKS = "  checked 3 hook reference(s): extant-verify, install, main-tree-guard"
SKILL_WRITTEN = ("wrote .agents/skills/extant/SKILL.md, read by Codex, Gemini CLI, "
                 "Copilot, Cursor and Kimi")
LEFT_ALONE = "already exists - left alone (use --force to replace)"
NO_PREFIX = ("  entry_prefix was not detected; the command file falls back to "
             "'## Phase '. Set it in .extant.toml and correct the command, or "
             "archiving and live-claim checks will not recognise your entries.")
NO_CLAUDE = ("  skipped .claude/commands/extant.md: no .claude or CLAUDE.md here "
             "- use --claude-command to write it anyway")


def _closing(shipped: str, *, off: str = "", unverified: str = "",
             weak: str = "") -> list[str]:
    """closing_advice (install.py:1283): the lists are what this run decided,
    the paragraph after them is the same on every run."""
    lines = ["still needs you",
             f"  SHIPPED DEFAULT: {shipped} - not determined here, so each runs "
             "on the pattern extant ships.",
             "  --verify names every rule that examines nothing under one. Set "
             "your own, or '' to switch a pattern off."]
    if off:
        lines.append(f"  OFF: {off} - switched off in the config.")
    if unverified:
        lines.append(f"  NOT VERIFIED: {unverified} - written without evidence; check it.")
    if weak:
        lines.append(f"  LOW CONFIDENCE: {weak} - verify against the real document.")
    return lines + [
        "  Then run --verify and read its denominator line: a rule that examined",
        "  0 candidates is inert whatever the exit code says. Then break something",
        "  on purpose to watch a rule fire - a rule never observed failing has not",
        "  been tested.",
        "  Finally: sh tools/hooks/install",
    ]


def _row(key: str, confidence: str, shown: str, evidence: str) -> list[str]:
    """One entry of the `derived configuration` table, as its two lines are
    specified (install.py:1212-1220): the key padded to the longest key (28,
    release_claims_name_our_tags), the confidence padded to 8 in brackets,
    the value cut at 70."""
    return [f"  {key:<28}  [{confidence:<8}] {shown[:70]}", f"  {'':<28}   {evidence}"]


CONFIG_HEADER = """\
# Generated by the extant skill's installer, by inspecting this repo.
#
# Confidence is recorded per value. Anything marked unknown or default
# is COMMENTED OUT rather than guessed, and a commented setting is the
# shipped default - extant's own patterns, measured on the project it
# was built for. Every run says so beside a rule that examines nothing
# under one. Write your own, or '' to switch a pattern off.
# See references/porting.md.

[extant]
"""

SHIPPED_TAIL = """\
# [default] cannot be derived - depends on how THIS project says 'not done yet'
# live_phrases = '...'   # not determined here - the shipped default applies; set your own, or '' to switch it off

# [default] not derived - the shipped pattern reads a backticked path after **Plan:**, **Design:**, 'see' or 'read'
# path_pointer = '...'   # not determined here - the shipped default applies; set your own, or '' to switch it off
"""

# --- I1: a status-document repository, everything derived ---------------------

I1_CONFIG = CONFIG_HEADER + """\
# [derived] 13 lines
primary_doc = "STATUS.md"

# [derived] origin/HEAD -> main
trunk = "main"

# [derived] 8 branches sampled; slash prefixes: feature/ x3; ticket keys: ABC- x3
branch_token = '`((?:feature)/[^`]+|(?:ABC)-\\d+[^`]*)`'

# [derived] 2 tags, all v-prefixed or bare
release_tag = '(?:released|shipped|tagged)\\s+(?:in|as|at)\\s+`?(v?\\d+\\.\\d+(?:[\\w.-]*[\\w])?)`?'

# [derived] 4/10 subjects carry a ticket id; grouping by ticket
phase_task = '\\b([A-Z][A-Z0-9]{1,9}-\\d+)\\b'

# [derived] placed beside the document
archive_doc = "status-archive.md"

# [derived] this document describes this repository, so its release claims name these tags
release_claims_name_our_tags = true

# [guessed] highest-scoring header '## Release'; others: # Status, ## Notes
entry_prefix = "## Release "

# [derived] 2 example(s) using: merged, shipped
merge_claim = '(?:merged|shipped)\\s+(?:to|into|in|on)\\s+(`[^`\\n]+`|[\\w.\\-/]+)\\s+(?:at|in|as)\\s+`?([0-9a-f]{7,40})`?(?![0-9a-f])'

""" + SHIPPED_TAIL + """
retain_entries = 3
"""

_SHIPPED_ROWS = [
    *_row("live_phrases", "default", "shipped default",
          "cannot be derived - depends on how THIS project says 'not done yet'"),
    *_row("path_pointer", "default", "shipped default",
          "not derived - the shipped pattern reads a backticked path after "
          "**Plan:**, **Design:**, 'see' or 'read'"),
]
_OURS = ("this document describes this repository, so its release claims name "
         "these tags")

I1_TABLE = [
    *_row("primary_doc", "derived", "STATUS.md", "13 lines"),
    *_row("trunk", "derived", "main", "origin/HEAD -> main"),
    *_row("branch_token", "derived", "`((?:feature)/[^`]+|(?:ABC)-\\d+[^`]*)`",
          "8 branches sampled; slash prefixes: feature/ x3; ticket keys: ABC- x3"),
    *_row("release_tag", "derived",
          r"(?:released|shipped|tagged)\s+(?:in|as|at)\s+`?(v?\d+\.\d+(?:[\w.-]*[\w])?)`?",
          "2 tags, all v-prefixed or bare"),
    *_row("phase_task", "derived", r"\b([A-Z][A-Z0-9]{1,9}-\d+)\b",
          "4/10 subjects carry a ticket id; grouping by ticket"),
    *_row("archive_doc", "derived", "status-archive.md", "placed beside the document"),
    *_row("release_claims_name_our_tags", "derived", "True", _OURS),
    *_row("entry_prefix", "guessed", "## Release ",
          "highest-scoring header '## Release'; others: # Status, ## Notes"),
    *_row("merge_claim", "derived",
          r"(?:merged|shipped)\s+(?:to|into|in|on)\s+(`[^`\n]+`|[\w.\-/]+)\s+(?:at|in|as)"
          r"\s+`?([0-9a-f]{7,40})`?(?![0-9a-f])",
          "2 example(s) using: merged, shipped"),
    *_SHIPPED_ROWS,
]
I1_CLOSING = _closing("live_phrases, path_pointer", weak="entry_prefix")


def _status_repo(root: Path, status: str = STATUS) -> Path:
    """I1: test_detect_outputs.py's tickets-and-remotes history, a status
    document, and the CLAUDE.md that makes the installer render the slash
    command. The two documents are left untracked: nothing on this path reads
    the index."""
    repo = _tickets_and_remotes(root)
    _write(repo / "STATUS.md", status)
    _write(repo / "CLAUDE.md", "# notes\n")
    return repo


def _i1_files(repo: Path, entry_prefix: str = "## Release ") -> list[str]:
    return [_rendered("extant.md.template", PROJECT=repo.name, DOC="STATUS.md",
                      ARCHIVE="status-archive.md", ENTRY_PREFIX=entry_prefix),
            _rendered("agent-skill.md.template", PROJECT=repo.name, DOC="STATUS.md")]


def _i1_stdout(repo: Path, payload: list[str], files: list[str],
               hooks: tuple[str, ...] = (HOOKS,)) -> list[str]:
    return ["payload", *_indented(payload), *hooks,
            "", "document", "", "derived configuration", *I1_TABLE, "",
            *files, "", *I1_CLOSING]


def _wrote(repo: Path, verb: str = "wrote", why: str = "found CLAUDE.md") -> list[str]:
    return [f"  {verb} .extant.toml",
            f"  {verb} .claude/commands/extant.md, rendered for '{repo.name}' ({why})",
            "  " + SKILL_WRITTEN.replace("wrote", verb, 1)]


def test_a_status_document_repository_is_installed_whole(tmp_path: Path) -> None:
    repo = _status_repo(tmp_path)
    run = _run(repo)
    assert (run.returncode, run.stderr) == (0, "")
    assert [_read(repo / f) for f in FILES] == [I1_CONFIG, *_i1_files(repo)]
    assert run.stdout.splitlines() == _i1_stdout(repo, _actions("copied"), _wrote(repo))


def test_a_second_run_leaves_every_file_alone_and_force_rewrites_them(
        tmp_path: Path) -> None:
    """install.py:1224-1266. A second run skips each identical payload file
    and leaves each rendered file alone, even one edited by hand; --force
    replaces all of them. By then the first run has created `.claude/`, so
    the command's evidence names it too."""
    repo = _status_repo(tmp_path)
    assert _run(repo).returncode == 0
    _write(repo / ".extant.toml", "# edited by hand\n")

    again = _run(repo)
    assert (again.returncode, again.stderr) == (0, "")
    assert again.stdout.splitlines() == _i1_stdout(
        repo, _skipped(), [f"  {f} {LEFT_ALONE}" for f in FILES])
    assert _read(repo / ".extant.toml") == "# edited by hand\n"

    forced = _run(repo, "--force")
    assert (forced.returncode, forced.stderr) == (0, "")
    assert forced.stdout.splitlines() == _i1_stdout(
        repo, _actions("copied"), _wrote(repo, why="found .claude, CLAUDE.md"))
    assert [_read(repo / f) for f in FILES] == [I1_CONFIG, *_i1_files(repo)]


def test_a_dry_run_writes_nothing_and_says_so(tmp_path: Path) -> None:
    """install.py:1099-1104 and the three `would write` lines: everything a
    real run would print, no hook check (there are no hooks to check), and no
    file - not the payload, not one rendered file."""
    repo = _status_repo(tmp_path)
    run = _run(repo, "--dry-run")
    assert (run.returncode, run.stderr) == (0, "")
    assert run.stdout.splitlines() == _i1_stdout(
        repo, _actions("would copy"), _wrote(repo, verb="would write"), hooks=())
    assert [name for name in (".extant.toml", ".claude", ".agents", "tools")
            if (repo / name).exists()] == []


def test_an_undetected_entry_prefix_falls_back_and_says_so(tmp_path: Path) -> None:
    """install.py:865-874 and render_command (install.py:707-714): no dated
    header repeats, so entry_prefix is unknown and commented out, and BOTH
    rendered files fall back to '## Phase ' and say so; nothing reads as a
    merge either, so merge_claim joins the shipped defaults."""
    repo = _status_repo(tmp_path, "# Status\n\nNothing dated here.\n")
    run = _run(repo)
    assert (run.returncode, run.stderr) == (0, "")

    config = _swap(I1_CONFIG, "# [derived] 13 lines", "# [derived] 3 lines")
    config = _swap(config, """\
# [guessed] highest-scoring header '## Release'; others: # Status, ## Notes
entry_prefix = "## Release "
""", """\
# [unknown] no repeated dated header found
# entry_prefix = '...'   # not determined here - the shipped default applies; set your own
""")
    config = _swap(config, config[config.index("# [derived] 2 example(s)"):
                                  config.index("# [default] cannot be derived")], """\
# [unknown] no 'verb ... target at <sha>' phrasing found
# merge_claim = '...'   # not determined here - the shipped default applies; set your own, or '' to switch it off

""")
    assert [_read(repo / f) for f in FILES] == [
        config, *_i1_files(repo, entry_prefix="## Phase ")]

    table = I1_TABLE[:]
    table[0:2] = _row("primary_doc", "derived", "STATUS.md", "3 lines")
    at = table.index(_row("entry_prefix", "guessed", "## Release ", "x")[0])
    table[at:at + 4] = [
        *_row("entry_prefix", "unknown", "shipped default",
              "no repeated dated header found"),
        *_row("merge_claim", "unknown", "shipped default",
              "no 'verb ... target at <sha>' phrasing found")]
    wrote = _wrote(repo)
    assert run.stdout.splitlines() == [
        "payload", *_indented(_actions("copied")), HOOKS,
        "", "document", "", "derived configuration", *table, "",
        wrote[0], wrote[1], NO_PREFIX, wrote[2], NO_PREFIX, "",
        *_closing("entry_prefix, merge_claim, live_phrases, path_pointer")]


# --- I3: the readme preset ----------------------------------------------------

I3_CONFIG = CONFIG_HEADER + """\
# [derived] 3 lines
primary_doc = "README.md"

# [derived] branch exists locally
trunk = "main"

# [guessed] 1 branch, no repeated prefix; matching any slashed name
branch_token = '`([\\w.-]+/[^`]+)`'

# [default] no version-shaped tags here
# release_tag = '...'   # not determined here - the shipped default applies; set your own, or '' to switch it off

# [derived] placed beside the document
archive_doc = "status-archive.md"

# [derived] this document describes this repository, so its release claims name these tags
release_claims_name_our_tags = true

# [unknown] no repeated dated header found
# entry_prefix = '...'   # not determined here - the shipped default applies; set your own

# [unknown] no 'verb ... target at <sha>' phrasing found
# merge_claim = '...'   # not determined here - the shipped default applies; set your own, or '' to switch it off

""" + SHIPPED_TAIL + """
# [derived] present in this repo, added by preset 'readme'
extra_docs = ["CONTRIBUTING.md"]

# [derived] switched off by preset 'readme'
phase_task = ''

# [derived] switched off by preset 'readme'
phase_bare = ''

# [derived] switched off by preset 'readme'
plans_dir = ''

retain_entries = 3
"""

# The rows a one-commit repository with no tag and no status document gives,
# shared by I3 and I4.
_FRESH_ROWS = [
    *_row("trunk", "derived", "main", "branch exists locally"),
    *_row("branch_token", "guessed", r"`([\w.-]+/[^`]+)`",
          "1 branch, no repeated prefix; matching any slashed name"),
    *_row("release_tag", "default", "shipped default", "no version-shaped tags here"),
]
_UNDETECTED_ROWS = [
    *_row("archive_doc", "derived", "status-archive.md", "placed beside the document"),
    *_row("release_claims_name_our_tags", "derived", "True", _OURS),
    *_row("entry_prefix", "unknown", "shipped default", "no repeated dated header found"),
    *_row("merge_claim", "unknown", "shipped default",
          "no 'verb ... target at <sha>' phrasing found"),
    *_SHIPPED_ROWS,
]


def test_the_readme_preset_on_a_project_with_no_status_document(tmp_path: Path) -> None:
    """choose_document takes the preset's README (install.py:818-819);
    apply_preset (install.py:506-551) keeps it, adds CONTRIBUTING.md and
    switches three keys off, moving them to the end; no CLAUDE evidence, so
    the slash command is skipped and says why, and the agent skill is still
    written - with the entry-prefix fallback, which the skill carries too."""
    repo = make_repo(tmp_path, **{"README.md": "# Proj\n\nA project.\n",
                                  "CONTRIBUTING.md": "# Contributing\n"})
    run = _run(repo, "--preset", "readme")
    assert (run.returncode, run.stderr) == (0, "")
    assert _read(repo / ".extant.toml") == I3_CONFIG
    assert not (repo / ".claude").exists()
    assert _read(repo / FILES[2]) == _rendered(
        "agent-skill.md.template", PROJECT=repo.name, DOC="README.md")
    off = "switched off by preset 'readme'"
    assert run.stdout.splitlines() == [
        "payload", *_indented(_actions("copied")), HOOKS,
        "", "document", "  using README.md, named by the preset",
        "", "  preset 'readme': check the docs you already have (no status file needed)",
        "    primary_doc already README.md",
        "    extra_docs -> CONTRIBUTING.md",
        "    disabled: phase_task, phase_bare, plans_dir",
        "", "derived configuration",
        *_row("primary_doc", "derived", "README.md", "3 lines"),
        *_FRESH_ROWS, *_UNDETECTED_ROWS,
        *_row("extra_docs", "derived", "['CONTRIBUTING.md']",
              "present in this repo, added by preset 'readme'"),
        *_row("phase_task", "derived", "'' (off)", off),
        *_row("phase_bare", "derived", "'' (off)", off),
        *_row("plans_dir", "derived", "'' (off)", off),
        "", "  wrote .extant.toml", NO_CLAUDE, "  " + SKILL_WRITTEN, NO_PREFIX, "",
        *_closing("release_tag, entry_prefix, merge_claim, live_phrases, path_pointer",
                  off="phase_task, phase_bare, plans_dir", weak="branch_token")]


# --- I4: --wide-docs nominates a root README.rst ------------------------------

I4_CONFIG = CONFIG_HEADER + """\
# [derived] 4 lines; nominated by --wide-docs, no status document detected
primary_doc = "README.rst"

# [derived] branch exists locally
trunk = "main"

# [guessed] 1 branch, no repeated prefix; matching any slashed name
branch_token = '`([\\w.-]+/[^`]+)`'

# [default] no version-shaped tags here
# release_tag = '...'   # not determined here - the shipped default applies; set your own, or '' to switch it off

# [unknown] no grouping key found in 1 subject; switched off rather than inheriting another project's pattern
phase_task = ''

# [unknown] 0/1 subjects name a bare 'Phase N.N'; switched off rather than inheriting another project's pattern
phase_bare = ''

# [derived] placed beside the document
archive_doc = "status-archive.md"

# [derived] this document describes this repository, so its release claims name these tags
release_claims_name_our_tags = true

# [unknown] no repeated dated header found
# entry_prefix = '...'   # not determined here - the shipped default applies; set your own

# [unknown] no 'verb ... target at <sha>' phrasing found
# merge_claim = '...'   # not determined here - the shipped default applies; set your own, or '' to switch it off

""" + SHIPPED_TAIL + """
# [derived] 1 found by --wide-docs at the root and under docs/, ordinary stratum only
extra_docs = ["docs/guide.md"]

retain_entries = 3
"""


def test_wide_docs_nominates_a_root_readme_rst(tmp_path: Path) -> None:
    """No status document, so --wide-docs nominates the root README under the
    suffix it has (install.py:1158-1182) and says so in the evidence
    (install.py:1194-1201); `_fold_wide_docs` (install.py:607-645) adds what
    is left. NOT test_detect_outputs.py's mixed tree: its root CHANGELOG.md
    is a status-document NAME (detect.py:303-306), so the installer would
    choose it and nominate nothing. docs/HISTORY.md keeps the
    historical-record exclusion without being one."""
    repo = make_repo(tmp_path, **{
        "README.rst": "Proj\n====\n\nA project.\n", "docs__HISTORY.md": "# x\n",
        "docs__guide.md": "# x\n", "docs__vendor__lib.md": "# x\n",
        "docs__api__index.md": "# x\n", "docs__a__b__c__deep.md": "# x\n",
        "notes__x.md": "# x\n", "src__readme.txt": "x\n"})
    run = _run(repo, "--wide-docs")
    assert (run.returncode, run.stderr) == (0, "")
    assert _read(repo / ".extant.toml") == I4_CONFIG
    off = "switched off rather than inheriting another project's pattern"
    assert run.stdout.splitlines() == [
        "payload", *_indented(_actions("copied")), HOOKS,
        "", "document", "  no status document found in the usual places",
        "", "  --wide-docs: 2 documents (root 1, docs/ 1), ordinary stratum only, depth 3",
        "    1 excluded as generated, 1 excluded as historical-record, "
        "1 excluded as vendored",
        "    each becomes an extra_docs entry; a moved file will be reported as missing",
        "  primary_doc <- README.rst (nominated by --wide-docs; no status document detected)",
        "  --wide-docs: extra_docs -> 1 document(s), 1 newly discovered",
        "", "derived configuration",
        *_row("primary_doc", "derived", "README.rst",
              "4 lines; nominated by --wide-docs, no status document detected"),
        *_FRESH_ROWS,
        *_row("phase_task", "unknown", "'' (off)",
              f"no grouping key found in 1 subject; {off}"),
        *_row("phase_bare", "unknown", "'' (off)",
              f"0/1 subjects name a bare 'Phase N.N'; {off}"),
        *_UNDETECTED_ROWS,
        *_row("extra_docs", "derived", "['docs/guide.md']",
              "1 found by --wide-docs at the root and under docs/, ordinary stratum only"),
        "", "  wrote .extant.toml", NO_CLAUDE, "  " + SKILL_WRITTEN, NO_PREFIX, "",
        *_closing("release_tag, entry_prefix, merge_claim, live_phrases, path_pointer",
                  off="phase_task, phase_bare", weak="branch_token")]


# --- I6, I10: the two ways the installer stops ---------------------------------


def test_a_project_with_no_document_stops_with_its_reason(tmp_path: Path) -> None:
    """install.py:1184-1191: no --doc, no preset, nothing detected - exit 1
    after the payload, and the two ways out named. No config is written. The
    README is NOT nominated: only --wide-docs nominates (install.py:1174)."""
    repo = make_repo(tmp_path, **{"README.md": "# Proj\n", "src__main.py": "x = 1\n"})
    run = _run(repo)
    assert (run.returncode, run.stderr) == (1, "")
    assert run.stdout.splitlines() == [
        "payload", *_indented(_actions("copied")), HOOKS,
        "", "document", "  no status document found in the usual places",
        "", "  No document to check. Pass --doc <path>, or --preset readme",
        "  to check the README and CONTRIBUTING file you already have."]
    assert not (repo / ".extant.toml").exists()


def test_an_unknown_flag_names_the_program_install(tmp_path: Path) -> None:
    """`prog="install"` (install.py:1064) is seen only in a usage message.
    Only its first line's start and its last line are compared: argparse
    wraps the usage to the terminal and has reworded it across the Python
    versions CI runs."""
    run = _run(tmp_path, "--bogus")
    lines = run.stderr.splitlines()
    assert (run.returncode, run.stdout) == (2, "")
    assert lines[0].startswith("usage: install [-h] --repo REPO"), lines
    assert lines[-1] == "install: error: unrecognized arguments: --bogus"
    preset = _run(tmp_path, "--preset", "bogus")
    assert (preset.returncode, preset.stdout) == (2, "")
    assert preset.stderr.splitlines()[-1].startswith(
        "install: error: argument --preset: invalid choice: 'bogus'"), preset.stderr


# --- I8, I9: the payload and its hooks, in process -----------------------------

ORPHAN = ("tools/extant_config.py: ORPHAN from an older layout - delete it, "
          "it is still importable from tools/")


def test_copy_payload_reports_a_changed_file_and_an_orphan(tmp_path: Path) -> None:
    """install.py:736-783: a file edited after install is left alone without
    --force and overwritten with it; a file an older layout shipped is
    reported, never deleted."""
    repo = tmp_path / "proj"
    repo.mkdir()
    assert install.copy_payload(repo, dry_run=False, force=False) == _actions("copied")
    expected = _skipped()
    for edited in ("tools/extant_collect.py", "tools/extant/git.py"):
        _write(repo / edited, "# edited\n")
        expected[expected.index(f"{edited}: already present and identical, skipped")] = (
            f"{edited}: EXISTS AND DIFFERS - left alone, use --force to overwrite")
    _write(repo / "tools/extant_config.py", "# old layout\n")
    assert install.copy_payload(repo, dry_run=False, force=False) == [*expected, ORPHAN]
    assert install.copy_payload(repo, dry_run=False, force=True) == [
        *_actions("copied"), ORPHAN]
    assert _read(repo / "tools/extant/git.py") == _read(
        SKILL_ROOT / "payload/extant/git.py")
    assert (repo / "tools/extant_config.py").is_file()


def test_verify_hooks_says_each_thing_it_can_say(tmp_path: Path) -> None:
    """install.py:116-145, on three trees: no shim, a shim naming no hook,
    and a shim naming one hook that is there and one that is not."""
    bare = tmp_path / "bare"
    bare.mkdir()
    assert install.verify_hooks(bare) == [
        "tools/hooks/install did not land - no hooks can be wired"]

    silent = tmp_path / "silent"
    _write(silent / "tools/hooks/install", "#!/bin/sh\necho nothing to wire\n")
    assert install.verify_hooks(silent) == [
        "tools/hooks/install names no hooks - expected at least one; the check "
        "below would pass vacuously"]

    partial = tmp_path / "partial"
    _write(partial / "tools/hooks/install", "#!/bin/sh\nsh tools/hooks/gone\n"
           "sh tools/hooks/extant-verify\nsh tools/hooks/lost\n")
    _write(partial / "tools/hooks/extant-verify", "#!/bin/sh\n")
    assert install.verify_hooks(partial) == [
        "checked 3 hook reference(s): extant-verify, gone, lost",
        "MISSING: gone, lost - wired but absent, so they will silently NOT run"]


# --- I11-I14: a document under docs/, and three more ways main() answers -------

DOCS_STATUS = ("# Status\n\n## Release 1 - start (2026-01-01)\n\n"
               "## Notes\n\n## Links\n\n## Plans\n")

I11_CONFIG = _swap(I4_CONFIG, """\
# [derived] 4 lines; nominated by --wide-docs, no status document detected
primary_doc = "README.rst"
""", """\
# [derived] 9 lines
primary_doc = "docs/STATUS.md"
""")
I11_CONFIG = _swap(I11_CONFIG, 'archive_doc = "status-archive.md"',
                   'archive_doc = "docs/status-archive.md"')
I11_CONFIG = _swap(I11_CONFIG, """\
# [unknown] no repeated dated header found
# entry_prefix = '...'   # not determined here - the shipped default applies; set your own
""", """\
# [guessed] highest-scoring header '## Release'; others: # Status, ## Notes, ## Links
entry_prefix = "## Release "
""")
I11_CONFIG = _swap(I11_CONFIG, """\
# [derived] 1 found by --wide-docs at the root and under docs/, ordinary stratum only
extra_docs = ["docs/guide.md"]

""", "")


def test_a_document_under_docs_with_the_command_asked_for(tmp_path: Path) -> None:
    """The archive is placed BESIDE the document (install.py:844-847), so
    under docs/, in the config and in the command; one dated header scores
    2, which clears `> 1` (install.py:867), and the evidence names three of
    the other four headers; --claude-command writes the command with no
    Claude evidence and says it was asked for (install.py:1238-1239)."""
    repo = make_repo(tmp_path, **{"docs__STATUS.md": DOCS_STATUS})
    run = _run(repo, "--doc", "docs/STATUS.md", "--claude-command")
    assert (run.returncode, run.stderr) == (0, "")
    assert [_read(repo / f) for f in FILES] == [
        I11_CONFIG,
        _rendered("extant.md.template", PROJECT="proj", DOC="docs/STATUS.md",
                  ARCHIVE="docs/status-archive.md", ENTRY_PREFIX="## Release "),
        _rendered("agent-skill.md.template", PROJECT="proj", DOC="docs/STATUS.md")]
    off = "switched off rather than inheriting another project's pattern"
    assert run.stdout.splitlines() == [
        "payload", *_indented(_actions("copied")), HOOKS,
        "", "document", "  using --doc docs/STATUS.md",
        "", "derived configuration",
        *_row("primary_doc", "derived", "docs/STATUS.md", "9 lines"),
        *_FRESH_ROWS,
        *_row("phase_task", "unknown", "'' (off)",
              f"no grouping key found in 1 subject; {off}"),
        *_row("phase_bare", "unknown", "'' (off)",
              f"0/1 subjects name a bare 'Phase N.N'; {off}"),
        *_row("archive_doc", "derived", "docs/status-archive.md",
              "placed beside the document"),
        *_row("release_claims_name_our_tags", "derived", "True", _OURS),
        *_row("entry_prefix", "guessed", "## Release ",
              "highest-scoring header '## Release'; others: # Status, ## Notes, ## Links"),
        *_row("merge_claim", "unknown", "shipped default",
              "no 'verb ... target at <sha>' phrasing found"),
        *_SHIPPED_ROWS,
        "", "  wrote .extant.toml",
        "  wrote .claude/commands/extant.md, rendered for 'proj' "
        "(asked for on the command line)",
        "  " + SKILL_WRITTEN, "",
        *_closing("release_tag, merge_claim, live_phrases, path_pointer",
                  off="phase_task, phase_bare", weak="branch_token, entry_prefix")]


def test_a_directory_that_is_no_repository_is_refused(tmp_path: Path) -> None:
    """install.py:1094-1097: refused before anything is copied."""
    plain = tmp_path / "plain"
    plain.mkdir()
    run = _run(plain)
    assert (run.returncode, run.stderr) == (1, "")
    assert run.stdout.splitlines() == [f"not a git repository: {plain.resolve()}"]
    assert list(plain.iterdir()) == []


def test_wide_docs_with_no_root_readme_has_nothing_to_nominate(tmp_path: Path) -> None:
    """install.py:1184-1191: --wide-docs found a document, but the
    nomination is the root README and nothing else, so it stops - and says
    which suffixes it looked for."""
    repo = make_repo(tmp_path, **{"docs__guide.md": "# Guide\n"})
    run = _run(repo, "--wide-docs")
    assert (run.returncode, run.stderr) == (1, "")
    assert run.stdout.splitlines() == [
        "payload", *_indented(_actions("copied")), HOOKS,
        "", "document", "  no status document found in the usual places",
        "", "  --wide-docs: 1 document (root 0, docs/ 1), ordinary stratum only, depth 3",
        "    each becomes an extra_docs entry; a moved file will be reported as missing",
        "", "  No document to check. Pass --doc <path>, or --preset readme",
        "  to check the README and CONTRIBUTING file you already have.",
        "  --wide-docs found no root README (.md, .markdown, .mdx, .rst) to nominate."]
    assert not (repo / ".extant.toml").exists()


def test_help_says_what_every_flag_does(tmp_path: Path) -> None:
    """argparse's help (install.py:1081-1108) is how a user learns a flag
    exists. Each sentence is compared, not the page: argparse titles and
    lays the page out differently across the Python versions CI runs.
    COLUMNS is set past any sentence's length and colour is off; whitespace
    is removed before comparing all the same, because argparse's textwrap
    also breaks at a hyphen, and the --preset sentence is long."""
    run = _run(tmp_path, "--help", COLUMNS="100000", NO_COLOR="1", PYTHON_COLORS="0")
    assert (run.returncode, run.stderr) == (0, "")
    page = "".join(run.stdout.split())
    presets = "; ".join(f"{k}: {v['summary']}" for k, v in install.PRESETS.items())
    for sentence in (
            " ".join(str(install.__doc__).split()),
            "--doc DOC path to the status document, if ambiguous",
            "--force overwrite existing payload files",
            "--claude-command write the Claude Code slash command even without "
            "evidence this repo uses Claude Code",
            "--no-claude-command never write the Claude Code slash command",
            "--preset {" + ",".join(sorted(install.PRESETS)) + "} start from a "
            f"known project shape; {presets}",
            "--wide-docs [DEPTH] also check every tracked document at the root and "
            "up to DEPTH (default 3) levels under docs/, restricted to the ordinary "
            "stratum"):
        assert "".join(sentence.split()) in page, sentence


# --- in process: the steps between observing and writing ----------------------

_SEED = [Observation("primary_doc", "STATUS.md", "derived", "13 lines"),
         Observation("trunk", "main", "derived", "branch exists locally")]
DISABLED = "  disabled: phase_task, phase_bare, plans_dir"


def _switched_off(name: str) -> list[Observation]:
    return [Observation(key, "", "derived", f"switched off by preset '{name}'")
            for key in ("phase_task", "phase_bare", "plans_dir")]


def _verified(name: str, table: dict[str, dict[str, str]]) -> Observation:
    return Observation("consistency", table, "derived",
                       f"preset '{name}', files and patterns verified")


_NODE = install.PRESETS["node"]["consistency"]["version"]
_PYPROJECT = 'requires-python = ">=3.11"\nversion = "1.0.0"\n'

# preset, files, the observations handed in, the observations and the notes
# after the summary line handed back.
_PRESET_CASES: dict[str, tuple[str, dict[str, str], list[Observation],
                               list[Observation], list[str]]] = {
    # The document replaced, a source located one directory down, the
    # suite command, one check verified.
    "node-located": ("node", {
        "README.md": "# Proj\n", "CONTRIBUTING.md": "# C\n",
        "CHANGELOG.md": "## [1.2.3] - 2026-01-01\n",
        "packages__app__package.json": '{"version": "1.2.3"}\n'}, _SEED, [
        Observation("primary_doc", "README.md", "derived", "chosen by preset 'node'"),
        _SEED[1],
        Observation("extra_docs", ["CONTRIBUTING.md"], "derived",
                    "present in this repo, added by preset 'node'"),
        *_switched_off("node"),
        Observation("suite_command", ["npm", "test"], "derived", "preset 'node'"),
        _verified("node", {"version": {"packages/app/package.json": _NODE["package.json"],
                                       "CHANGELOG.md": _NODE["CHANGELOG.md"]}})], [
        "  primary_doc -> README.md", "  extra_docs -> CONTRIBUTING.md", DISABLED,
        "  suite_command -> ['npm', 'test']",
        "  consistency.version located package.json -> packages/app/package.json",
        "  consistency -> version"]),
    # No document handed in, so the preset's is APPENDED; two extras; one
    # check with two problems, the first a pattern matching nothing.
    "legacy-web-skipped": ("legacy-web", {
        "README.md": "# Proj\n", "INSTALL.md": "# I\n", "DEPLOY.md": "# D\n",
        ".nvmrc": "lts/iron\n", "CHANGELOG.md": "## 2.0.0\n"}, _SEED[1:], [
        _SEED[1],
        Observation("primary_doc", "README.md", "derived",
                    "chosen by preset 'legacy-web'"),
        Observation("extra_docs", ["INSTALL.md", "DEPLOY.md"], "derived",
                    "present in this repo, added by preset 'legacy-web'"),
        *_switched_off("legacy-web")], [
        "  primary_doc -> README.md", "  extra_docs -> INSTALL.md, DEPLOY.md", DISABLED,
        "  consistency.node_version skipped: nothing matched in .nvmrc, "
        "package.json not here",
        "  consistency.version skipped: package.json not here"]),
    # The preset's document absent, so the detected one is kept; two checks
    # verified where they are declared.
    "ml-verified": ("ml", {
        "pyproject.toml": _PYPROJECT, "environment.yml": "dependencies:\n  - python=3.11\n",
        "CHANGELOG.md": "## 1.0.0\n"}, _SEED, [
        *_SEED, *_switched_off("ml"),
        _verified("ml", install.PRESETS["ml"]["consistency"])], [
        "  README.md does not exist here; kept the detected document", DISABLED,
        "  consistency -> python_version, version"]),
    # A source found twice is refused rather than guessed, and every problem
    # of a check is named, the checks in order.
    "ml-ambiguous": ("ml", {
        "a__pyproject.toml": _PYPROJECT, "b__pyproject.toml": _PYPROJECT,
        "CHANGELOG.md": "## 1.0.0\n"}, _SEED, [*_SEED, *_switched_off("ml")], [
        "  README.md does not exist here; kept the detected document", DISABLED,
        "  consistency.python_version skipped: 2 candidates for pyproject.toml, "
        "ambiguous, environment.yml not here",
        "  consistency.version skipped: 2 candidates for pyproject.toml, ambiguous"]),
}


@pytest.mark.parametrize("case", sorted(_PRESET_CASES))
def test_apply_preset_compared_whole(tmp_path: Path, case: str) -> None:
    """apply_preset (install.py:506-604): a preset names documents and
    shape, and never overrides what was measured; each consistency source is
    located before it is read, and kept only if its pattern matches."""
    name, files, seed, expected, notes = _PRESET_CASES[case]
    repo = make_repo(tmp_path, **files)
    assert install.apply_preset(name, seed, repo) == (
        expected, [f"preset '{name}': {install.PRESETS[name]['summary']}", *notes])


def test_wide_docs_add_to_what_is_configured_and_say_so() -> None:
    """_fold_wide_docs (install.py:607-645): appended to a preset's extras,
    never over them; the document and the archive are never added; and an
    enumeration that adds nothing says so."""
    obs = [Observation("primary_doc", "README.md", "derived", "x"),
           Observation("archive_doc", "status-archive.md", "derived", "x"),
           Observation("extra_docs", ["CONTRIBUTING.md"], "derived", "x")]
    assert install._fold_wide_docs(obs, ["CONTRIBUTING.md", "README.md", "docs/guide.md",
                                         "status-archive.md"]) == ([
        obs[0], obs[1],
        Observation("extra_docs", ["CONTRIBUTING.md", "docs/guide.md"], "derived",
                    "1 found by --wide-docs at the root and under docs/, ordinary "
                    "stratum only; 1 already configured")], [
        "  --wide-docs: extra_docs -> 2 document(s), 1 newly discovered"])
    assert install._fold_wide_docs(obs, ["README.md", "CONTRIBUTING.md"]) == (
        obs, ["  --wide-docs: adds nothing that is not already configured"])


def test_choose_document_says_how_it_chose(tmp_path: Path) -> None:
    """choose_document (install.py:786-828): --doc first, and a --doc that
    is not there is refused rather than answered with another file; a
    preset's document that is not there falls back to detection; two
    detected, the nearest the root is taken and both are named."""
    root = tmp_path / "proj"
    for name in ("NEXT_SESSION.md", "docs/STATUS.md", "notes.md"):
        _write(root / name, "# x\n")
    assert install.choose_document(root, "notes.md") == (
        root / "notes.md", ["using --doc notes.md"])
    assert install.choose_document(root, "gone.md") == (
        None, ["--doc gone.md does not exist"])
    assert install.choose_document(root, None, "README.md") == (root / "NEXT_SESSION.md", [
        "MULTIPLE candidates: NEXT_SESSION.md, docs/STATUS.md",
        "  chose NEXT_SESSION.md (nearest the root) - rerun with --doc to override"])


_SHAPES = [
    Observation("trunk", 'x"y\\z', "derived", "a quote and a backslash"),
    Observation("entry_prefix", "## R\t\x01\x7f ", "guessed", "a tab, a control, DEL"),
    Observation("branch_token", "a'b", "derived", "a quote in a pattern"),
    Observation("unnamed", "c'd", "derived", "a key no set names, with a quote"),
    Observation("unnamed_too", "e", "derived", "and without"),
    Observation("suite_command", ["npm", "run", "test"], "derived", "three: one line"),
    Observation("extra_docs", ["a.md", "b.md", "c.md", "d.md"], "derived",
                "four: one per line"),
    Observation("plans_dir", "", "derived", "off"),
    Observation("release_claims_name_our_tags", False, "derived", "a switch"),
    Observation("retain", 7, "derived", "a number"),
    Observation("consistency", {"version": {"a.json": '"v": "(\\d+)"',
                                            "b.md": "it's (\\d+)"}}, "derived", "a table"),
]

_SHAPES_TOML = CONFIG_HEADER + (
    "# [derived] a quote and a backslash\n"
    'trunk = "x\\"y\\\\z"\n\n'
    "# [guessed] a tab, a control, DEL\n"
    'entry_prefix = "## R\t\\u0001\\u007F "\n\n'
    "# [derived] a quote in a pattern\n"
    "branch_token = '''a'b'''\n\n"
    "# [derived] a key no set names, with a quote\n"
    "unnamed = '''c'd'''\n\n"
    "# [derived] and without\n"
    "unnamed_too = 'e'\n\n"
    "# [derived] three: one line\n"
    'suite_command = ["npm", "run", "test"]\n\n'
    "# [derived] four: one per line\n"
    'extra_docs = [\n  "a.md",\n  "b.md",\n  "c.md",\n  "d.md",\n]\n\n'
    "# [derived] off\n"
    "plans_dir = ''\n\n"
    "# [derived] a switch\n"
    "release_claims_name_our_tags = false\n\n"
    "# [derived] a number\n"
    "retain = 7\n\n"
    "retain_entries = 3\n\n"
    "# [derived] a table\n"
    "[extant.consistency.version]\n"
    '"a.json" = \'"v": "(\\d+)"\'\n'
    '"b.md" = \'\'\'it\'s (\\d+)\'\'\'\n'
)


def test_render_config_writes_each_shape_so_it_reads_back_as_itself(
        tmp_path: Path) -> None:
    """render_config (install.py:947-1060) on a value of each shape it
    branches on, compared whole, then parsed: every value must read back as
    itself, which is what every one of those branches exists for - the
    escapes in a basic string, the triple quote around an apostrophe in a
    pattern, in a key no set names and in a consistency pattern, a list on
    one line and one per line past three, the consistency table last."""
    text = install.render_config(_SHAPES)
    assert text == _SHAPES_TOML
    _write(tmp_path / ".extant.toml", text)
    assert config_of(tmp_path) == {
        **{o.key: o.value for o in _SHAPES}, "retain_entries": 3}


def test_render_command_fills_each_placeholder_and_names_a_stray_one(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """render_command (install.py:693-733): the archive named is the one
    beside the document; with nothing observed, each placeholder falls back
    and the entry prefix says so; a placeholder the mapping does not know is
    named, every one, rather than shipped silently."""
    obs = [Observation("primary_doc", "docs/STATUS.md", "derived", ""),
           Observation("archive_doc", "docs/status-archive.md", "derived", ""),
           Observation("entry_prefix", "## Release ", "guessed", "")]
    assert install.render_command(obs, "p") == (_rendered(
        "extant.md.template", PROJECT="p", DOC="docs/STATUS.md",
        ARCHIVE="docs/status-archive.md", ENTRY_PREFIX="## Release "), [])
    assert install.render_command([], "p") == (_rendered(
        "extant.md.template", PROJECT="p", DOC="NEXT_SESSION.md",
        ARCHIVE="status-archive.md", ENTRY_PREFIX="## Phase "), [NO_PREFIX[2:]])
    _write(tmp_path / "t.template", "{{PROJECT}} {{NEW}} {{ALSO_NEW}} {{NEW}}\n")
    monkeypatch.setattr(install, "SKILL_ROOT", tmp_path)
    assert install.render_command(obs, "p", "t.template") == (
        "p {{NEW}} {{ALSO_NEW}} {{NEW}}\n",
        ["UNSUBSTITUTED placeholder(s): {{ALSO_NEW}}, {{NEW}}"])


def test_closing_advice_names_every_key_in_each_list() -> None:
    """closing_advice (install.py:1300-1336): a key goes on the list for
    what it will DO - the shipped default when it has no value or a default
    one, off when it is empty, not verified when it is unknown and still
    written, low confidence when guessed."""
    obs = [Observation("a", None, "default", ""), Observation("b", "x", "default", ""),
           Observation("c", "", "derived", ""), Observation("d", "", "unknown", ""),
           Observation("e", "v", "unknown", ""), Observation("f", "w", "unknown", ""),
           Observation("g", "v", "guessed", ""), Observation("h", "w", "guessed", "")]
    assert ["still needs you", *install.closing_advice(obs)] == _closing(
        "a, b", off="c, d", unverified="e, f", weak="g, h")


def test_a_consistency_pattern_is_checked_against_what_the_file_holds(
        tmp_path: Path) -> None:
    """_pattern_matches (install.py:676-690): a manifest that is not all
    UTF-8 is still read; a pattern that does not compile, or a path that
    cannot be read, matches nothing rather than raising."""
    manifest = tmp_path / "CHANGELOG.md"
    manifest.write_bytes(b"caf\xe9\n## 1.2.3\n")
    assert install._pattern_matches(manifest, r"^##\s*(\d+\.\d+\.\d+)") is True
    assert install._pattern_matches(manifest, r"^##\s*(") is False
    assert install._pattern_matches(tmp_path, r".") is False


def test_copy_payload_names_what_the_skill_is_missing(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """install.py:741-743 and 758-760: a skill installed without its
    payload names each missing piece and still copies the rest."""
    skill = tmp_path / "skill"
    _write(skill / "payload/hooks/install", "#!/bin/sh\n")
    monkeypatch.setattr(install, "SKILL_ROOT", skill)
    repo = tmp_path / "proj"
    repo.mkdir()
    assert install.copy_payload(repo, dry_run=False, force=False) == [
        "MISSING from skill payload: payload/extant_collect.py",
        "MISSING from skill payload: payload/hooks/extant-verify",
        "MISSING from skill payload: payload/hooks/main-tree-guard",
        "copied tools/hooks/install",
        "MISSING from skill payload: payload/extant/"]
