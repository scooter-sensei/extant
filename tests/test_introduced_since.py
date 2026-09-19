"""`--introduced-since REF` gates on the claims a change WROTE, and nothing else.

The mechanism: the lines of every tracked document that the working tree
holds and the merge base of REF does not, read off one `git diff -U0`, and a
finding gates when it sits on one of them. No document is configured, no
baseline is recorded, no path is pinned - the diff is the ratchet.

Two things it deliberately does not do, and the tests below pin both. It
never gates on a claim a change BROKE without writing it - a heading removed
under another document's anchor, a file moved out from under a pointer - and
it never runs a repository-scoped rule, whose findings sit at a synthetic
line 1 that nothing wrote. `--verify` and `--sweep` own those.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PAYLOAD = (Path(__file__).resolve().parent.parent / "plugin" / "skills"
           / "extant" / "payload")
sys.path.insert(0, str(PAYLOAD))

DEAD = "dead" + "0" * 36
DEAD_TOO = "beef" + "1" * 36


def _run(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout


def _gate(repo, ref, fmt="text"):
    """Run the mode in process and hand back (exit code, stdout, stderr)."""
    from extant import session as hc
    from extant.introduced_since import run_introduced_since

    hc.reload_config(repo)
    return run_introduced_since(repo, ref, fmt)


# --- the gate ---------------------------------------------------------------

def test_a_finding_on_a_line_the_range_wrote_gates(git_repo, capsys) -> None:
    repo, commit = git_repo
    commit("docs/notes.md", "# Notes\n\nNothing here yet.\n", "docs: start")
    commit("docs/notes.md", f"# Notes\n\nNothing here yet.\n\nMerged at `{DEAD}`.\n",
           "docs: a claim")

    code = _gate(repo, "HEAD~1")
    out = capsys.readouterr().out

    assert code == 1, out
    assert "docs/notes.md: line 5: [dead-sha]" in out, out


def test_a_finding_on_a_line_the_range_did_not_touch_does_not_gate(
        git_repo, capsys) -> None:
    """The claim is still false, and the mode does not care: it was not written
    by this change. It is counted as set aside so the reader knows the
    document is not clean, only that this range did not make it dirty."""
    repo, commit = git_repo
    commit("docs/notes.md", f"# Notes\n\nMerged at `{DEAD}`.\n", "docs: old claim")
    commit("docs/notes.md", f"# Notes\n\nMerged at `{DEAD}`.\n\nA new, true line.\n",
           "docs: a harmless edit")

    code = _gate(repo, "HEAD~1")
    out = capsys.readouterr().out

    assert code == 0, out
    assert "[dead-sha]" not in out, out
    assert "1 finding(s) in the changed document(s) sit on lines the range did not touch" in out, out


def test_a_document_the_range_did_not_change_is_not_read(git_repo, capsys) -> None:
    """Only changed documents can carry an introduced line, so the others are
    not read - and the denominator says how many were left unread, because a
    gate that quietly narrowed its population would print exactly what a gate
    over the whole repository prints."""
    repo, commit = git_repo
    commit("docs/old.md", f"# Old\n\nMerged at `{DEAD}`.\n", "docs: old claim")
    commit("docs/new.md", "# New\n\nAll true.\n", "docs: a clean page")

    code = _gate(repo, "HEAD~1")
    out = capsys.readouterr().out

    assert code == 0, out
    assert "docs/old.md" not in out, out
    assert "examined 1 changed document(s) since HEAD~1" in out, out
    assert "1 tracked document(s) the range did not change were not read" in out, out


def test_the_base_is_the_merge_base_not_the_ref(git_repo, capsys) -> None:
    """On a branch that has diverged from REF, a plain `diff REF` shows every
    line REF has since deleted as a `+` line - lines this branch never wrote.
    The merge base is where the two histories fork, and only its lines are
    the branch's own."""
    repo, commit = git_repo
    commit("docs/notes.md", f"# Notes\n\nMerged at `{DEAD}`.\n", "docs: shared history")
    _run(repo, "checkout", "-q", "-b", "feature")
    commit("docs/feature.md", "# Feature\n\nAll true.\n", "docs: branch work")
    _run(repo, "checkout", "-q", "main")
    commit("docs/notes.md", "# Notes\n\nThe claim was removed on main.\n",
           "docs: main removes the claim")
    _run(repo, "checkout", "-q", "feature")

    code = _gate(repo, "main")
    out = capsys.readouterr().out

    assert code == 0, out
    assert "[dead-sha]" not in out, (
        "the dead claim main deleted was gated as if this branch had written "
        "it, so the diff is against REF rather than the merge base:\n" + out)
    assert "examined 1 changed document(s) since main" in out, out


