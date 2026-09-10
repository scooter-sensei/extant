"""The four behaviour changes kept from an outside branch, each pinned here.

Everything else that branch proposed was measured and dropped. What survived
made a difference to what extant REPORTS, and a change to what a validator
reports is worth nothing unless something fails when it stops happening. Each
test below names the wrong implementation it catches.
"""
from __future__ import annotations

import io
import contextlib
import subprocess
import sys
from pathlib import Path

from conftest import _install_into

PAYLOAD = (Path(__file__).resolve().parent.parent / "plugin" / "skills"
           / "extant" / "payload")
sys.path.insert(0, str(PAYLOAD))


# --- a floor written two ways is one floor -----------------------------

def _floor_findings(git_repo, manifest: str, text: str):
    from extant import session as hc
    from extant.rules import manifest_floor as rule
    repo, commit = git_repo
    commit("pyproject.toml", manifest, "chore: manifest")
    hc._SCOPE = hc.RunScope()
    hc._DOC = hc.DocScope()
    hc._SCOPE.manifest_floors = {}
    hc.set_document(doc_path="README.md")
    try:
        return rule.check(hc.context(repo), text)
    finally:
        hc.set_document(doc_path=None)


def test_a_floor_of_3_14_agrees_with_a_manifest_saying_3_14_0(git_repo) -> None:
    """`3.14` and `3.14.0` are one floor spelled two ways.

    Comparing the parsed tuples directly made (3, 14) differ from (3, 14, 0)
    and reported a disagreement no reader could act on, because there is none.
    Catches a rule that compares tuples of unequal length without padding.
    """
    findings = _floor_findings(
        git_repo,
        '[project]\nname = "x"\nrequires-python = ">=3.14.0"\n',
        "This requires Python 3.14+.\n")
    assert findings == [], [f.detail for f in findings]


def test_padding_does_not_swallow_a_real_disagreement(git_repo) -> None:
    """The padding must not make every floor agree with every other.

    Catches the obvious over-correction - comparing only the shared prefix -
    which would silence the rule entirely.
    """
    findings = _floor_findings(
        git_repo,
        '[project]\nname = "x"\nrequires-python = ">=3.14.0"\n',
        "This requires Python 3.12+.\n")
    assert [f.kind for f in findings] == ["manifest-floor-mismatch"], findings


# --- a query string is not part of a filename --------------------------

def _link_findings(git_repo, text: str):
    from extant import session as hc
    from extant.rules import md_link as rule
    repo, commit = git_repo
    commit("notes.md", "# notes\n", "docs: a real file")
    hc._SCOPE = hc.RunScope()
    hc._DOC = hc.DocScope()
    hc.set_document(doc_path="README.md", link_base=repo)
    try:
        return rule.check(hc.context(repo), text)
    finally:
        hc.set_document(doc_path=None, link_base=None)


def test_a_link_carrying_a_query_string_resolves_to_the_file(git_repo) -> None:
    """`?raw=1` and `?plain=1` are how a forge serves a file, not its name.

    Leaving the query on the target made a file that is plainly there resolve
    to nothing, so the rule reported a working link as dead. Catches a check
    that splits on `#` but not on `?`.
    """
    findings = _link_findings(git_repo, "See [the notes](notes.md?plain=1).\n")
    assert findings == [], [f.detail for f in findings]


def test_the_query_strip_does_not_revive_a_dead_link(git_repo) -> None:
    """Catches a strip that discards the whole target rather than the query."""
    findings = _link_findings(git_repo, "See [gone](absent.md?plain=1).\n")
    assert [f.kind for f in findings] == ["dead-md-link"], findings


# --- a shallow clone answers a narrower question -----------------------

def test_is_shallow_reads_the_marker_git_writes(tmp_path: Path) -> None:
    """True only when git says so. Catches a probe that guesses, and one that
    never returns True at all - which would pass every other test here."""
    from extant.git import is_shallow
    plain = tmp_path / "plain"
    (plain / ".git").mkdir(parents=True)
    assert is_shallow(plain) is False
    (plain / ".git" / "shallow").write_text("abc\n", encoding="utf-8")
    assert is_shallow(plain) is True


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                          text=True, check=True).stdout


