"""The exit and refusal paths a coverage measurement found reached by nothing.

Measured on 2026-09-15 with every process the suite and the three harnesses
spawn instrumented: 95.0 per cent of the package's 4,065 statements, and 205
statements reached by nothing. Most of those are degraded paths - a git that
is missing, a config file that will not decode - and are recorded rather than
tested. The ones here DECIDE AN EXIT CODE or a refusal, which is the class
this project refuses to leave untested: a path that turns an errored run into
a clean one is the failure the whole tool exists to catch, and the coverage
run showed that the line doing so for a parallel survey had never executed.

Each test names the line it reaches, so the next measurement can check that
it still does.
"""
from __future__ import annotations

import io
import subprocess
import sys
import types
from pathlib import Path

import pytest

from conftest import committer, init_repo


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                          text=True, encoding="utf-8", check=True).stdout


def _clean_status(repo: Path, commit, name: str = "NEXT_SESSION.md") -> None:
    commit(name, "# Status\n\n## Phase 1 - work (done, 2026-01-01)\n\n"
                 "Nothing is claimed here.\n\n## 1. Layout\n", "docs: status")


# --- cli(): the console-script entry, executed by nothing until now ---------

@pytest.fixture
def configured_repo(git_repo):
    """A repository whose `.extant.toml` names a primary document the defaults
    do not, so a run that read the repository's config is told apart from one
    that ran on defaults by which file it says it checked."""
    repo, commit = git_repo
    commit(".extant.toml", '[extant]\nprimary_doc = "STATUS.md"\n', "chore: config")
    _clean_status(repo, commit, "STATUS.md")
    return repo


def test_cli_with_no_arguments_verifies_the_current_directory(
        configured_repo, monkeypatch, capsys) -> None:
    """cli.py: the `--verify` default and `--repo` defaulting to the cwd, then
    `reload_config(repo)` - the only route that reads the checked-out
    repository's own settings."""
    from extant import cli
    monkeypatch.chdir(configured_repo)
    monkeypatch.setattr(sys, "argv", ["extant"])
    code = cli.cli()
    out = capsys.readouterr()
    assert code == 0, out.out + out.err
    assert "checked STATUS.md" in out.out + out.err, out.out + out.err


def test_cli_accepts_repo_in_the_equals_spelling(
        configured_repo, tmp_path, monkeypatch, capsys) -> None:
    """cli.py: the `--repo=PATH` branch, from a cwd that is not the repository."""
    from extant import cli
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setattr(sys, "argv", ["extant", f"--repo={configured_repo}"])
    code = cli.cli()
    out = capsys.readouterr()
    assert code == 0, out.out + out.err
    assert "checked STATUS.md" in out.out + out.err, out.out + out.err


def test_cli_leaves_an_explicit_mode_alone(configured_repo, monkeypatch, capsys) -> None:
    """cli.py: a mode on the command line is not doubled with `--verify`."""
    from extant import cli
    monkeypatch.setattr(sys, "argv", ["extant", "--sweep", "--repo", str(configured_repo)])
    code = cli.cli()
    out = capsys.readouterr()
    assert code == 0, out.err
    assert "swept" in out.out + out.err


def test_cli_refuses_a_bare_repo_flag(configured_repo, monkeypatch, capsys) -> None:
    """cli.py: `extant --repo` with nothing after it is a parser error with
    exit 2, not an IndexError out of argv[i+1]."""
    from extant import cli
    monkeypatch.setattr(sys, "argv", ["extant", "--repo"])
    with pytest.raises(SystemExit) as stopped:
        cli.cli()
    assert stopped.value.code == 2
    assert "--repo requires a PATH" in capsys.readouterr().err


# --- a rule error inside a survey worker ------------------------------------

def _worker_outcome(tasks, errors):
    """What `survey` returns when workers ran: every task answered, each
    carrying `errors` the way `_validate_chunk` attaches them."""
    return ({relative: ([], None, {}, list(errors), False)
             for relative, _primary in tasks},
            2, None)