def test_a_working_tree_edit_is_an_introduced_line(git_repo, capsys) -> None:
    """The sweep reads the working tree, so the diff has to be against the
    working tree too - against HEAD, a line added in the working tree above a
    committed claim would shift every number the diff reports."""
    repo, commit = git_repo
    commit("docs/notes.md", "# Notes\n\nA line.\n", "docs: start")
    commit("docs/notes.md", f"# Notes\n\nA line.\n\nMerged at `{DEAD}`.\n", "docs: claim")
    with open(repo / "docs/notes.md", "w", encoding="utf-8", newline="") as fh:
        fh.write(f"# Notes\n\nInserted, uncommitted.\n\nA line.\n\nMerged at `{DEAD}`.\n")

    code = _gate(repo, "HEAD~1")
    out = capsys.readouterr().out

    assert code == 1, out
    assert "docs/notes.md: line 7: [dead-sha]" in out, out


def test_a_modified_line_gates_on_what_it_already_held(git_repo, capsys) -> None:
    """A reflowed or reworded line is a `+` line, so a claim already on it is
    gated as this change's. That is the same rule GitHub's own annotations
    follow, and it is stated rather than tuned away: whoever edits a line owns
    what it says."""
    repo, commit = git_repo
    commit("docs/notes.md", f"# Notes\n\nMerged at `{DEAD}`.\n", "docs: old claim")
    commit("docs/notes.md", f"# Notes\n\nIt was merged at `{DEAD}`.\n", "docs: reword")

    code = _gate(repo, "HEAD~1")
    out = capsys.readouterr().out

    assert code == 1, out
    assert "docs/notes.md: line 3: [dead-sha]" in out, out


# --- the refusals and the empty result --------------------------------------

@pytest.mark.parametrize("fmt", ["text", "sarif"])
def test_an_unresolvable_ref_refuses_rather_than_passing(git_repo, capsys, fmt) -> None:
    """`--deleted-since` examines nothing and exits 0 on a bad ref, and that is
    right for a mode that never gates. This one gates, so a range it cannot
    compute is a run that cannot proceed: exit 2, nothing on stdout - a SARIF
    document here would assert a clean scan that never happened."""
    repo, commit = git_repo
    commit("docs/notes.md", f"# Notes\n\nMerged at `{DEAD}`.\n", "docs")

    code = _gate(repo, "no-such-ref-anywhere", fmt)
    printed = capsys.readouterr()

    assert code == 2, printed.err
    assert printed.out == "", printed.out
    assert "no-such-ref-anywhere" in printed.err, printed.err


@pytest.mark.parametrize("fmt", ["text", "sarif"])
def test_a_range_writing_no_document_is_a_result_not_a_refusal(
        git_repo, capsys, fmt) -> None:
    """`--introduced-since HEAD` wrote nothing, and saying so is an answer: the
    denominator is printed and exit is 0. SARIF still emits a document, for
    the reason `_report_empty_survey` gives - a machine consumer handed zero
    bytes fails its upload rather than reading "no results"."""
    repo, commit = git_repo
    commit("docs/notes.md", f"# Notes\n\nMerged at `{DEAD}`.\n", "docs")

    code = _gate(repo, "HEAD", fmt)
    printed = capsys.readouterr()

    assert code == 0, printed.out + printed.err
    summary = printed.err if fmt == "sarif" else printed.out
    assert "examined 0 changed document(s) since HEAD" in summary, summary
    if fmt == "sarif":
        doc = json.loads(printed.out)
        assert doc["runs"][0]["results"] == []
        assert doc["runs"][0]["automationDetails"]["id"] == "extant/introduced-since"


# --- reading the diff -------------------------------------------------------