def test_is_shallow_agrees_with_git_on_a_real_linked_worktree(tmp_path) -> None:
    """Built from the layout git actually writes, not a plausible one.

    A linked worktree keeps its own git directory but SHARES the object store,
    and `shallow` lives in the shared one: `.git/shallow` of the clone, never
    `.git/worktrees/<name>/shallow`. The first version of this test invented
    the second shape, passed, and the real case returned False while git said
    true - the exact silent wrong answer `is_shallow` exists to prevent.

    Catches a probe that stops at the worktree's own git directory.
    """
    from extant.git import is_shallow

    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "main")
    _git(origin, "config", "user.email", "test@example.com")
    _git(origin, "config", "user.name", "Test")
    for i in range(3):
        (origin / "f.txt").write_text(f"v{i}\n", encoding="utf-8")
        _git(origin, "add", "-A")
        _git(origin, "commit", "-qm", f"c{i}")

    shallow = tmp_path / "shallow"
    _git(tmp_path, "clone", "-q", "--depth", "1",
         origin.as_uri(), str(shallow))
    _git(shallow, "worktree", "add", "-q", "--detach",
         str(tmp_path / "wt"), "HEAD")

    # git's own answer is the oracle, so the test cannot drift from reality.
    def git_says(where: Path) -> bool:
        return _git(where, "rev-parse", "--is-shallow-repository").strip() == "true"

    checked = 0
    for where in (shallow, tmp_path / "wt", origin):
        assert is_shallow(where) is git_says(where), (
            f"{where.name}: is_shallow said {is_shallow(where)}, "
            f"git says {git_says(where)}")
        checked += 1
    assert checked == 3

    # And a worktree of a FULL clone must stay False, so the fix above cannot
    # be "return True whenever a commondir exists".
    _git(origin, "worktree", "add", "-q", "--detach",
         str(tmp_path / "wt_full"), "HEAD")
    assert is_shallow(tmp_path / "wt_full") is False


def test_validate_says_so_when_the_clone_is_shallow(git_repo) -> None:
    """The denominator is only honest if its caveats print beside it.

    A `dead-sha` count from a shallow clone describes the slice that was
    cloned, not the repository. Catches a `is_shallow` nothing calls.
    """
    import extant_collect as hc
    repo, commit = git_repo
    commit("NEXT_SESSION.md", "# status\n\nNothing to see.\n", "docs: status")
    _install_into(repo)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        hc.main(["--validate", "NEXT_SESSION.md", "--repo", str(repo)])
    assert "shallow repository" not in out.getvalue() + err.getvalue()

    (repo / ".git" / "shallow").write_text("abc\n", encoding="utf-8")
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        hc.main(["--validate", "NEXT_SESSION.md", "--repo", str(repo)])
    assert "shallow repository" in out.getvalue() + err.getvalue()


# --- a survey says which machinery produced its numbers -----------------

def test_a_small_survey_runs_in_one_process_and_claims_nothing(git_repo,
                                                               capsys) -> None:
    """Below the floor there are no workers, so nothing may say there were.

    Catches a report that prints the parallel line unconditionally, which would
    make the announcement worthless.
    """
    from extant import session
    from extant.sweep import run_sweep
    repo, commit = git_repo
    for i in range(4):
        commit(f"docs/d{i}.md", f"# Doc {i}\n", f"docs: {i}")
    # `reload_config`, for the reason `_sweep_text` below gives at length: a
    # bare `CONFIG =` reaches no rule, and these fixtures configure nothing, so
    # the difference is invisible here and would stay invisible the day one of
    # them grows a `.extant.toml`.
    session.reload_config(repo)
    run_sweep(repo, "text")
    printed = capsys.readouterr().out
    assert "worker process(es)" not in printed
    assert "swept 4 markdown file(s)" in printed


def test_a_document_that_returns_no_result_is_named_not_skipped(git_repo,
                                                               capsys,
                                                               monkeypatch) -> None:
    """A survey that loses a file must not print the summary of a clean one.

    The merge looks each document up by path. A document missing from that
    mapping is the one case where a sweep can examine nothing and say nothing,
    so it is counted and named instead. Catches the bare `continue` that shape
    invites - which is exactly what the branch this came from had written.
    """
    from extant import session, sweep
    repo, commit = git_repo
    for i in range(3):
        commit(f"docs/d{i}.md", f"# Doc {i}\n\nSee `src/gone{i}.py`.\n",
               f"docs: {i}")
    session.reload_config(repo)

    real = sweep._sequential

    def losing(repo_, tasks):
        gathered = real(repo_, tasks)
        gathered.pop("docs/d1.md", None)      # the survey drops one document
        return gathered

    monkeypatch.setattr(sweep, "_sequential", losing)
    exit_code = sweep.run_sweep(repo, "text")
    printed = capsys.readouterr().out
    assert "returned no result" in printed, printed
    assert "docs/d1.md" in printed, printed
    # Printing it is half the job. A sweep that lost a document and still
    # exits 0 reports a clean run for work that did not happen, and a caller
    # reading only the exit code - which is every hook and every CI job -
    # would never learn otherwise. Catches a report without a consequence.
    assert exit_code == 1, "a survey that lost a document exited 0"


