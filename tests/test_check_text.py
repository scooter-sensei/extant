"""`--check-text`: the same checks, over a document that need not be on disk.

The primitive under any caller holding a draft - a write hook handing back what
a model just produced, a harness, an editor. It carries no assumption of its
own, which is why it could be built before anything that measures whether such
a caller is worth having.

The risk it does carry has a name, and most of this file is about it. A
document with no path is a NARROWER question than `--validate` asks: rules that
key on the filename cannot answer, relative links have nothing to resolve
against but the repository root, and the markup language falls back to
markdown. Narrowing quietly is the failure this whole tool exists to refuse, so
`--as-path` supplies the location and its absence is stated in the output
rather than left for the reader to infer from a denominator that looks clean.

Run as a SUBPROCESS throughout, because stdin is the thing under test and a
function call cannot exercise it.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import _install_into

PAYLOAD = (Path(__file__).resolve().parent.parent / "plugin" / "skills"
           / "extant" / "payload")
sys.path.insert(0, str(PAYLOAD))


def check_text(repo: Path, document: str, *args: str,
               raw: bytes | None = None) -> subprocess.CompletedProcess:
    """Run `--check-text` against `repo`, feeding `document` on stdin."""
    tools = _install_into(repo)
    payload = raw if raw is not None else document.encode("utf-8")
    return subprocess.run(
        [sys.executable, str(tools / "extant_collect.py"), "--check-text",
         "--repo", str(repo), *args],
        input=payload, capture_output=True, timeout=180,
    )


def output(done: subprocess.CompletedProcess) -> str:
    return (done.stdout + done.stderr).decode("utf-8", errors="replace")


# --- the mode does what --validate does ---------------------------------------

def test_a_false_claim_on_stdin_is_reported_and_gates(git_repo) -> None:
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    done = check_text(repo, "The fix landed in `abc1234f`.\n")
    assert done.returncode == 1, output(done)
    assert "dead-sha" in output(done)
    assert "abc1234f" in output(done)


def test_a_document_with_nothing_wrong_exits_zero(git_repo) -> None:
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    done = check_text(repo, "Nothing checkable is written here.\n")
    assert done.returncode == 0, output(done)


def test_a_live_sha_on_stdin_produces_no_finding(git_repo) -> None:
    """The other half of the first test, and not redundant with it.

    A mode that reported everything would pass the first test while being
    useless, which is the shape `--selftest` exists to catch one level down.
    """
    repo, commit = git_repo
    live = commit("a.py", "a = 1\n", "feat: a").strip()
    done = check_text(repo, f"The fix landed in `{live[:9]}`.\n")
    assert done.returncode == 0, output(done)


def test_the_denominator_is_printed_for_every_rule(git_repo) -> None:
    """"Nothing found" and "nothing checked" must not look alike here either.

    This is the promise the whole tool is built on, and a new mode is exactly
    where it gets dropped: the findings come out right and the summary line is
    forgotten, so a caller reading zero results cannot tell which zero it is.
    """
    from extant.registry import RULES
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    text = output(check_text(repo, "Nothing here.\n"))
    assert "checked <stdin>:" in text, text
    for rule in RULES:
        assert rule.kind in text, f"{rule.kind} missing from the denominator"


# --- the narrowing that must never be silent ----------------------------------

def test_without_as_path_the_narrower_question_is_stated(git_repo) -> None:
    """The one thing this mode could get quietly wrong.

    Without a path the filename-keyed rules report 0 examined, which is
    indistinguishable from "this document makes no such claims" unless
    something says otherwise. A reader who cannot tell those apart has the
    denominator without the meaning of it.
    """
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    text = output(check_text(repo, "Nothing here.\n"))
    assert "no --as-path" in text, text
    assert "key on the filename" in text


def test_with_as_path_the_note_is_absent(git_repo) -> None:
    """The other direction: a mode that always warns trains its reader to skip.

    Without this, the fix above could be "print the note unconditionally",
    which is the failure mode that gets a diagnostic filtered out of the log.
    """
    repo, commit = git_repo
    commit("STATUS.md", "# Status\n", "docs: status")
    text = output(check_text(repo, "Nothing here.\n", "--as-path", "STATUS.md"))
    assert "no --as-path" not in text, text


def test_as_path_decides_what_a_relative_link_resolves_against(git_repo) -> None:
    """A link is relative to its DOCUMENT, so a document with no location
    cannot resolve one the way the same text on disk would.

    `docs/plan.md` linking to `notes.md` means `docs/notes.md`. Resolved from
    the repository root instead it means `notes.md`, and the rule then reports
    a dead link for a file that is there - or misses one that is not.
    """
    repo, commit = git_repo
    commit("docs/notes.md", "# Notes\n", "docs: notes")
    body = "See [notes](notes.md).\n"

    with_path = check_text(repo, body, "--as-path", "docs/plan.md")
    assert with_path.returncode == 0, output(with_path)

    without = check_text(repo, body)
    assert "dead-md-link" in output(without)
    assert without.returncode == 1, (
        "resolved a document-relative link against the repository root and "
        "still called it fine")


def test_as_path_decides_the_markup_language(git_repo) -> None:
    """`[text](url)` is markdown and nothing else.

    In reStructuredText that shape occurs in ordinary Python - numpy writes
    `np.dtype[mp.mpf](dps=100)` in a doctest - so every match is false by
    construction. `rule_applies` skips the markdown-only rules whenever the
    format is not markdown, and nothing but the filename says which it is.
    """
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    body = "Call ``np.dtype[mp.mpf](dps=100)`` to widen it.\n"

    as_rst = output(check_text(repo, body, "--as-path", "docs/guide.rst"))
    assert "dead-md-link 0" in as_rst or "dead-md-link" not in as_rst, as_rst
    assert "[dead-md-link]" not in as_rst, (
        "ran a markdown-only rule over reStructuredText: " + as_rst)


def test_as_path_is_refused_rather_than_ignored_without_check_text(git_repo) -> None:
    """A flag that cannot apply must say so, not evaporate.

    `--validate` already knows where its file is, so an `--as-path` beside it
    is a caller believing they supplied something. Silently dropping it is how
    a caller learns the wrong thing about what ran.
    """
    repo, commit = git_repo
    commit("STATUS.md", "# Status\n", "docs: status")
    tools = _install_into(repo)
    done = subprocess.run(
        [sys.executable, str(tools / "extant_collect.py"), "--verify",
         "--repo", str(repo), "--as-path", "other.md"],
        capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert done.returncode == 2, done.stdout + done.stderr
    assert "--as-path applies to --check-text" in done.stdout + done.stderr


# --- what it must NOT do ------------------------------------------------------

def test_it_writes_no_file_even_when_given_a_sha_map(git_repo) -> None:
    """`--sha-map` REWRITES a document, and there is no document to rewrite.

    The translation still applies in memory, so the findings match what the
    repaired text would produce - but a mode reading from stdin that touched
    the working tree would be authoring, which is the boundary this tool's
    authority rests on.
    """
    repo, commit = git_repo
    live = commit("a.py", "a = 1\n", "feat: a").strip()
    doc = repo / "STATUS.md"
    doc.write_text("# untouched\n", encoding="utf-8")
    mapping = repo / "commit-map"
    mapping.write_text(f"{'abc1234' + '0' * 33} {live}\n", encoding="utf-8")

    # Snapshotted AFTER the install, not before: `_install_into` creates
    # tools/, and a listing taken first would record the HARNESS writing to
    # the repository and report it as the tool having done so.
    _install_into(repo)
    before = sorted(p.name for p in repo.iterdir())
    done = check_text(repo, "Landed in `abc1234`.\n", "--sha-map", str(mapping),
                      "--as-path", "STATUS.md")

    assert doc.read_text(encoding="utf-8") == "# untouched\n"
    assert sorted(p.name for p in repo.iterdir()) == before
    assert "writes no file" in output(done), output(done)


def test_stdin_that_is_not_utf8_is_reported_not_silently_replaced(git_repo) -> None:
    """Decoding with errors="replace" would run every rule over corrupted text.

    The findings would then be about bytes that are not there, which is worse
    than refusing: it is a confident answer to a question nobody asked.
    `--validate` refuses the same way for a file.
    """
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    done = check_text(repo, "", raw=b"\xff\xfe not utf-8 \x00\x01")
    assert done.returncode == 1
    assert "not valid UTF-8" in output(done), output(done)


def test_suggest_fixes_without_a_path_says_why(git_repo) -> None:
    """A patch names the file it applies to, so it needs one.

    Emitting a diff headed with an invented filename would produce something
    `git apply` accepts and applies to the wrong file.
    """
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    done = check_text(repo, "See [x](gone.md).\n", "--suggest-fixes")
    assert "needs --as-path" in output(done), output(done)


# --- the promises shared with --validate --------------------------------------

def test_the_baseline_suppresses_and_says_how_much(git_repo) -> None:
    """A baseline that hides its own size is the denominator failure again.

    Wired through the same `Collector` as `--validate`, and this is what pins
    that: a second implementation would be the place the suppressed count gets
    forgotten.
    """
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    body = "The fix landed in `abc1234f`.\n"
    # Recorded through `--verify`, which is the only mode allowed to write one:
    # a baseline written from a single piped document would discard everything
    # the project had already forgiven. See the refusal test below.
    (repo / "NEXT_SESSION.md").write_text(body, encoding="utf-8")
    tools = _install_into(repo)
    recorded = subprocess.run(
        [sys.executable, str(tools / "extant_collect.py"), "--verify",
         "--repo", str(repo), "--write-baseline"],
        capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert recorded.returncode == 0, recorded.stdout + recorded.stderr
    assert (repo / ".extant-baseline.json").is_file()

    again = check_text(repo, body, "--as-path", "NEXT_SESSION.md", "--baseline")
    assert again.returncode == 0, output(again)
    assert "suppressed by" in output(again), output(again)
    assert "0 new finding(s)" in output(again), output(again)


def test_sarif_carries_the_denominator_and_nothing_else_is_on_stdout(git_repo) -> None:
    """SARIF must be the only thing on stdout or it is not parseable JSON.

    Every human diagnostic moves to stderr in that mode, and a new mode is
    where that gets missed - the summary line is printed the way it is
    everywhere else and the document stops being SARIF.
    """
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    # With `--as-path`, which SARIF requires here: every result is located by
    # a URI and a document with no path has none. See the refusal test below.
    done = check_text(repo, "The fix landed in `abc1234f`.\n",
                      "--format=sarif", "--as-path", "docs/plan.md")
    document = json.loads(done.stdout.decode("utf-8"))
    run = document["runs"][0]
    assert run["results"], "no results in the SARIF"
    examined = run["properties"]["examined"]
    assert "dead-sha" in examined, examined
    # And in prose beside it, because a reader of the notifications sees those
    # rather than the properties bag.
    notes = " ".join(note["message"]["text"] for note
                     in run["invocations"][0]["toolExecutionNotifications"])
    assert "examined:" in notes, notes


def test_github_annotations_name_the_document(git_repo) -> None:
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    named = output(check_text(repo, "Landed in `abc1234f`.\n",
                              "--format=github", "--as-path", "docs/plan.md"))
    assert "file=docs/plan.md" in named, named
    anonymous = output(check_text(repo, "Landed in `abc1234f`.\n",
                                  "--format=github"))
    assert "file=<stdin>" in anonymous, anonymous


def test_entry_scoped_rules_are_not_tied_to_as_path(git_repo) -> None:
    """Whether a document has dated entries is a property of the TEXT.

    Written first as `has_entries=bool(--as-path)`, which is wrong: a status
    document piped in without a path still has entries, and switching two
    rules off because no filename was supplied is a silent narrowing wearing
    the costume of a default.
    """
    from extant.registry import RULES
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    entry_scoped = [r.kind for r in RULES if r.scope == "newest-entry"]
    if not entry_scoped:
        pytest.skip("no entry-scoped rules to check")
    text = output(check_text(repo, "Nothing here.\n"))
    for kind in entry_scoped:
        assert kind in text, (
            f"{kind} vanished from the denominator when no --as-path was "
            f"given: {text}")


# --- what a gap audit found, each with the damage it did ----------------------

def test_it_refuses_to_write_a_baseline_over_the_projects_own(git_repo) -> None:
    """Measured destroying one: two entries became one, and the run exited 0.

    `--write-baseline` records what THIS run found and replaces the file. Over
    one piped document that is one document's findings, keyed on `<stdin>` or
    on an asserted path, written on top of a baseline recorded from the whole
    project. The next `--verify --baseline` then reported "2 new finding(s), 0
    suppressed" - the amnesty gone, nothing anywhere saying so, exit code 0.
    """
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    doc = repo / "NEXT_SESSION.md"
    doc.write_text("# Status\n\nLanded in `abc1234f`.\nSee [x](gone.md).\n",
                   encoding="utf-8")
    tools = _install_into(repo)
    real = subprocess.run(
        [sys.executable, str(tools / "extant_collect.py"), "--verify",
         "--repo", str(repo), "--write-baseline"],
        capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert real.returncode == 0, real.stdout + real.stderr
    baseline = repo / ".extant-baseline.json"
    recorded = json.loads(baseline.read_text(encoding="utf-8"))["findings"]
    assert recorded, "the fixture recorded no baseline to protect"

    done = check_text(repo, "Landed in `beef9999`.\n", "--write-baseline")

    assert done.returncode == 2, output(done)
    assert "--check-text does not support" in output(done)
    after = json.loads(baseline.read_text(encoding="utf-8"))["findings"]
    assert after == recorded, "the project's baseline was overwritten"


def test_it_refuses_to_judge_a_baseline_it_cannot_see(git_repo) -> None:
    """Measured calling live entries STALE and advising their deletion.

    `--baseline-check` asks which recorded entries this RUN did not encounter.
    `--verify` reads the primary document, the archive and every extra_doc, so
    that answer means something. A run over one piped document encounters
    almost nothing, so every real entry came back STALE under "These no longer
    happen ... Remove them" - advice which, followed, deletes suppressions that
    are still needed and turns CI red.
    """
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    (repo / "NEXT_SESSION.md").write_text("Landed in `abc1234f`.\n",
                                          encoding="utf-8")
    tools = _install_into(repo)
    subprocess.run([sys.executable, str(tools / "extant_collect.py"), "--verify",
                    "--repo", str(repo), "--write-baseline"],
                   capture_output=True, timeout=180)

    done = check_text(repo, "Nothing checkable here.\n", "--baseline-check")

    assert done.returncode == 2, output(done)
    assert "STALE" not in output(done), (
        "reported the project's live baseline entries as stale")


def test_reading_a_baseline_is_still_allowed(git_repo) -> None:
    """The other direction: refusing all three would break the useful case.

    A caller checking a draft wants what the project already forgave applied
    to it. Only the flags that WRITE or JUDGE the recorded set are refused.
    """
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    body = "Landed in `abc1234f`.\n"
    recorded = check_text(repo, body, "--as-path", "STATUS.md",
                          "--write-baseline")
    assert recorded.returncode == 2, "the write path should be refused"
    # Record it the supported way, then read it here.
    (repo / "NEXT_SESSION.md").write_text(body, encoding="utf-8")
    tools = _install_into(repo)
    subprocess.run([sys.executable, str(tools / "extant_collect.py"), "--verify",
                    "--repo", str(repo), "--write-baseline"],
                   capture_output=True, timeout=180)
    done = check_text(repo, body, "--as-path", "NEXT_SESSION.md", "--baseline")
    assert done.returncode == 0, output(done)
    assert "suppressed by" in output(done), output(done)


def test_sarif_without_a_path_is_refused_rather_than_made_invalid(git_repo) -> None:
    """`<stdin>` is not a URI, and SARIF requires one.

    Measured: `artifactLocation.uri` came out as `<stdin>`, and `<` and `>` are
    characters RFC 3986 forbids. A code-scanning upload can reject the whole
    document, so every finding in it disappears - the silent failure, one layer
    out. Not papered over with a name like `stdin` either: that would be a
    valid URI pointing at a file which does not exist, which is the wrong
    answer wearing a better disguise.
    """
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    done = check_text(repo, "Landed in `abc1234f`.\n", "--format=sarif")
    assert done.returncode == 2, output(done)
    assert "needs --as-path" in output(done)

    named = check_text(repo, "Landed in `abc1234f`.\n", "--format=sarif",
                       "--as-path", "docs/plan.md")
    document = json.loads(named.stdout.decode("utf-8"))
    uris = [r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
            for r in document["runs"][0]["results"]]
    assert uris == ["docs/plan.md"], uris
    for uri in uris:
        assert not set(uri) & set("<>\"{}|\\^` "), f"{uri!r} is not a URI"


def test_nothing_on_stdin_is_reported_rather_than_reported_clean(git_repo) -> None:
    """An empty document printed every rule at 0 and exited 0.

    Which is "nothing was checked" wearing the exact appearance of "nothing was
    wrong" - the one conflation this tool exists to remove, reintroduced by its
    newest mode. And it is the LIKELY failure here rather than an exotic one:
    this mode is fed through a pipe from hooks and harnesses, and a pipe that
    delivers nothing is a plumbing mistake.
    """
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    for empty in (b"", b"   \n\n  \t\n"):
        done = check_text(repo, "", raw=empty)
        assert done.returncode != 0, (
            f"an empty document exited 0: {output(done)!r}")
        assert "nothing arrived on stdin" in output(done), output(done)


def test_as_path_must_stay_inside_the_repository(git_repo) -> None:
    """Measured accepting `../../../etc/passwd` and printing it as the name.

    An asserted path is a claim about where the document would live. One that
    leaves the repository is a claim the rest of the run cannot honour:
    relative links resolve against a directory git knows nothing about, and
    every finding carries a location meaningless to any reader or consumer.
    """
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    for escaping in ("../outside.md", "docs/../../outside.md", "/etc/passwd",
                     "C:/Windows/win.ini"):
        done = check_text(repo, "Nothing here.\n", "--as-path", escaping)
        assert done.returncode == 2, f"accepted {escaping!r}: {output(done)}"
        assert "inside the repository" in output(done)
    ok = check_text(repo, "Nothing here.\n", "--as-path", "docs/plan.md")
    assert ok.returncode == 0, output(ok)


def test_both_gating_modes_share_one_tail(git_repo) -> None:
    """Structural, because the drift would be invisible in any single run.

    `--validate` and `--check-text` make the same promises about output: the
    machine formats, the suppressed count, and a raised rule never exiting 0.
    Two copies of that would answer differently one day, and the day would be
    whichever one nobody tested.
    """
    import inspect

    from extant import gate

    for mode in (gate.run_validate, gate.run_check_text):
        body = inspect.getsource(mode)
        assert "_finish(" in body, (
            f"{mode.__name__} stopped sharing the output tail, so the two "
            f"gating modes can now answer differently")
