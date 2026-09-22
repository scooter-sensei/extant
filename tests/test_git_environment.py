"""The environment every git process inherits, and what it must not decide.

`_git` in extant/git.py ran `["git", *args]` with `cwd=repo` and the
environment it was handed. That environment can name a repository: git exports
`GIT_DIR` and `GIT_WORK_TREE` to every hook it runs, pre-commit frameworks set
them too, and a harness that drives one repository's hook against another's
checkout passes them straight through. `cwd=repo` then decides which WORKING
TREE git looks at while `GIT_DIR` decides whose HISTORY it answers about.

Verified on this machine before anything was changed: from a second
repository, `GIT_DIR=../r1/.git git log -1` prints the first repository's
subject while `git rev-parse --show-toplevel` still names the second. Every
git-backed rule then answers about the wrong repository and prints what a
clean run prints - which is the failure shape this project exists to refuse.

Each variable below was checked for whether it changes an answer extant
actually asks for, and only those that do are in the table. `GIT_NAMESPACE`
is scrubbed too but is not here: only the transport commands honour it, and
`for-each-ref` under a leaked namespace still listed `refs/heads/main`.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PAYLOAD = (Path(__file__).resolve().parent.parent / "plugin" / "skills"
           / "extant" / "payload")
sys.path.insert(0, str(PAYLOAD))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import committer, init_repo  # noqa: E402

DOC = "## Phase 1 - x (in progress, 2026-01-01)\n\nSee `{a}` and `{b}`.\n"

# Which directory of the OTHER repository each variable is pointed at. The
# four are the ones that move the answer to "does this commit exist": the
# first three replace where git reads from, the last ADDS a store, so a commit
# that is dead here reads as alive.
LEAKS = [
    pytest.param("GIT_DIR", ".git", id="GIT_DIR"),
    pytest.param("GIT_COMMON_DIR", ".git", id="GIT_COMMON_DIR"),
    pytest.param("GIT_OBJECT_DIRECTORY", ".git/objects",
                 id="GIT_OBJECT_DIRECTORY"),
    pytest.param("GIT_ALTERNATE_OBJECT_DIRECTORIES", ".git/objects",
                 id="GIT_ALTERNATE_OBJECT_DIRECTORIES"),
]


def _two_repositories(git_repo, tmp_path: Path) -> tuple[Path, str, str]:
    """`repo` holding commit `a`, and a second repository holding only `b`."""
    repo, commit = git_repo
    a = commit("a.py", "a = 1\n", "feat: a")
    other = tmp_path / "other"
    init_repo(other)
    b = committer(other)("b.py", "b = 2\n", "feat: b")
    return repo, a, b


@pytest.mark.parametrize("variable, inside", LEAKS)
def test_a_leaked_location_variable_does_not_change_which_repository_answers(
        monkeypatch, git_repo, tmp_path, variable, inside) -> None:
    """`--repo` names the repository. Nothing in the environment overrides it.

    The document cites one commit from each repository. Only the OTHER
    repository's commit is dead in `repo`, so exactly that one is reported -
    and under the leak, without the fix, the report inverts or empties.
    """
    from extant import session as hc

    repo, a, b = _two_repositories(git_repo, tmp_path)
    monkeypatch.setenv(variable, str(tmp_path / "other" / inside))

    findings = hc.validate(repo, DOC.format(a=a, b=b))
    dead = sorted(f.subject for f in findings if f.kind == "dead-sha")
    print(f"{variable} leaked: dead={dead}")
    assert dead == [b], (
        f"with {variable} naming another repository, dead-sha reported {dead} "
        f"where only {b!r} is absent from --repo")


POINTER = ("version https://git-lfs.github.com/spec/v1\n"
           "oid sha256:" + "a" * 64 + "\nsize 4096\n")


def _commit_raw(repo: Path, rel: str, content: str) -> None:
    """Commit `rel` bypassing any LFS clean filter, as tests/test_lfs.py does."""
    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    with open(repo / rel, "w", encoding="utf-8", newline="") as fh:
        fh.write(content)
    sha = subprocess.run(["git", "hash-object", "-w", "--no-filters", rel],
                         cwd=repo, capture_output=True, text=True,
                         check=True).stdout.strip()
    subprocess.run(["git", "update-index", "--add", "--cacheinfo",
                    f"100644,{sha},{rel}"], cwd=repo, check=True,
                   capture_output=True)
    subprocess.run(["git", "commit", "-qm", f"add {rel}"], cwd=repo,
                   check=True, capture_output=True)


# The git invocations CountingGit's docstring lists as bypassing the seam,
# each named by the argv it starts with and how many sites spell it. Every
# one must be reached below, or a site nobody reached is a site nobody
# checked. `cat-file --batch` is TWO sites with one argv - the LFS rule's
# blob read and `--deleted-since`'s read of every previous version, which
# replaced one `git show` per document on 2026-09-20 - so a presence check
# would let either of them go unreached behind the other; the count is what
# keeps both in the denominator.
DIRECT_SITES = {"cat-file --batch-check": 1, "ls-tree -r -z HEAD": 1,
                "check-attr -z --stdin filter": 1, "cat-file --batch": 2,
                "diff -U0": 1}


def test_every_git_process_starts_with_the_scrubbed_environment(
        monkeypatch, git_repo, tmp_path) -> None:
    """Including the seven that call `subprocess` directly.

    A scrub applied in `_git` alone would leave the `cat-file` batches, the
    attribute query and `git diff` answering from the leaked location, and
    those are the SHA rule, the LFS rule, `--deleted-since` and
    `--introduced-since` - so the seam is not where this is checked. Every
    `git` process started while four modes run is recorded at the subprocess
    boundary with the environment it was handed, and the denominator is that
    each direct site was actually reached, as many times as there are sites
    spelling that argv.
    """
    from extant import session as hc
    from extant import deleted_since, introduced_since

    repo, commit = git_repo
    sha = commit("a.py", "a = 1\n", "feat: a")
    (repo / ".gitattributes").write_text(
        "*.png filter=lfs diff=lfs merge=lfs -text\n"
        "*.wav filter=lfs diff=lfs merge=lfs -text\n", encoding="utf-8")
    commit(".gitattributes", (repo / ".gitattributes").read_text("utf-8"),
           "chore: lfs")
    _commit_raw(repo, "Assets/raw.wav", "RIFF" + "wavdata" * 600)
    _commit_raw(repo, "Assets/ok.png", POINTER)
    commit("NEXT_SESSION.md", DOC.format(a=sha, b="dead" + "0" * 36), "docs")
    commit("NEXT_SESSION.md", "# S\n\nNothing.\n", "docs: remove")

    # A leak to watch being scrubbed: a COPY of the repository, so that a site
    # still answering from the leaked location gets a tree with the same
    # shape and every later site is reached either way. Pointing the leak at
    # a directory that is not there would fail the first unscrubbed site and
    # leave the ones behind it unreached, which reads as a broken fixture
    # rather than as the inheritance it is. Set after the fixture is built,
    # because the fixture's own git calls would inherit it too.
    other = tmp_path / "other"
    shutil.copytree(repo, other)
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    spawned: list[tuple[str, dict | None]] = []
    real = subprocess.run

    def record(cmd, *a, **kw):
        if cmd and str(cmd[0]) == "git":
            spawned.append((" ".join(str(c) for c in cmd[1:]), kw.get("env")))
        return real(cmd, *a, **kw)

    monkeypatch.setattr(subprocess, "run", record)
    hc.validate(repo, DOC.format(a=sha, b="dead" + "0" * 36))
    deleted_since.deleted_claims(repo, "HEAD~1")
    introduced_since.introduced_lines(repo, "HEAD~1")

    unscrubbed = [cmd for cmd, env in spawned
                  if env is None or "GIT_DIR" in env
                  or env.get("GIT_NO_LAZY_FETCH") != "1"]
    reached = {site: sum(cmd.startswith(site) for cmd, _env in spawned)
               for site in DIRECT_SITES}
    print(f"{len(spawned)} git processes, {len(unscrubbed)} unscrubbed; "
          f"direct sites reached: {reached}")
    assert not unscrubbed, (
        f"{len(unscrubbed)} of {len(spawned)} git processes inherited the "
        f"operator's environment unscrubbed: {unscrubbed}")
    short = {site: (reached[site], wanted) for site, wanted in DIRECT_SITES.items()
             if reached[site] < wanted}
    assert not short, f"direct sites reached fewer times than sites exist: {short}"


def test_a_repo_that_is_not_a_repository_root_is_said_so(git_repo, capsys) -> None:
    """`--repo` at a subdirectory: git walks UP and answers about the
    enclosing repository, while every document and path resolves against the
    subdirectory. Verified: `rev-parse --show-toplevel` from `r2/sub/deeper`
    prints `r2`. Neither half is wrong on its own, and together they are the
    "true where you are standing" confusion this tool exists to catch - so the
    run says which repository git is answering about, once, on stderr.

    A note rather than a refusal, because a deliberate `--repo <subdir>` has
    worked since the flag existed and somebody may depend on it.
    """
    from extant import cli

    repo, commit = git_repo
    commit("docs/NEXT_SESSION.md", "Nothing falsifiable here.\n", "docs")

    cli.main(["--verify", "--repo", str(repo / "docs")])
    err = capsys.readouterr().err
    notes = [line for line in err.splitlines() if "not the root" in line]
    print(err)
    assert len(notes) == 1, err
    assert str(repo) in notes[0], notes[0]

    # And at the root, nothing - a note printed on every run is one nobody
    # reads.
    cli.main(["--verify", "--repo", str(repo)])
    assert "not the root" not in capsys.readouterr().err


def test_a_repo_with_no_repository_above_it_is_said_so(tmp_path, capsys) -> None:
    """A `git archive` extract, or any plain directory: nothing git can find.

    Every git-backed rule then errors, which the run already reports beside
    the denominators. The note in front of that names the cause rather than
    leaving thirteen rule errors to imply it.
    """
    from extant import cli

    plain = tmp_path / "extract"
    plain.mkdir()
    (plain / "NEXT_SESSION.md").write_text("Nothing here.\n", encoding="utf-8")

    cli.main(["--verify", "--repo", str(plain)])
    err = capsys.readouterr().err
    print(err)
    assert "no repository" in err and str(plain) in err, err


def test_a_renamed_path_holding_a_non_ascii_character_still_gets_a_hint(
        git_repo) -> None:
    """`core.quotePath` defaults to true, and it is off for every process here.

    Under the default, `log --name-status` prints a path holding any byte
    above ASCII as a quoted, octal-escaped string - `"docs/\303\234bersicht.md"`
    - and the rename map keyed on that spelling matched nothing a document
    could write. The pointer was still reported dead, so nothing was wrong
    that a test on the finding would see; what went missing, silently, was
    the "renamed to" hint that the same rename gets under an ASCII name.
    """
    from extant import session as hc
    from extant.refs import renamed_to

    repo, commit = git_repo
    old = "docs/\u00dcbersicht.md"
    commit(old, "# U\n", "docs: add")
    subprocess.run(["git", "mv", old, "docs/overview.md"], cwd=repo,
                   check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "docs: rename"], cwd=repo,
                   check=True, capture_output=True)

    with hc.run_scope():
        hint = renamed_to(hc.context(repo), old)
    print(f"renamed_to({old!r}) = {hint!r}")
    assert hint == "docs/overview.md", hint


def test_the_operators_own_config_injection_survives_the_child_environment(
        monkeypatch, git_repo) -> None:
    """`core.quotePath=false` is APPENDED to `GIT_CONFIG_COUNT`, not put in
    its place. CI sets that triplet for `safe.directory`, and a child that lost
    it would fail where the parent works; git itself is asked, so the test
    reads what the child sees rather than what the dict says.
    """
    from extant.git import environment

    repo, _commit = git_repo
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "safe.directory")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "*")

    def child_says(key: str) -> str:
        return subprocess.run(["git", "config", "--get", key], cwd=repo,
                              capture_output=True, text=True,
                              env=environment()).stdout.strip()

    seen = {key: child_says(key) for key in ("safe.directory", "core.quotepath")}
    print(f"the child sees {seen}")
    assert seen == {"safe.directory": "*", "core.quotepath": "false"}, seen

    # A count git refuses is left for git to refuse: the child must not work
    # where the operator's own git does not.
    monkeypatch.setenv("GIT_CONFIG_COUNT", "bogus")
    assert environment()["GIT_CONFIG_COUNT"] == "bogus"


def test_deleted_since_sees_a_document_whose_name_holds_a_non_ascii_character(
        git_repo) -> None:
    """The other reader of a quoted path. `--deleted-since` keeps only the
    configured documents that `diff --name-only` says changed, and under the
    default quoting that listing spelled this document `"\303\234bersicht.md"`
    - so it was never among the changed, examined nothing, and the removed
    false claim went unreported. Verified on the command itself before this
    test was written: the default prints the octal spelling, `quotePath=false`
    the bytes.
    """
    from extant import session as hc
    from extant import deleted_since

    repo, commit = git_repo
    name = "\u00dcbersicht.md"
    (repo / ".extant.toml").write_text(f'primary_doc = "{name}"\n',
                                       encoding="utf-8")
    commit(".extant.toml", (repo / ".extant.toml").read_text("utf-8"), "cfg")
    hc.reload_config(repo)
    dead = "dead" + "0" * 36
    commit(name, f"## Phase 1 - x (in progress, 2026-01-01)\n\nMerged at "
                 f"`{dead}`.\n", "docs: claim")
    commit(name, "## Phase 1 - x (in progress, 2026-01-01)\n\nNothing.\n",
           "docs: remove")

    gone, examined, _skipped, _bad = deleted_since.deleted_claims(repo, "HEAD~1")
    print(f"examined {examined}; gone {[g.finding.subject for g in gone]}")
    assert examined == 1, f"examined {examined} documents, not the one that changed"
    assert [g.finding.subject for g in gone] == [dead]


def test_a_bare_repository_is_its_own_root(tmp_path, capsys) -> None:
    """`HEAD` beside `objects` and `refs`, and no `.git`: git reads that as a
    repository, and so must the root note, or every run against a bare
    repository opens with a note saying there is none."""
    from extant import cli

    bare = tmp_path / "bare.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True,
                   capture_output=True)
    cli.main(["--verify", "--repo", str(bare)])
    err = capsys.readouterr().err
    print(err)
    assert "no repository" not in err and "not the root" not in err, err


def test_a_sweep_under_a_leaked_git_dir_surveys_the_repository_it_was_given(
        monkeypatch, git_repo, tmp_path, capsys) -> None:
    """The survey's document list comes from `ls-tree HEAD`, so a leaked
    location would have it survey another repository's files - or, pointed at
    one whose tree lists no markdown, report an honest-looking empty run."""
    from extant import session as hc
    from extant.sweep import run_sweep

    repo, commit = git_repo
    commit("NEXT_SESSION.md", "## Phase 1 - x (in progress, 2026-01-01)\n\n"
                              "See `" + "dead" + "0" * 36 + "`.\n",
           "docs")
    other = tmp_path / "other"
    init_repo(other)
    committer(other)("b.py", "b = 2\n", "feat: b")
    hc.reload_config(repo)
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))

    run_sweep(repo, "text")
    out = capsys.readouterr().out
    print(out)
    assert "swept 1 markdown file(s)" in out, out
    assert "dead-sha" in out and "dead0000" in out, out


def test_every_direct_git_spawn_in_the_source_passes_the_environment() -> None:
    """The structural half of the runtime test above, for sites no mode in
    that test reaches. A `subprocess.run(["git", ...])` written next year in
    a rule the fixture does not exercise would inherit the operator's
    environment and print what a clean run prints - so every such call in the
    shipped source is read here and must name `env=environment()`. The
    denominator: the eight sites tests/test_scope.py lists beside
    PACKAGE_DIRECT_SUBPROCESS_SITES, plus the seam.
    """
    import ast

    sites: list[str] = []
    naked: list[str] = []
    for path in sorted((PAYLOAD / "extant").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "run" and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "subprocess" and node.args):
                continue
            first = node.args[0]
            if not (isinstance(first, ast.List) and first.elts
                    and isinstance(first.elts[0], ast.Constant)
                    and first.elts[0].value == "git"):
                continue
            where = f"{path.name}:{node.lineno}"
            sites.append(where)
            passed = any(kw.arg == "env" and isinstance(kw.value, ast.Call)
                         and getattr(kw.value.func, "id", "") == "environment"
                         for kw in node.keywords)
            if not passed:
                naked.append(where)
    print(f"{len(sites)} direct git spawns in the source: {sites}")
    assert len(sites) == 9, f"expected the eight direct sites plus the seam, found {sites}"
    assert not naked, f"git spawned with the operator's environment at {naked}"