def _sweep_text(repo, capsys) -> str:
    """A survey of `repo` under `repo`'s own settings, as the CLI runs one.

    `reload_config`, not a bare `session.CONFIG = load_config(repo)`. The two
    look interchangeable and are not: every rule reads the built `Config` on
    `session._ACTIVE`, which only `_apply_config` writes, and `reload_config`
    is the public call that does both. Assigning CONFIG alone left this helper
    surveying under DEFAULTS while claiming to survey under the repository's
    configuration - so the agreement test below compared two default-configured
    runs and would have passed however badly a worker read the config.
    """
    from extant import session
    from extant.sweep import run_sweep
    session.reload_config(repo)
    run_sweep(repo, "text")
    return capsys.readouterr().out


def test_the_parallel_survey_runs_and_agrees_with_the_serial_one(git_repo,
                                                                 capsys,
                                                                 monkeypatch) -> None:
    """Above the floor the pool is used, says so, and changes no answer.

    The floor is lowered rather than four hundred documents committed, because
    what needs exercising is the dispatch, not the arithmetic that picks it.

    This is the test the branch this came from did not have: its three
    `parallel` tests asserted only on findings, which are identical either way,
    so they passed whether or not a single worker ever started. Catches a pool
    that silently falls back, and a merge that reorders or loses findings.
    """
    from extant import sweep
    repo, commit = git_repo
    for i in range(6):
        commit(f"docs/d{i}.md", f"# Doc {i}\n\nSee `src/gone{i}.py`.\n",
               f"docs: {i}")

    monkeypatch.setattr(sweep, "_PARALLEL_FLOOR", 10 ** 9)
    serial = _sweep_text(repo, capsys)
    assert "worker process(es)" not in serial

    monkeypatch.setattr(sweep, "_PARALLEL_FLOOR", 1)
    parallel = _sweep_text(repo, capsys)
    assert "worker process(es)" in parallel, parallel
    assert "could not start" not in parallel, parallel

    # The whole point of having two paths: they must produce one answer.
    strip = [ln for ln in parallel.splitlines()
             if "worker process(es)" not in ln]
    assert strip == serial.splitlines(), (
        "the parallel survey disagreed with the serial one")
    # The denominator for this test itself: six documents, six dead pointers.
    assert serial.count("[dead-path-pointer]") == 6, serial


def test_a_configured_document_under_a_dot_directory_still_gates(git_repo,
                                                                 capsys) -> None:
    """`.github/CONTRIBUTING.md` in extra_docs must be GATED, not surveyed.

    `partition_documents` normalised configured names with `.lstrip("./")`, and
    `str.lstrip` takes a CHARACTER SET rather than a prefix: the name came back
    as `github/CONTRIBUTING.md`, which matches nothing git tracks. The document
    fell into the unreviewed half, was printed under "surveyed only, not gated",
    and left the exit code at 0 - while `--verify` checked the same file and
    failed on it. Two modes disagreeing about whether a configured document
    gates is the shape this project exists to refuse, and `.github/` is the
    ordinary home for a CONTRIBUTING file.

    Nothing covered `partition_documents` before this, which is why it survived.
    """
    from extant.sweep import partition_documents
    repo, commit = git_repo
    commit(".extant.toml",
           "[extant]\nprimary_doc = \"STATUS.md\"\n"
           "extra_docs = [\".github/CONTRIBUTING.md\"]\n", "config")
    commit("STATUS.md", "# Status\n\n## Phase 1 - a thing\n\nBody.\n", "status")
    commit(".github/CONTRIBUTING.md",
           "# Contributing\n\nSee `scripts/absent.py` for the helper.\n", "doc")

    from extant import session
    session.reload_config(repo)
    paths = ["STATUS.md", ".github/CONTRIBUTING.md"]
    vetted, unvetted = partition_documents(repo, paths)
    assert ".github/CONTRIBUTING.md" in vetted, (vetted, unvetted)
    assert unvetted == [], unvetted

    printed = _sweep_text(repo, capsys)
    assert "2 configured" in printed, printed
    assert "0 unreviewed" in printed, printed