def test_a_deleted_block_introduces_no_lines(git_repo) -> None:
    """A pure deletion is `@@ -a,b +c,0 @@`: a position and a count of zero,
    and a parser that reads the position as a line would gate on whatever
    now sits there."""
    from extant.introduced_since import introduced_lines

    repo, commit = git_repo
    commit("docs/notes.md", "# Notes\n\none\ntwo\nthree\n\nMerged at `x`.\n", "docs")
    base = commit("docs/notes.md", "# Notes\n\none\ntwo\nthree\n\nMerged at `x`.\n\ntail\n",
                  "docs: more")
    commit("docs/notes.md", "# Notes\n\n\nMerged at `x`.\n\ntail\n", "docs: delete a block")

    lines, _binary = introduced_lines(repo, base)

    assert lines.get("docs/notes.md", set()) == set(), lines


def test_added_and_modified_lines_are_numbered_in_the_new_file(git_repo) -> None:
    from extant.introduced_since import introduced_lines

    repo, commit = git_repo
    base = commit("docs/notes.md", "# Notes\n\na\nb\nc\n", "docs")
    commit("docs/notes.md", "# Notes\n\nzero\n\na\nB\nc\nd\ne\n", "docs: edit")

    lines, _binary = introduced_lines(repo, base)

    # `zero` and the blank after it (3, 4), `B` (6), `d` and `e` (8, 9).
    assert lines["docs/notes.md"] == {3, 4, 6, 8, 9}, lines


def test_a_renamed_and_edited_document_is_read_under_its_new_name(
        git_repo, capsys) -> None:
    """HEAD's tree holds the new path and so does the sweep, so the diff's
    `+++ b/` side is the name the finding has to be filed under."""
    repo, commit = git_repo
    commit("docs/old-name.md", "# Notes\n\nA line.\n", "docs")
    _run(repo, "mv", "docs/old-name.md", "docs/new-name.md")
    _run(repo, "commit", "-qm", "docs: rename")
    commit("docs/new-name.md", f"# Notes\n\nA line.\n\nMerged at `{DEAD}`.\n",
           "docs: claim in the moved file")

    code = _gate(repo, "HEAD~2")
    out = capsys.readouterr().out

    assert code == 1, out
    assert "docs/new-name.md: line 5: [dead-sha]" in out, out


def test_a_moved_document_with_no_edited_line_is_not_gated(git_repo, capsys) -> None:
    """The stated limit. A pure rename has no `+` line, so a relative link the
    move broke is a claim the change BROKE without writing - `--verify` and
    `--sweep` report it, this mode does not, and the docstring says so."""
    repo, commit = git_repo
    commit("docs/guide/page.md", "# Page\n\nSee [the readme](../README.md).\n", "docs")
    commit("README.md", "# Top\n", "docs: readme")
    (repo / "docs" / "guide" / "deeper").mkdir()
    _run(repo, "mv", "docs/guide/page.md", "docs/guide/deeper/page.md")
    _run(repo, "commit", "-qm", "docs: move the page")

    code = _gate(repo, "HEAD~1")
    out = capsys.readouterr().out

    assert code == 0, out
    assert "[dead-md-link]" not in out, out
    assert "examined 0 changed document(s)" in out, out


def test_a_c_quoted_path_is_unquoted() -> None:
    """git quotes a path holding a quote, a backslash or a control character
    the way C would, and leaves non-ASCII raw because `environment()` turns
    `core.quotePath` off. Every triggering character is illegal in a Windows
    filename, so the on-disk case can only be built on POSIX; the function is
    exercised here on both."""
    from extant.introduced_since import unquote_path

    assert unquote_path('"docs/a\\tb.md"') == "docs/a\tb.md"
    assert unquote_path('"docs/say \\"hi\\".md"') == 'docs/say "hi".md'
    assert unquote_path('"docs/back\\\\slash.md"') == "docs/back\\slash.md"
    assert unquote_path('"docs/\\101.md"') == "docs/A.md"
    # Two octal escapes reassembled into one UTF-8 character. Built with
    # chr() because the suite forbids a non-ASCII string literal anywhere.
    e_acute = chr(0xE9)
    assert unquote_path('"docs/\\303\\251.md"') == "docs/" + e_acute + ".md"
    assert unquote_path("docs/plain.md") == "docs/plain.md"
    assert unquote_path("docs/caf" + e_acute + ".md") == "docs/caf" + e_acute + ".md"


