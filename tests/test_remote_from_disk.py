"""Reading `remote.origin.url` from the config file instead of spawning git.

`git.py` already does this twice - `is_shallow` reads `.git/shallow` and
`common_git_dir` reads `commondir` - "because it is one stat", and because
interpreting a failed `rev-parse` "is exactly the ambiguity this is trying to
remove". `remote get-url origin` is the same shape: 27.27 ms to spawn, 0.56 ms
to read.

The milliseconds are not the point. `--verify` opens one RunScope per document,
so this one repository-level fact was asked five times per run - and widening
that scope to share it would trade away a safety property `scope.py` documents
having been burned by, where an origin added between two calls kept answering
None and `dead-pinned-ref` reported clean having examined nothing. Reading the
file buys the same five spawns and changes no lifetime at all.

WHAT MAKES IT MORE THAN A ONE-LINE CHANGE is that `configparser` is not a git
config parser. It disagrees with git on three real syntaxes, and each
disagreement survives `_normalise_remote` into a wrong `owner/name`:

    quoted value      git=owner/name   configparser="https://.../name.git"
    inline ; comment  git=owner/name   configparser=https://... ; c
    inline # comment  git=owner/name   configparser=https://... # c

So the shape is READ, VALIDATE, OR FALL BACK - a fast path for what git itself
writes, and git's own answer for anything else. These tests are the divergence
table: every variant either matches git or declines, and declining is a pass.
A test that only exercised the happy path would have gone green while the
quoted-value case returned a wrong `owner/name`.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PAYLOAD = (Path(__file__).resolve().parent.parent / "plugin" / "skills"
           / "extant" / "payload")
sys.path.insert(0, str(PAYLOAD))

URL = "https://github.com/acme/widget.git"

# Every spelling measured, named so a failure says which one broke. The value
# is what gets APPENDED to a config that already has an ordinary `[core]`
# section; None means "add nothing", which is the no-origin case.
VARIANTS = [
    pytest.param(f'[remote "origin"]\n\turl = {URL}\n', id="plain"),
    pytest.param(f'[remote "origin"]\n\turl = "{URL}"\n', id="quoted"),
    pytest.param(f'[remote "origin"]\n\turl = {URL} ; a comment\n',
                 id="inline-semicolon"),
    pytest.param(f'[remote "origin"]\n\turl = {URL} # a comment\n',
                 id="inline-hash"),
    pytest.param(f'[REMOTE "origin"]\n\turl = {URL}\n', id="uppercase-section"),
    pytest.param('[remote "origin"]\n\turl = git@github.com:acme/widget.git\n',
                 id="scp-style-ssh"),
    pytest.param("", id="no-origin"),
    pytest.param('[remote "upstream"]\n\turl = https://github.com/other/repo\n',
                 id="different-remote-only"),
    pytest.param(f'[remote "origin"]\n\turl = {URL}\n'
                 f'\turl = https://github.com/acme/second.git\n',
                 id="two-urls"),
    pytest.param(f'[url "git@github.com:"]\n\tinsteadOf = https://github.com/\n'
                 f'[remote "origin"]\n\turl = {URL}\n',
                 id="insteadOf-rewrite"),
    pytest.param(f'[remote "origin"]\n\turl={URL}\n', id="no-spaces"),
    pytest.param(f'[remote "origin"]\n\tURL = {URL}\n', id="uppercase-key"),
    pytest.param(f'[extensions]\n\tworktreeConfig = true\n'
                 f'[remote "origin"]\n\turl = {URL}\n',
                 id="worktree-config-enabled"),
    pytest.param(f'[include]\n\tpath = elsewhere\n'
                 f'[remote "origin"]\n\turl = {URL}\n', id="include"),
]


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True,
        encoding="utf-8", check=True,
    ).stdout.strip()


def git_says(repo: Path) -> str | None:
    """What `git remote get-url origin` answers, or None when there is none."""
    done = subprocess.run(
        ["git", "remote", "get-url", "origin"], cwd=repo, capture_output=True,
        text=True, encoding="utf-8",
    )
    return done.stdout.strip() or None if done.returncode == 0 else None


def with_config(repo: Path, extra: str) -> None:
    from extant.git import common_git_dir

    shared = common_git_dir(repo)
    assert shared is not None, repo
    config = shared / "config"
    config.write_text(config.read_text(encoding="utf-8") + extra,
                      encoding="utf-8")


@pytest.mark.parametrize("extra", VARIANTS)
def test_the_fast_path_matches_git_or_declines_to_answer(git_repo, extra) -> None:
    """The whole contract, in one assertion, over every spelling measured.

    A WRONG answer is the only failure. Declining is a pass, and costs a spawn.
    """
    from extant.git import remote_url

    repo, commit = git_repo
    commit("a.py", "a = 1\n", "chore: init")
    with_config(repo, extra)

    expected = git_says(repo)
    got = remote_url(repo, "origin")
    print(f"git={expected!r} file={got!r}")
    assert got is None or got == expected, (
        f"the fast path answered {got!r} where git says {expected!r}")


def test_the_common_spellings_are_actually_answered_from_disk(git_repo) -> None:
    """The denominator. A guard that declines everything passes the table above.

    Four of the twelve variants must resolve on the fast path, or this change
    buys nothing at all and the tests above are asserting a permanent refusal.
    """
    from extant.git import remote_url

    repo, commit = git_repo
    commit("a.py", "a = 1\n", "chore: init")

    answered = []
    for spelling in ('[remote "origin"]\n\turl = ' + URL + "\n",
                     '[REMOTE "origin"]\n\turl = ' + URL + "\n",
                     '[remote "origin"]\n\turl=' + URL + "\n",
                     '[remote "origin"]\n\tURL = ' + URL + "\n"):
        from extant.git import common_git_dir
        shared = common_git_dir(repo)
        assert shared is not None
        config = shared / "config"
        base = config.read_text(encoding="utf-8")
        config.write_text(base + spelling, encoding="utf-8")
        answered.append(remote_url(repo, "origin"))
        config.write_text(base, encoding="utf-8")

    print(f"answered from disk: {answered}")
    assert answered == [URL] * 4, answered


def test_a_linked_worktree_reads_the_config_it_actually_shares(git_repo) -> None:
    """Its `.git` is a FILE, so a naive read finds no config at all.

    Not a corner: phase work in this project happens in linked worktrees by
    convention, so the naive version would have declined on every run a
    contributor actually makes - correct, and silently paying the spawn it was
    written to remove.
    """
    from extant.git import remote_url

    repo, commit = git_repo
    commit("a.py", "a = 1\n", "chore: init")
    git(repo, "remote", "add", "origin", URL)
    linked = repo.parent / "linked"
    git(repo, "worktree", "add", "-q", "-b", "side", str(linked))

    assert (linked / ".git").is_file(), "expected a worktree pointer file"
    assert git_says(linked) == URL
    assert remote_url(linked, "origin") == URL


def test_a_per_worktree_config_file_is_what_makes_the_answer_unsettled(
        git_repo) -> None:
    """`extensions.worktreeConfig` alone is not a reason to decline, and was.

    Refusing on the word made this change worth nothing on the repository that
    motivated it: extant's own `.git/config` sets that extension, so the fast
    path never fired here and `--verify` went on spawning five processes for
    one fact. The extension only says a `config.worktree` WOULD be read; the
    file is what can override the URL, and this stats for the file.
    """
    from extant.git import _own_git_dir, remote_url

    repo, commit = git_repo
    commit("a.py", "a = 1\n", "chore: init")
    with_config(repo, f'[extensions]\n\tworktreeConfig = true\n'
                      f'[remote "origin"]\n\turl = {URL}\n')

    assert remote_url(repo, "origin") == URL, (
        "declined on the extension alone, with no per-worktree config present")

    own = _own_git_dir(repo)
    assert own is not None
    (own / "config.worktree").write_text(
        f'[remote "origin"]\n\turl = https://github.com/other/name.git\n',
        encoding="utf-8")
    assert remote_url(repo, "origin") is None, (
        "answered from the shared config while a per-worktree one overrides it")


def test_a_repository_with_no_git_directory_at_all_declines(tmp_path) -> None:
    """The unreadable case answers None rather than inventing an absence.

    "This repository has no origin" and "this question could not be settled"
    are the two answers this project exists to keep apart, and only the second
    is what a missing file means.
    """
    from extant.git import remote_url

    bare = tmp_path / "not-a-repo"
    bare.mkdir()
    assert remote_url(bare, "origin") is None


def test_the_rule_answers_the_same_thing_without_spawning(monkeypatch,
                                                          git_repo) -> None:
    """`dead-pinned-ref`'s own question, and the five spawns it stops costing."""
    from extant import session as hc
    from extant.rules import pinned_ref

    repo, commit = git_repo
    commit("a.py", "a = 1\n", "chore: init")
    git(repo, "remote", "add", "origin", URL)

    spawns: list[str] = []
    real = subprocess.run

    def record(cmd, *a, **kw):
        if cmd and str(cmd[0]) == "git":
            spawns.append(" ".join(str(c) for c in cmd[1:]))
        return real(cmd, *a, **kw)

    monkeypatch.setattr(subprocess, "run", record)
    with hc.run_scope():
        assert pinned_ref._own_remote(hc.context(repo)) == "acme/widget"

    print(f"spawns while answering the remote: {spawns}")
    assert spawns == [], "the remote was still answered by a git process"