def test_a_rule_error_reported_by_a_sweep_worker_fails_the_run(
        git_repo, monkeypatch, capsys) -> None:
    """sweep.py: `if workers and errors: RULE_ERRORS.extend(errors)`.

    Workers are spawned and re-import the real rules, so a raise cannot be
    injected into one from here; what is pinned is the parent's handling of
    what a worker reports. Delete that line and a rule that crashed in a
    worker prints a clean survey and exits 0.
    """
    from extant import sweep
    from extant.registry import RULE_ERRORS
    repo, commit = git_repo
    commit("docs/a.md", "# A\n", "docs: a")
    monkeypatch.setattr(sweep, "survey", lambda repo, tasks, tracked=None: _worker_outcome(
        tasks, [("dead-sha", "RuntimeError: boom")]))
    before = len(RULE_ERRORS)
    try:
        code = sweep.run_sweep(repo, "text")
        out = capsys.readouterr()
        assert RULE_ERRORS[before:] == [("dead-sha", "RuntimeError: boom")]
    finally:
        del RULE_ERRORS[before:]
    assert code == 1, out.out + out.err
    assert "dead-sha" in out.out + out.err and "RuntimeError" in out.out + out.err


def test_a_rule_error_reported_by_an_introduced_since_worker_fails_the_run(
        git_repo, monkeypatch, capsys) -> None:
    """introduced_since.py: the same line in the other survey."""
    from extant import introduced_since
    from extant.registry import RULE_ERRORS
    repo, commit = git_repo
    commit("docs/a.md", "# A\n", "docs: a")
    commit("docs/a.md", "# A\n\nMore.\n", "docs: more")
    monkeypatch.setattr(introduced_since, "survey", lambda repo, tasks: _worker_outcome(
        tasks, [("dead-sha", "RuntimeError: boom")]))
    before = len(RULE_ERRORS)
    try:
        code = introduced_since.run_introduced_since(repo, "HEAD~1", "text")
        out = capsys.readouterr()
        assert RULE_ERRORS[before:] == [("dead-sha", "RuntimeError: boom")]
    finally:
        del RULE_ERRORS[before:]
    assert code == 1, out.out + out.err
    assert "dead-sha" in out.out + out.err


def test_a_document_a_worker_never_returned_is_named_and_gates(
        git_repo, monkeypatch, capsys) -> None:
    """sweep.py: a document dispatched to the pool and absent from what came
    back is not a document with no findings."""
    from extant import sweep
    repo, commit = git_repo
    commit("docs/a.md", "# A\n", "docs: a")
    monkeypatch.setattr(sweep, "survey", lambda repo, tasks, tracked=None: ({}, 2, None))
    code = sweep.run_sweep(repo, "text")
    out = capsys.readouterr()
    assert code == 1
    assert "returned no result" in out.out + out.err and "docs/a.md" in out.out + out.err


# --- the two refusals of --introduced-since ----------------------------------

def test_introduced_since_refuses_when_the_diff_needs_an_object_it_cannot_get(
        tmp_path, capsys) -> None:
    """introduced_since.py: `git diff` fails -> exit 2, named.

    The real shape: a `blob:none` clone whose base version of the changed
    document was never transported, under the environment that refuses the
    lazy fetch. Nothing is monkeypatched.
    """
    from extant import introduced_since
    source = tmp_path / "source"
    init_repo(source)
    commit = committer(source)
    commit("docs/a.md", "# A\n\nOne.\n", "docs: one")
    commit("docs/a.md", "# A\n\nTwo.\n", "docs: two")
    git(source, "config", "uploadpack.allowFilter", "true")
    partial = tmp_path / "partial"
    subprocess.run(["git", "clone", "-q", "--filter=blob:none",
                    "file://" + source.as_posix(), str(partial)],
                   check=True, capture_output=True)
    code = introduced_since.run_introduced_since(partial, "HEAD~1", "text")
    err = capsys.readouterr().err
    assert code == 2, err
    assert "git diff against" in err and "failed" in err, err


