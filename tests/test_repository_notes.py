"""What the checkout is, said in every mode that counts, and the third note.

Three notes describe the repository beside a mode's denominators, because
each changes what a count means: a shallow repository (older SHAs read dead),
a partial one (objects left out stay out), and - since tranche 10 of the
internals review - an ancestry index that reached its bound in a repository
without a commit-graph, where every question past the bound was settled by
walking. `--verify`, `--check-text` and `--introduced-since` printed the
first two; `--sweep`, the mode most often pointed at a stranger's repository,
printed neither. The third exists because the gap was measured at 7.5x on the
index, 27x on the batch and 77x on `merge-base` and then not built, since the
only deterministic trigger is a fact of the run scope and the notes printed
after that scope had closed.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from test_introduced_since import _shallow_copy
from test_partial_repository import partial_repo  # noqa: F401 - a fixture


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True,
                          capture_output=True, text=True, encoding="utf-8").stdout


def _notes(out: str, word: str) -> list[str]:
    return [line for line in out.splitlines() if "NOTE:" in line and word in line]


# --- the two notes --sweep never printed --------------------------------------

def test_sweep_says_the_repository_is_partial(partial_repo, capsys) -> None:  # noqa: F811
    """The same sentence `--verify` prints, once, beside the denominators."""
    from extant import session as hc
    from extant import sweep
    hc.reload_config(partial_repo)

    sweep.run_sweep(partial_repo, "text")
    out = capsys.readouterr().out

    assert len(_notes(out, "partial")) == 1, out


def test_sweep_says_the_repository_is_shallow(git_repo, tmp_path, capsys) -> None:
    from extant import session as hc
    from extant import sweep
    repo, commit = git_repo
    commit("docs/notes.md", "# Notes\n", "docs")
    commit("docs/notes.md", "# Notes\n\nMerged at `0123456789ab`.\n", "docs: claim")
    shallow = _shallow_copy(repo, tmp_path / "shallow", depth=1)
    hc.reload_config(shallow)

    sweep.run_sweep(shallow, "text")
    out = capsys.readouterr().out

    assert len(_notes(out, "shallow")) == 1, out


# --- the commit-graph note ----------------------------------------------------

def _release_history(git_repo):
    """Three commits on main, a tag on the first, and a document that claims
    the release - which is what makes the release rule ask ancestry and build
    the index."""
    repo, commit = git_repo
    first = commit("a.py", "a = 1\n", "feat: a")
    commit("b.py", "b = 1\n", "feat: b")
    git(repo, "tag", "v1.0.0", first)
    commit("NEXT_SESSION.md",
           "# Status\n\n## Phase 1 - work (in progress, 2026-01-01)\n\n"
           "Shipped in v1.0.0.\n\n## 1. Layout\n", "docs: status")
    return repo


def test_verify_notes_an_index_past_the_bound_without_a_commit_graph(
        git_repo, monkeypatch, capsys) -> None:
    """The deterministic trigger: the index came back incomplete, and the
    repository has no commit-graph to make the walk past it cheap."""
    from extant import cli, refs
    repo = _release_history(git_repo)
    monkeypatch.setattr(refs, "INDEX_BOUND", 1)

    cli.main(["--verify", "--repo", str(repo)])
    out = capsys.readouterr().out

    notes = _notes(out, "commit-graph")
    assert len(notes) == 1, out
    assert "git commit-graph write --reachable" in notes[0]


def test_no_note_once_the_repository_has_a_commit_graph(
        git_repo, monkeypatch, capsys) -> None:
    from extant import cli, refs
    repo = _release_history(git_repo)
    git(repo, "commit-graph", "write", "--reachable")
    monkeypatch.setattr(refs, "INDEX_BOUND", 1)

    cli.main(["--verify", "--repo", str(repo)])
    out = capsys.readouterr().out

    assert _notes(out, "commit-graph") == [], out


def test_no_note_when_the_index_held_the_whole_history(git_repo, capsys) -> None:
    """The default bound covers this history, so nothing was walked."""
    from extant import cli
    repo = _release_history(git_repo)

    cli.main(["--verify", "--repo", str(repo)])
    out = capsys.readouterr().out

    assert _notes(out, "commit-graph") == [], out


def test_no_note_when_no_rule_asked_ancestry(git_repo, monkeypatch, capsys) -> None:
    """A bound the history exceeds is not the trigger; an index that was BUILT
    and came back incomplete is. A document with no release, merge or live
    claim builds none."""
    from extant import cli, refs
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    commit("b.py", "b = 1\n", "feat: b")
    commit("NEXT_SESSION.md",
           "# Status\n\n## Phase 1 - work (in progress, 2026-01-01)\n\n"
           "See `a.py`.\n\n## 1. Layout\n", "docs: status")
    monkeypatch.setattr(refs, "INDEX_BOUND", 1)

    cli.main(["--verify", "--repo", str(repo)])
    out = capsys.readouterr().out

    assert _notes(out, "commit-graph") == [], out


def test_sweep_notes_an_index_past_the_bound(git_repo, monkeypatch, capsys) -> None:
    """The sequential survey shares the parent's scope, so the flag is read
    from it after the documents are done."""
    from extant import refs, session as hc, sweep
    repo = _release_history(git_repo)
    monkeypatch.setattr(refs, "INDEX_BOUND", 1)
    monkeypatch.setattr(sweep, "_PARALLEL_FLOOR", 10 ** 9)
    hc.reload_config(repo)

    sweep.run_sweep(repo, "text")
    out = capsys.readouterr().out

    assert len(_notes(out, "commit-graph")) == 1, out


def test_sweep_carries_the_flag_a_worker_reports(git_repo, monkeypatch, capsys) -> None:
    """Workers re-import the real modules, so a low bound set here never
    reaches one; what is pinned is that the parent reads the flag a worker
    hands back and prints the note. Drop the flag from the tuple and a
    parallel survey of a large repository never says so."""
    from extant import session as hc, sweep
    repo, commit = git_repo
    commit("docs/a.md", "# A\n", "docs: a")
    commit("docs/b.md", "# B\n", "docs: b")
    hc.reload_config(repo)

    # Only the FIRST document's worker saw an incomplete index. The flags
    # are OR-ed, so a parent that kept the last one would print nothing.
    def worker_survey(repo, tasks, tracked=None):
        return ({relative: ([], None, {}, [], index == 0)
                 for index, (relative, _p) in enumerate(tasks)},
                2, None)

    monkeypatch.setattr(sweep, "survey", worker_survey)

    sweep.run_sweep(repo, "text")
    out = capsys.readouterr().out

    assert len(_notes(out, "commit-graph")) == 1, out


def test_introduced_since_notes_an_index_past_the_bound(
        git_repo, monkeypatch, capsys) -> None:
    """The gate prints the repository notes after its own survey; the flag
    has to reach it the same way."""
    from extant import refs, session as hc
    from extant.introduced_since import run_introduced_since
    repo = _release_history(git_repo)
    monkeypatch.setattr(refs, "INDEX_BOUND", 1)
    hc.reload_config(repo)

    run_introduced_since(repo, "HEAD~1", "text")
    out = capsys.readouterr().out

    assert len(_notes(out, "commit-graph")) == 1, out


def test_a_commit_graph_is_found_by_stat_in_either_spelling(git_repo) -> None:
    """`objects/info/commit-graph` is what `write` leaves; `--split` leaves a
    chain under `commit-graphs/`. Both are one stat on the shared git
    directory, so a linked worktree finds the same file."""
    from extant.git import has_commit_graph
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    assert has_commit_graph(repo) is False
    git(repo, "commit-graph", "write", "--reachable", "--split")
    assert has_commit_graph(repo) is True
    linked = repo.parent / "linked"
    git(repo, "worktree", "add", "--detach", str(linked), "HEAD")
    assert has_commit_graph(linked) is True