def test_the_rule_still_falls_back_when_the_file_cannot_settle_it(
        monkeypatch, git_repo) -> None:
    """A syntax the guard refuses must produce git's answer, not no answer.

    Degrade to correct-and-slow is the failure mode this is designed for, and
    a fast path that declined into `None` would make `dead-pinned-ref` examine
    nothing and report clean - the exact silent shape `scope.py` records.
    """
    from extant import session as hc
    from extant.rules import pinned_ref

    repo, commit = git_repo
    commit("a.py", "a = 1\n", "chore: init")
    with_config(repo, f'[remote "origin"]\n\turl = "{URL}"\n')

    spawns: list[str] = []
    real = subprocess.run

    def record(cmd, *a, **kw):
        if cmd and str(cmd[0]) == "git":
            spawns.append(" ".join(str(c) for c in cmd[1:]))
        return real(cmd, *a, **kw)

    monkeypatch.setattr(subprocess, "run", record)
    with hc.run_scope():
        assert pinned_ref._own_remote(hc.context(repo)) == "acme/widget"

    print(f"spawns while falling back: {spawns}")
    assert any("remote get-url origin" in c for c in spawns), (
        "the quoted spelling was answered from disk instead of falling back")


def test_a_repository_with_no_origin_still_reports_none(git_repo) -> None:
    """The other direction, so the tests above cannot pass by always answering."""
    from extant import session as hc
    from extant.rules import pinned_ref

    repo, commit = git_repo
    commit("a.py", "a = 1\n", "chore: init")

    with hc.run_scope():
        assert pinned_ref._own_remote(hc.context(repo)) is None