@pytest.mark.skipif(os.name == "nt", reason="a tab is illegal in a Windows filename")
def test_a_document_whose_name_git_quotes_is_still_gated(git_repo, capsys) -> None:
    repo, commit = git_repo
    commit("docs/tab\tbed.md", "# Notes\n", "docs")
    commit("docs/tab\tbed.md", f"# Notes\n\nMerged at `{DEAD}`.\n", "docs: claim")

    code = _gate(repo, "HEAD~1")
    out = capsys.readouterr().out

    assert code == 1, out
    assert "[dead-sha]" in out, out


def test_a_document_git_reads_as_binary_is_counted_not_examined(
        git_repo, capsys) -> None:
    """A NUL byte makes git call the file binary and print no hunks. The sweep
    would read it - a NUL is valid UTF-8 - so leaving it out has to be said,
    or it is a document that was silently not gated."""
    repo, commit = git_repo
    target = repo / "docs" / "odd.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"# Odd\n")
    _run(repo, "add", "docs/odd.md")
    _run(repo, "commit", "-qm", "docs: odd")
    target.write_bytes(b"# Odd\n\x00\nMerged at `" + DEAD.encode() + b"`.\n")
    _run(repo, "add", "docs/odd.md")
    _run(repo, "commit", "-qm", "docs: a NUL")

    code = _gate(repo, "HEAD~1")
    out = capsys.readouterr().out

    assert code == 0, out
    assert "1 changed document(s) git reads as binary" in out, out
    assert "docs/odd.md" in out, out


def test_a_bare_carriage_return_document_is_surveyed_not_gated(
        git_repo, capsys) -> None:
    """extant counts a bare `\\r` as a line break and git does not, so the two
    numberings diverge from that character on. Measured at 1 of 78,878 corpus
    documents - a raster fixture - so the answer is to name it, not to map
    it: its findings are surveyed and counted, and do not gate."""
    repo, commit = git_repo
    commit("docs/cr.md", "# CR\n", "docs")
    commit("docs/cr.md", f"# CR\rone\rtwo\r\nMerged at `{DEAD}`.\n", "docs: bare CR")

    code = _gate(repo, "HEAD~1")
    out = capsys.readouterr().out

    assert code == 0, out
    assert "[dead-sha]" not in out, out
    assert "1 changed document(s) hold a bare carriage return" in out, out
    assert "1 finding(s) there were surveyed and do not gate" in out, out


# --- what the denominator says ----------------------------------------------

def test_repository_rules_are_not_run_and_the_output_says_so(git_repo, capsys) -> None:
    """Their findings sit at line 1 of `.gitattributes` or `.extant.toml`, a
    line nothing wrote, so they cannot be placed on an introduced line. Not
    run, and named rather than silently absent from the examined line."""
    from extant import session as hc

    repo, commit = git_repo
    commit("docs/notes.md", "# Notes\n", "docs")
    commit("docs/notes.md", "# Notes\n\nMore.\n", "docs: edit")

    _gate(repo, "HEAD~1")
    out = capsys.readouterr().out

    skipped = [rule.kind for rule in hc.RULES if rule.scope == "repository"]
    assert skipped, "no repository-scoped rule exists to skip"
    assert f"{len(skipped)} repository-wide rule(s) not run" in out, out
    counted = next(line for line in out.splitlines()
                   if line.strip().startswith("examined:"))
    for kind in skipped:
        assert kind not in counted, (
            f"{kind} appears in the examined line although it did not run:\n{out}")


def test_exclude_paths_are_honoured_and_counted(git_repo, capsys) -> None:
    repo, commit = git_repo
    commit(".extant.toml", 'exclude_paths = ["vendor/"]\n', "config")
    commit("vendor/lib/README.md", "# Lib\n", "vendored")
    commit("vendor/lib/README.md", f"# Lib\n\nMerged at `{DEAD}`.\n", "vendored: claim")

    code = _gate(repo, "HEAD~1")
    out = capsys.readouterr().out

    assert code == 0, out
    assert "[dead-sha]" not in out, out
    assert "excluded 1 of 1 changed document(s) via 1 exclude_paths pattern(s)" in out, out