def test_introduced_since_refuses_when_heads_tree_cannot_be_listed(
        git_repo, monkeypatch, capsys) -> None:
    """introduced_since.py: `tracked_markdown` raises -> exit 2, named. No
    real state fails `ls-tree` after a diff has succeeded, so the raise is
    injected at the function that documents why it raises."""
    from extant import introduced_since, refs
    repo, commit = git_repo
    commit("docs/a.md", "# A\n", "docs: a")
    commit("docs/a.md", "# A\n\nMore.\n", "docs: more")

    def cannot_list(ctx):
        raise subprocess.CalledProcessError(128, ["git", "ls-tree"])

    monkeypatch.setattr(refs, "tracked_markdown", cannot_list)
    code = introduced_since.run_introduced_since(repo, "HEAD~1", "text")
    err = capsys.readouterr().err
    assert code == 2, err
    assert "cannot list HEAD's tree" in err, err


# --- --check-text: no stdin, an unreadable baseline --------------------------

def test_check_text_with_no_usable_stdin_is_reported_and_exits_one(
        git_repo, monkeypatch, capsys) -> None:
    """gate.py: `_read_stdin` catching AttributeError -> None -> exit 1."""
    from extant import cli
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    monkeypatch.setattr(sys, "stdin", None)
    code = cli.main(["--check-text", "--repo", str(repo)])
    out = capsys.readouterr()
    assert code == 1, out.out + out.err
    assert "could not read stdin" in out.out + out.err


def test_check_text_with_an_unreadable_baseline_exits_two(
        git_repo, tmp_path, monkeypatch, capsys) -> None:
    """gate.py: `_open_baseline` declining -> exit 2. A MISSING baseline is
    deliberately an empty one; an unreadable one is refused."""
    from extant import cli
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", types.SimpleNamespace(buffer=io.BytesIO(b"# Draft\n")))
    code = cli.main(["--check-text", "--repo", str(repo), "--baseline", str(bad)])
    err = capsys.readouterr().err
    assert code == 2, err


# --- --selftest on a document that is not text --------------------------------

def test_selftest_refuses_a_primary_document_that_is_not_utf8(
        git_repo, capsys) -> None:
    """cli.py: `run_selftest` reporting the decode failure -> exit 1, rather
    than running every probe against replaced bytes."""
    from extant import cli
    repo, _commit = git_repo
    (repo / "NEXT_SESSION.md").write_bytes(b"# Status\n\n\xff\xfe not text\n")
    git(repo, "add", "NEXT_SESSION.md")
    git(repo, "commit", "-q", "-m", "docs: bytes")
    code = cli.main(["--selftest", "--repo", str(repo)])
    err = capsys.readouterr().err
    assert code == 1, err
    assert "not valid UTF-8" in err


# --- the answer of last resort ------------------------------------------------

def test_reachable_from_a_ref_that_does_not_resolve_falls_back_to_merge_base(
        git_repo, monkeypatch) -> None:
    """refs.py: no index for the ref -> one `merge-base --is-ancestor` -> False.

    Unreachable from every rule by construction - `_merge_sites` drops a claim
    whose ref does not resolve, `integration_refs` keeps only refs that do -
    so this is the only caller the path has, and the only thing that would
    notice it answering True.
    """
    from extant import refs
    from extant import session as hc
    from extant.git import CountingGit, SubprocessGit
    repo, commit = git_repo
    sha = commit("a.py", "a = 1\n", "feat: a")
    counting = CountingGit(SubprocessGit())
    monkeypatch.setattr(hc, "_GIT", counting)
    with hc.run_scope():
        assert refs.reachable_from(hc.context(repo), sha, "no-such-ref") is False
    asked = [c for c in counting.calls if c[:2] == ("merge-base", "--is-ancestor")]
    assert asked == [("merge-base", "--is-ancestor", sha, "no-such-ref")]