def test_a_configured_name_may_be_written_with_a_leading_dot_slash(git_repo) -> None:
    """`./STATUS.md` and `STATUS.md` must name one document everywhere.

    Four sites in this module spelled a configured name their own way - one
    stripped a leading `./`, one only turned backslashes round, and two compared
    the raw setting. That is the "one claim, two scanners" defect applied to a
    PATH: the stripping site decided the document was gated while the site that
    decides which document is PRIMARY did not recognise it, so `has_entries` was
    false for every file in the survey and every entry-scoped rule was skipped -
    reported as `0 examined` under "no document makes such claims", which is a
    wrong diagnosis of a real zero.
    """
    from extant import session
    from extant.sweep import _normalise, partition_documents
    repo, commit = git_repo
    commit(".extant.toml", "[extant]\nprimary_doc = \"./STATUS.md\"\n", "config")
    commit("STATUS.md", "# Status\n\n## Phase 1 - a thing\n\nBody.\n", "status")

    session.reload_config(repo)
    vetted, _ = partition_documents(repo, ["STATUS.md"])
    assert vetted == ["STATUS.md"], vetted
    # The half that used to disagree: the same name, as the primary test spells
    # it. Equality here is what makes `has_entries` true for the primary file.
    assert _normalise(session.CONFIG.primary_doc) == "STATUS.md"


def test_the_parallel_survey_reads_the_projects_configuration(git_repo,
                                                              capsys,
                                                              monkeypatch) -> None:
    """A worker must judge documents under the SAME settings as its parent.

    The agreement test above cannot see this and never could. It compares two
    runs of a repository that configures nothing, so both paths use the
    defaults and agree no matter what a worker reads. Every setting this
    project has is off the default path by definition, and a survey that drops
    them all still prints the summary of a healthy run.

    Catches `_worker_init` assigning `session.CONFIG` without applying it, which
    is the trap `session.context`'s own docstring names: the rules read the
    built Config on `_ACTIVE`, and only `_apply_config` writes that. Spawned
    workers rebuild `_ACTIVE` from whatever `load_config` finds beside
    `session.py` - in a pip or pre-commit install, nothing, so the defaults.

    A CUSTOM PATTERN, not a boolean this repository also sets. The first draft
    used `release_claims_name_our_tags`, and it passed against the broken code:
    a worker spawned by this suite re-imports `extant/session.py` from THIS
    checkout, whose upward search finds THIS repository's `.extant.toml`, where
    that setting is already true. It agreed by coincidence of where the tests
    run from. `REFER` appears in no default and in no configuration this
    project ships, so a worker can only report these six pointers if it is
    genuinely holding the settings its parent built.
    """
    from extant import sweep
    repo, commit = git_repo
    commit(".extant.toml",
           "[extant]\n"
           r"path_pointer = '\bREFER\b[^`\n]{0,40}`([\w./-]+\.(?:py|md|txt))`'"
           "\n", "config")
    for i in range(6):
        commit(f"docs/d{i}.md",
               f"# Doc {i}\n\nREFER to `docs/absent{i}.md` for details.\n",
               f"docs: {i}")

    monkeypatch.setattr(sweep, "_PARALLEL_FLOOR", 10 ** 9)
    serial = _sweep_text(repo, capsys)
    # The denominator for this test itself. Six documents, six pointers, and if
    # the pattern ever stops reaching even the SERIAL path this fails here
    # rather than passing by comparing two equally empty runs.
    assert serial.count("[dead-path-pointer]") == 6, serial
    assert "dead-path-pointer 6" in serial, serial

    monkeypatch.setattr(sweep, "_PARALLEL_FLOOR", 1)
    parallel = _sweep_text(repo, capsys)
    assert "worker process(es)" in parallel, parallel
    assert "could not start" not in parallel, parallel

    assert parallel.count("[dead-path-pointer]") == 6, (
        "the parallel survey lost the project's configuration:\n" + parallel)
    strip = [ln for ln in parallel.splitlines()
             if "worker process(es)" not in ln]
    assert strip == serial.splitlines(), (
        "the parallel survey disagreed with the serial one")


def test_a_pool_that_cannot_start_is_announced_not_swallowed(git_repo,
                                                             capsys,
                                                             monkeypatch) -> None:
    """Falling back is right; falling back quietly is the bug.

    A survey that drops to one process and says nothing goes on printing the
    summary of a healthy run while the machinery it reports using has stopped.
    Catches the bare `except Exception: use_parallel = False` this replaced.
    """
    import concurrent.futures

    from extant import sweep
    repo, commit = git_repo
    for i in range(4):
        commit(f"docs/d{i}.md", f"# Doc {i}\n\nSee `src/gone{i}.py`.\n",
               f"docs: {i}")

    def refuse(*args, **kwargs):
        raise OSError("spawning is not permitted here")

    monkeypatch.setattr(sweep, "_PARALLEL_FLOOR", 1)
    monkeypatch.setattr(concurrent.futures, "ProcessPoolExecutor", refuse)
    printed = _sweep_text(repo, capsys)

    assert "could not start" in printed, printed
    assert "spawning is not permitted here" in printed, printed
    # And it still surveyed everything, rather than reporting a clean repo.
    assert printed.count("[dead-path-pointer]") == 4, printed
    assert "worker process(es)" not in printed, printed