def test_a_configured_document_the_exclusions_remove_is_a_conflict(
        git_repo, capsys) -> None:
    repo, commit = git_repo
    commit(".extant.toml", 'exclude_paths = ["NEXT_SESSION.md"]\n', "config")
    commit("NEXT_SESSION.md", "# S\n", "docs")
    commit("NEXT_SESSION.md", "# S\n\nMore.\n", "docs: edit")

    code = _gate(repo, "HEAD~1")
    printed = capsys.readouterr()

    assert code == 1, printed.out + printed.err
    assert "CONFLICT" in printed.err, printed.err


def test_a_rule_that_raised_fails_the_run(git_repo, monkeypatch, capsys) -> None:
    import dataclasses

    from extant import session as hc

    repo, commit = git_repo
    commit("docs/notes.md", "# Notes\n", "docs")
    commit("docs/notes.md", "# Notes\n\nMore.\n", "docs: edit")

    def explode(ctx, text):
        raise RuntimeError("deliberate")

    broken = dataclasses.replace(hc.RULES[0], check=explode)
    monkeypatch.setattr(hc, "RULES", (broken,) + hc.RULES[1:])

    code = _gate(repo, "HEAD~1")
    out = capsys.readouterr().out

    assert code == 1, out
    assert "ERRORED" in out and broken.kind in out, out


def test_github_annotations_are_errors_on_gated_lines_only(git_repo, capsys) -> None:
    repo, commit = git_repo
    commit("docs/notes.md", f"# Notes\n\nMerged at `{DEAD}`.\n", "docs: old claim")
    commit("docs/notes.md", f"# Notes\n\nMerged at `{DEAD}`.\n\nAnd at `{DEAD_TOO}`.\n",
           "docs: new claim")

    code = _gate(repo, "HEAD~1", "github")
    out = capsys.readouterr().out

    assert code == 1, out
    annotations = [line for line in out.splitlines() if line.startswith("::")]
    assert annotations == [
        "::error file=docs/notes.md,line=5,title=dead-sha::`" + DEAD_TOO
        + "` does not resolve in this repo"], annotations


def test_the_flags_that_suppress_or_rewrite_are_refused(git_repo, capsys) -> None:
    """A baseline is a ratchet against OLD findings and this mode has none by
    construction; `--suggest-fixes` and `--sha-map` write. Refused with exit
    2 the way `--sweep` refuses them, rather than silently ignored."""
    from extant.cli import main

    repo, commit = git_repo
    commit("docs/notes.md", "# Notes\n", "docs")
    for flag in (["--baseline"], ["--write-baseline"], ["--baseline-check"],
                 ["--suggest-fixes"], ["--sha-map", "nowhere"]):
        code = main(["--introduced-since", "HEAD", "--repo", str(repo), *flag])
        printed = capsys.readouterr()
        assert code == 2, (flag, printed.out, printed.err)
        assert "--introduced-since does not support" in printed.err, (flag, printed.err)
        assert printed.out == "", (flag, printed.out)


def test_the_mode_is_reachable_through_the_command_line(git_repo, capsys) -> None:
    from extant.cli import main

    repo, commit = git_repo
    commit("docs/notes.md", "# Notes\n", "docs")
    commit("docs/notes.md", f"# Notes\n\nMerged at `{DEAD}`.\n", "docs: claim")

    code = main(["--introduced-since", "HEAD~1", "--repo", str(repo)])
    out = capsys.readouterr().out

    assert code == 1, out
    assert "[dead-sha]" in out, out


def test_a_changed_document_that_is_not_utf8_is_counted_as_unreadable(
        git_repo, capsys) -> None:
    """git diffs it happily - a latin-1 byte is text to git - so it reaches
    the survey, which cannot decode it. Named and counted, exit 0: a fact
    about the repository, not about this change."""
    repo, commit = git_repo
    commit("docs/notes.md", "# Notes\n", "docs")
    (repo / "docs" / "notes.md").write_bytes(b"# Notes\n\ncaf\xe9\n")
    _run(repo, "add", "docs/notes.md")
    _run(repo, "commit", "-qm", "docs: latin-1")

    code = _gate(repo, "HEAD~1")
    out = capsys.readouterr().out

    assert code == 0, out
    assert "1 could not be read: docs/notes.md (UnicodeDecodeError)" in out, out


def test_a_sarif_result_on_an_introduced_line_is_an_error_that_gates(
        git_repo, capsys) -> None:
    repo, commit = git_repo
    commit("docs/notes.md", "# Notes\n", "docs")
    commit("docs/notes.md", f"# Notes\n\nMerged at `{DEAD}`.\n", "docs: claim")

    code = _gate(repo, "HEAD~1", "sarif")
    printed = capsys.readouterr()

    assert code == 1, printed.err
    run = json.loads(printed.out)["runs"][0]
    assert [r["level"] for r in run["results"]] == ["error"]
    assert run["results"][0]["properties"]["gates"] is True
    assert run["results"][0]["locations"][0]["physicalLocation"]["region"]["startLine"] == 3
    assert "examined 1 changed document(s)" in printed.err, printed.err


def _shallow_copy(source: Path, into: Path, depth: int) -> Path:
    """A depth-limited copy of `source`, over the file transport."""
    subprocess.run(["git", "clone", "-q", "--depth", str(depth),
                    source.as_uri(), str(into)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=into,
                   check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=into,
                   check=True, capture_output=True)
    return into


def test_a_base_beyond_a_depth_limited_checkouts_history_refuses(
        git_repo, tmp_path, capsys) -> None:
    """The likely first bug report from CI: `actions/checkout` defaults to
    depth 1, so `HEAD~1` is not there to diff against. A refusal that names
    the depth, not a gate that examined nothing and passed."""
    repo, commit = git_repo
    commit("docs/notes.md", "# Notes\n", "docs")
    commit("docs/notes.md", f"# Notes\n\nMerged at `{DEAD}`.\n", "docs: claim")
    shallow = _shallow_copy(repo, tmp_path / "shallow", depth=1)

    code = _gate(shallow, "HEAD~1")
    printed = capsys.readouterr()

    assert code == 2, printed.out + printed.err
    assert "depth-limited" in printed.err, printed.err


def test_a_depth_limited_checkout_whose_base_is_present_says_it_is_shallow(
        git_repo, tmp_path, capsys) -> None:
    """With the base inside the depth the gate runs, and the note is what
    separates a wall of dead SHAs caused by the checkout from a document
    full of invented ones."""
    repo, commit = git_repo
    commit("docs/notes.md", "# Notes\n", "docs")
    commit("docs/notes.md", f"# Notes\n\nMerged at `{DEAD}`.\n", "docs: claim")
    shallow = _shallow_copy(repo, tmp_path / "shallow", depth=2)

    code = _gate(shallow, "HEAD~1")
    out = capsys.readouterr().out

    assert code == 1, out
    assert "NOTE: this is a shallow repository" in out, out


def test_the_mode_stays_within_its_spawn_budget(git_repo, monkeypatch) -> None:
    """Counted at the subprocess boundary, as tests/test_spawn_budget.py counts
    `--verify`, because the diff is read as bytes outside the seam.

    The budget is what one changed document holding one dead SHA costs, and
    each spawn is named so a new one has to be argued for beside it:

      merge-base   1  where the two histories fork
      diff -U0     1  the introduced lines, every changed document at once
      ls-tree      1  the tracked documents, for the unread count
      cat-file     1  the one batch of hex tokens the document holds

    Measured at 4. The shallow and partial notes cost nothing here: both
    read the repository's own files rather than asking git.
    """
    repo, commit = git_repo
    commit("docs/notes.md", "# Notes\n", "docs")
    commit("docs/notes.md", f"# Notes\n\nMerged at `{DEAD}`.\n", "docs: claim")

    spawns: list[list[str]] = []
    real = subprocess.run

    def counting(args, *rest, **kwargs):
        if args and args[0] == "git":
            spawns.append(list(args))
        return real(args, *rest, **kwargs)

    monkeypatch.setattr(subprocess, "run", counting)
    _gate(repo, "HEAD~1")

    assert len(spawns) == 4, "\n".join(" ".join(s[:4]) for s in spawns)
