"""Running git, and nothing else.

No caching lives here. Memoised answers belong to a RunScope, which is what
gives them a lifetime; a cache in this module would have the lifetime of the
process and no way to say so.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

# The surface Task 2 said this would become. `_git` and `_git_soft` were
# declared here transitionally, because the shim re-exported them by name and
# five test sites wrapped them to count calls; both are back to being private
# implementation, called by SubprocessGit and named nowhere outside this file.
__all__ = ["Git", "SubprocessGit", "CountingGit",
           "_PLAIN_VALUE", "_UNSETTLED_BY", "_names_remote", "_own_git_dir",
           "common_git_dir", "environment", "is_partial", "is_shallow",
           "remote_url", "repository_root", "rewrite_journal_path",
           "rewrite_map_path"]


class Git:
    """The subcommands the validator asks for, behind one replaceable object.

    Both behaviours are modelled deliberately. `run` raises where `soft`
    returns empty, and an implementation that collapses them turns every error
    path into a success path, which is silent by construction. The two
    docstrings below say which is which; the reasoning for the distinction is
    on `_git_soft`, which is where it was written when the distinction was
    made.
    """

    def run(self, repo: Path, *args: str) -> str:
        """Run git in `repo` and return stdout. Raises when git fails."""
        raise NotImplementedError

    def soft(self, repo: Path, *args: str) -> str:
        """Run git in `repo`, returning "" rather than raising when it fails."""
        raise NotImplementedError


class SubprocessGit(Git):
    """The real one: a `git` process per call."""

    def run(self, repo: Path, *args: str) -> str:
        return _git(repo, *args)

    def soft(self, repo: Path, *args: str) -> str:
        return _git_soft(repo, *args)


class CountingGit(Git):
    """A Git that records every command, for budgets and profiles.

    Delegating rather than subclassing SubprocessGit so that a fake can be
    counted the same way.

    ONE entry per call, including a soft one, and that is the difference from
    the wrapper-counting it replaces. `_git_soft` delegates to `_git`, so a
    test that wrapped both names by hand saw two entries for one soft call -
    and the spawn figure this seam was built to defend was measured that way,
    wrongly, the first time. Here the delegation happens inside SubprocessGit,
    BELOW the interface, so it cannot be seen twice.

    Not a spawn count, and must not be read as one. Eight git invocations
    across this package do not fit `run(repo, *args)` - three `cat-file`
    batches fed on stdin (two in extant/rules/lfs.py, one in extant/refs.py's
    `_batch_shas`), the `rev-list --stdin` batch beside it in `_settle` that
    places the commits a bounded ancestry index could not, a `-z` listing
    paired with `check-attr --stdin` (both in extant/rules/lfs.py), a `git
    show` that must return bytes (extant/deleted_since.py's `_document_at`),
    and a `git diff -U0` that must return bytes too
    (extant/introduced_since.py's `introduced_lines`, because `_git` below
    translates a bare carriage return and a patch is written in git's line
    discipline) - so they call subprocess directly and are invisible here. tests/test_spawn_budget.py counts at the subprocess
    boundary for exactly that reason, and tests/test_scope.py prints both
    populations so the gap is a number somebody chose rather than one nobody
    noticed.
    """

    def __init__(self, inner: Git) -> None:
        self.inner = inner
        self.calls: list[tuple[str, ...]] = []

    def run(self, repo: Path, *args: str) -> str:
        self.calls.append(args)
        return self.inner.run(repo, *args)

    def soft(self, repo: Path, *args: str) -> str:
        self.calls.append(args)
        return self.inner.soft(repo, *args)


def _git_soft(repo: Path, *args: str) -> str:
    """Run git, returning "" instead of raising when the command fails.

    For FACT GATHERING, where the absence of an answer is itself a legitimate
    answer. A repository with no commits has no HEAD, no trunk ref and no
    branches, so `git log`, `git rev-parse HEAD` and `git branch --merged main`
    all exit 128 - not because anything is wrong, but because someone has just
    run `git init`.

    Deliberately NOT used by the validation rules. There, a git command that
    fails means a claim could not be checked, and silently treating that as
    "no finding" is the exact shape of failure this project exists to prevent.
    """
    try:
        return _git(repo, *args)
    except (subprocess.CalledProcessError, OSError):
        return ""


def is_shallow(repo: Path) -> bool:
    """True when this checkout is depth-limited.

    It matters because `dead-sha` asks whether a commit is REACHABLE, and a
    shallow clone answers that question about the slice it was given rather
    than about the repository. A SHA that is perfectly alive upstream reads as
    dead here, and the run reports it with the same confidence as a real one.
    Nothing about this can be fixed without the missing history, so the only
    honest thing available is to say which kind of answer the reader is
    holding - the same reason every mode prints its denominator.

    Read from the marker file rather than by shelling out, because it is one
    stat, and because a `git rev-parse --is-shallow-repository` that fails
    would have to be interpreted, and the interpretation of a failure here is
    exactly the ambiguity this is trying to remove.
    """
    if (repo / ".git" / "shallow").is_file():
        return True
    shared = common_git_dir(repo)
    if shared is None or shared == repo / ".git":
        return False
    return (shared / "shallow").is_file()


def is_partial(repo: Path) -> bool:
    """True when this repository was copied with an object filter.

    The transport then left objects out - `blob:none` keeps every commit and
    tree and only the blobs the checkout needed - and git retrieves each
    missing one from the promisor remote the moment a command wants it, over
    the network, mid-command. `environment()` turns that off with
    `GIT_NO_LAZY_FETCH`, so here a missing object stays missing: rename
    detection over an absent blob fails and the hint is not offered, and a
    rule that reads blob contents reads fewer. Both are answers about less
    than the repository holds, which is the shallow case's shape exactly, and
    it gets the same note beside the denominators.

    Read from the shared config rather than asked of git, for the reasons
    `is_shallow` gives. `remote.<name>.promisor = true` is what git itself
    checks; `remote.<name>.partialclonefilter` and the older
    `extensions.partialclone` are the other two spellings a filter leaves
    behind, matched on their common prefix. Section headers are not needed:
    no other key git writes is spelled either way.
    """
    shared = common_git_dir(repo)
    if shared is None:
        return False
    try:
        text = (shared / "config").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line[0] in "#;[":
            continue
        key, _, value = line.partition("=")
        key = key.strip().lower()
        if key == "promisor" and value.strip().lower() == "true":
            return True
        if key.startswith("partial"):
            return True
    return False


def common_git_dir(repo: Path) -> Path | None:
    """The SHARED git directory - `.git` of the original clone - or None.

    Everything git keeps once per REPOSITORY rather than once per checkout
    lives here: the object store, `shallow`, and the commit-map a
    `git filter-repo` run leaves behind. A linked worktree has a git directory
    of its own beside those, and looking in that one instead finds none of
    them.

    Read from the filesystem rather than by shelling out to
    `rev-parse --git-common-dir`, for the two reasons `is_shallow` gives: it is
    a stat, and the interpretation of a failed `rev-parse` is exactly the
    ambiguity this is trying to remove. It also has to stay a stat because the
    spawn budget in tests/test_spawn_budget.py has no spare margin, and a
    question asked once per run is still a question.

    The three shapes, each of which git writes differently:

    * A plain checkout keeps a `.git` DIRECTORY, and it is the shared one.
    * A LINKED WORKTREE keeps a `.git` FILE naming a directory under
      `.git/worktrees/<name>/`, which carries `commondir` pointing back at the
      original. This is the case that was got wrong once: `shallow` lives in
      the shared directory, so checking only the worktree's own returned False
      for every worktree of a shallow clone while git said true.
    * A SUBMODULE keeps a `.git` FILE too, naming a directory that IS its
      shared one - no `commondir` beside it - so the pointer is the answer.

    None means the question could not be settled: no `.git` at all, a pointer
    that does not parse, or one naming a directory that is not there. Callers
    report that rather than treating it as an absence, because "this
    repository was never rewritten" and "this repository could not be read"
    are the two answers this project exists to keep apart.
    """
    pointer = repo / ".git"
    if pointer.is_dir():
        return pointer
    gitdir = _own_git_dir(repo)
    if gitdir is None:
        return None
    common = gitdir / "commondir"
    if not common.is_file():
        return _normal(gitdir)
    try:
        shared = Path(common.read_text(encoding="utf-8").strip())
    except (OSError, UnicodeDecodeError):
        return None
    return _normal(shared if shared.is_absolute() else gitdir / shared)


def repository_root(path: Path) -> Path | None:
    """The directory git would answer about when run in `path`, or None.

    Found the way git finds it: `path` itself if it holds a `.git`, else the
    nearest parent that does, else nothing. So `--repo` naming a subdirectory
    returns the checkout above it - which is exactly what has to be said out
    loud, because git then answers about that checkout while every document
    and path in the run resolves against the subdirectory. Verified before
    this existed: `rev-parse --show-toplevel` from `r2/sub/deeper` prints
    `r2`, quietly.

    Stats, not a spawn, for the reason `common_git_dir` gives, and because
    this is asked once per run in front of a budget with no spare margin. A
    bare repository - `HEAD` beside `objects` and `refs`, no `.git` - counts
    as its own root, which is also how git reads one.

    Lexical: `abspath` and no `resolve()`, so a symlinked checkout is named
    the way the operator named it, and the comparison the caller makes
    against `--repo` is between two spellings of one convention.
    """
    start = Path(os.path.abspath(path))
    for candidate in (start, *start.parents):
        pointer = candidate / ".git"
        if pointer.is_dir() or pointer.is_file():
            return candidate
        if ((candidate / "HEAD").is_file() and (candidate / "objects").is_dir()
                and (candidate / "refs").is_dir()):
            return candidate
    return None


def _own_git_dir(repo: Path) -> Path | None:
    """THIS CHECKOUT's git directory, which is not always the shared one.

    The split matters because git keeps two different populations in the two
    places, and `common_git_dir` above is about the shared half. Everything
    per-worktree lives here instead: HEAD, the rebase state, and
    `config.worktree`, which is the file that can make the shared config's
    `remote.origin.url` not be the answer.

    Same three shapes `common_git_dir` documents, stopping one step earlier: a
    plain checkout's `.git` DIRECTORY is its own git directory, and a linked
    worktree or a submodule keeps a `.git` FILE naming one.
    """
    pointer = repo / ".git"
    if pointer.is_dir():
        return pointer
    if not pointer.is_file():
        return None
    try:
        content = pointer.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    if not content.startswith("gitdir:"):
        return None
    gitdir = Path(content.split(":", 1)[1].strip())
    return gitdir if gitdir.is_absolute() else repo / gitdir


def _normal(path: Path) -> Path:
    """Fold away the `..` git writes, so two spellings of one directory compare.

    `commondir` holds `../..` relative to `.git/worktrees/<name>`, so joining
    it yields `.../worktrees/<name>/../..` - the right directory under a name
    that is equal to nothing, which matters because callers compare this
    against `repo / ".git"` and key caches on it.

    Lexical rather than `resolve()`: it touches no filesystem, so a question
    asked once per run stays a question and not a walk, and it cannot turn a
    path the caller gave into a different one by following a symlink.
    """
    return Path(os.path.normpath(path))


# Anything in a config file that means the URL git reports is not the URL
# written under `[remote "<name>"]`. Matched as a SUBSTRING of the whole
# lowercased file, which over-refuses - a repository whose remote URL happens
# to contain one of these words pays a spawn it did not need - and that is the
# right direction to be wrong in here.
#
#   insteadof       `url.<base>.insteadOf` rewrites the URL git hands back.
#                   The caller reduces it to `owner/name` - the LAST TWO
#                   path segments - so a rewrite that changes the host, or
#                   keeps those two under a longer prefix, lands on an
#                   identical answer; one that moves the repository under
#                   another owner does not, and nothing here can tell which
#                   kind it is looking at without becoming git.
#   include         `include.path` and `includeIf` pull in another file, which
#                   may define the remote or redefine it. NOT a corner case: a
#                   GitHub Actions runner writes four
#                   `[includeIf "gitdir:..."]` sections into every checkout,
#                   so this path declines on CI and the spawn is paid there.
#                   Measured from a failing run, not assumed.
#
# Matched in the repository's own file here, and in every OTHER scope git
# reads by `_unsettled_elsewhere` below - which was the half that was missing:
# a rewrite in `~/.gitconfig`, the system file or the environment is just as
# effective, and the guard read only the file in front of it.
#
# `extensions.worktreeConfig` belongs to the same family and is deliberately
# NOT in this list, because refusing on the word alone made this change worth
# nothing on the repository that motivated it: extant's own config sets it, as
# does any repository where `git worktree` has enabled it, and this project
# does phase work in worktrees by convention. The extension does not override
# anything by itself - `config.worktree` does - so `remote_url` stats for that
# file instead, which is one stat and an exact question rather than a word
# match and a guess.
_UNSETTLED_BY = ("insteadof", "include")

# A value that is simply its own text. `configparser` was tried and is NOT a
# git config parser: it disagrees with git on three real syntaxes, and each
# disagreement survives into a wrong `owner/name` rather than into an error.
#
#     quoted value      git=owner/name   configparser="https://.../name.git"
#     inline ; comment  git=owner/name   configparser=https://... ; c
#     inline # comment  git=owner/name   configparser=https://... # c
#
# A quote preserves whitespace and escapes, `#` and `;` open an inline comment,
# and a backslash escapes the next character or continues the line onto the
# next. git handles every one of those; this refuses them, which turns each
# into a spawn instead of into a wrong answer.
#
# WHITESPACE INSIDE THE VALUE IS ALLOWED, and rejecting it was a real defect
# rather than caution. git strips only the whitespace SURROUNDING an unquoted
# value and keeps what is inside, so with quotes already refused there is
# nothing left to be ambiguous about - and `git clone` writes the source path
# verbatim, so every clone of a checkout living under a directory with a space
# in its name declined and paid the spawn. That is most of them on Windows.
# Found by running the suite against a fresh clone rather than the working
# tree, which is the check this project's own instructions ask for.
_PLAIN_VALUE = re.compile(r"^[^\"'#;\\]+$")


def remote_url(repo: Path, name: str) -> str | None:
    """The URL configured for remote `name`, read from the config file.

    None means THIS FILE COULD NOT SETTLE IT - ask git - and never "there is no
    such remote". The caller must treat it as a miss and spawn, because the
    same None covers an unreadable file, a syntax this declines to parse, a
    remote defined in the global config, and a repository that genuinely has no
    origin. Collapsing those into an absence is the shape that made
    `dead-pinned-ref` examine nothing and report clean once already.

    Read rather than spawned for the two reasons `is_shallow` and
    `common_git_dir` above give - it is one read, and a failed `rev-parse` has
    to be interpreted - and for a third this pair does not have: `--verify`
    opens one RunScope per document, so this repository-level fact was asked
    once per file. Measured on this machine, Windows: `git remote get-url
    origin` costs 28.92 ms (median of 20) and this read cost 0.19 ms (median
    of 200), a factor of 156, five times per `--verify` over this repository.
    Re-measured at 1.41 ms once `_unsettled_elsewhere` began statting the
    global and system scopes as well - ten candidate files, most of them
    absent, opened and read - which is still a factor of 20, and those reads
    are what stops this answering wrongly under a rewrite written anywhere
    but here.

    WHERE IT DOES NOT FIRE, stated because the saving is otherwise easy to
    overclaim: a GitHub Actions checkout carries four `[includeIf "gitdir:..."]`
    sections and a `config.worktree`, and either alone is enough for this to
    decline. So CI keeps paying the spawns - one per document holding a
    `rev:` pin, three of five here, since `_pinned_refs` stopped asking on a
    document with nothing to govern - and this is a developer-machine win
    rather than a universal one. That was measured from a red CI run whose
    spawn budget said 8 where a developer checkout says 5 - the guard doing
    exactly what it is for, on a config nobody here writes by hand.

    Through `common_git_dir`, which is what makes it work in a LINKED WORKTREE.
    A worktree's `.git` is a FILE pointing elsewhere, so a naive
    `repo/".git"/"config"` finds nothing there - and phase work in this project
    happens in worktrees by convention, so the naive version would have
    declined on every run a contributor actually makes: correct, and silently
    paying the spawn it was written to remove.

    WHERE THIS TECHNIQUE STOPS, because the next reader will be tempted by the
    ref lookups next door: this is ONE well-defined key with a validating
    guard, and a value git itself writes in one shape. Ref resolution is
    precedence between tags and heads, loose refs against `packed-refs`,
    symrefs, and peeling - reimplementing git rather than consulting it, with a
    wrong answer at the end of every corner missed. `refs.py` batches those
    into one `for-each-ref` instead, which is git answering once rather than
    this file guessing many times. Nothing here reads `.git/refs` or
    `packed-refs`, and nothing should.
    """
    shared = common_git_dir(repo)
    if shared is None:
        return None
    try:
        text = (shared / "config").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if any(word in text.lower() for word in _UNSETTLED_BY):
        return None
    # A per-worktree config can override what the shared one says, and it is
    # per WORKTREE, so it is looked for in this checkout's own git directory
    # rather than in the shared one this config came from.
    own = _own_git_dir(repo)
    if own is None or (own / "config.worktree").is_file():
        return None
    if _unsettled_elsewhere():
        return None
    found: list[str] = []
    in_section = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("["):
            if "]" not in line:
                return None       # unparseable header: trust nothing after it
            in_section = _names_remote(line[1:line.index("]")], name)
            continue
        if not in_section or "=" not in line:
            continue
        key, _, value = line.partition("=")
        # Case-insensitive, because git's key names are: `URL` and `url` are
        # the same key, and a config somebody hand-edited may carry either.
        if key.strip().lower() != "url":
            continue
        value = value.strip()
        if not _PLAIN_VALUE.match(value):
            return None           # a spelling this refuses to guess at
        found.append(value)
    # Exactly one, or nothing. `git remote get-url` without `--all` reports the
    # FIRST of several, and a second `url` line is unusual enough that being
    # sure is worth the 27 ms rather than being nearly sure for free.
    return found[0] if len(found) == 1 else None


def _unsettled_elsewhere() -> bool:
    """Could a scope other than the repository's own file change the answer?

    `url.<base>.insteadOf` is equally effective from the global config, the
    system config, a conditional include of either, the `GIT_CONFIG_COUNT`
    triplet, or the `GIT_CONFIG_PARAMETERS` that `git -c` exports to every
    process it starts, hooks included. The guard above read none of them.
    Found by a sandbox that injected exactly that: the `scp-style-ssh` row of
    tests/test_remote_from_disk.py went red with
    `git=https://github.com/acme/widget.git file=git@github.com:acme/widget.git`.

    That particular rewrite changes only the host and lands on the same
    `owner/name`. So does a mirror that keeps `owner/name` under a longer
    prefix, because the caller compares the LAST TWO path segments - the
    audit found the obvious example, `https://internal/mirror/acme/widget`,
    was exactly that. The one worth the reads moves the repository under
    another owner - `url.git@internal:widgets/.insteadOf =
    https://github.com/acme/` - and then `dead-pinned-ref` compares a
    project's pins against a repository git would not name, silently.

    Reads and stats only, in the over-refusing direction the local guard
    takes: a file that mentions a rewrite, an include or a remote at all
    declines, and one that cannot be read declines. Following an include -
    with its `gitdir:`, `onbranch:` and `hasconfig:` conditions - would be
    reimplementing git rather than consulting it, which is where this
    technique stops.

    The cost, stated: a developer whose global config carries the ordinary
    work-and-personal `includeIf` pays the spawn again on every run. Correct
    and slow is the degradation this fast path was designed for.
    """
    for path in _other_config_files():
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue          # absent, which is the common case
        except UnicodeDecodeError:
            return True
        if _mentions_a_remote(text):
            return True
    return any(_mentions_a_remote(value) for value in _injected_config())


def _mentions_a_remote(text: str) -> bool:
    """A rewrite, an include, or a remote of its own: anything in another
    scope that can put a different `remote.<name>.url` in front of git.

    A remote SECTION is refused here and not in the repository's own file,
    where the remote is expected: `git remote get-url` reports the FIRST
    value, scopes are read system, global, then local, so a remote defined
    globally wins the lookup over the one in the file.
    """
    lowered = text.lower()
    return (any(word in lowered for word in _UNSETTLED_BY)
            or "[remote" in lowered or "remote." in lowered)


def _other_config_files() -> list[Path]:
    """Every file git reads as global or system configuration, as far as it
    can be named without asking git. Absent files are fine; the caller
    skips them.

    Global: `GIT_CONFIG_GLOBAL` REPLACES both `~/.gitconfig` and the XDG
    file, so when it is set only it is read - that is what lets a test pin
    the scope to an empty file, and it is git's documented meaning rather
    than a shortcut. Otherwise `~` is found the way git finds it, `HOME`
    first, and every spelling of home this process can see is read, because
    reading one too many over-refuses and reading one too few answers
    wrongly.

    System: `GIT_CONFIG_SYSTEM` replaces `/etc/gitconfig` the same way.
    Otherwise `/etc/gitconfig` and `etc/gitconfig` under the install prefix
    of the `git` on PATH, which is where a Git for Windows or a Homebrew git
    keeps its system file - measured here: `C:/Program Files/Git/etc/gitconfig`
    beside a `git.exe` two directories below it. Finding that git is stats
    along PATH, not a process. A build whose system directory is somewhere
    else entirely - Apple's git keeps its under `usr/share/git-core` - is the
    residual this cannot see, and the reason the repository's own file stays
    the guard's first question.
    """
    env = os.environ
    files: list[Path] = []
    if "GIT_CONFIG_GLOBAL" in env:
        files.append(Path(env["GIT_CONFIG_GLOBAL"]))
    else:
        homes: list[str] = []
        drive, path = env.get("HOMEDRIVE"), env.get("HOMEPATH")
        for home in (env.get("HOME"), drive + path if drive and path else None,
                     env.get("USERPROFILE"), os.path.expanduser("~")):
            if home and home not in homes:
                homes.append(home)
        files += [Path(home) / ".gitconfig" for home in homes]
        xdg = env.get("XDG_CONFIG_HOME") or os.path.join(homes[0], ".config")
        files.append(Path(xdg) / "git" / "config")
    if "GIT_CONFIG_SYSTEM" in env:
        files.append(Path(env["GIT_CONFIG_SYSTEM"]))
    else:
        files.append(Path("/etc/gitconfig"))
        exe = _git_on_path()
        if exe:
            for spelling in (Path(exe), Path(os.path.realpath(exe))):
                files += [parent / "etc" / "gitconfig"
                          for parent in list(spelling.parents)[:3]]
        if env.get("ProgramData"):
            files.append(Path(env["ProgramData"]) / "Git" / "config")
    return files


def _git_on_path() -> str | None:
    """`shutil.which("git")`, without importing shutil.

    That module pulls the compression modules in behind it - 14 ms of import
    on this machine - and every post-commit hook pays every import before it
    validates anything. This is the part of `which` the lookup needs: the
    first `git` on PATH, under the Windows spellings where they apply.
    """
    names = ["git.exe", "git.cmd", "git.bat"] if os.name == "nt" else ["git"]
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if not directory:
            continue
        for name in names:
            candidate = os.path.join(directory, name)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
    return None


def _injected_config() -> list[str]:
    """Configuration arriving through the environment: the KEYS of the
    `GIT_CONFIG_COUNT` triplet, and `GIT_CONFIG_PARAMETERS` whole.

    Keys are enough for the triplet - a rewrite, an include or a remote all
    name themselves in the key. A count git cannot parse is returned as
    unsettling, because git refuses it too and the spawn will say so.
    """
    env = os.environ
    found: list[str] = []
    if env.get("GIT_CONFIG_PARAMETERS"):
        found.append(env["GIT_CONFIG_PARAMETERS"])
    try:
        count = int(env.get("GIT_CONFIG_COUNT") or "0")
    except ValueError:
        return ["remote."]
    found += [env.get(f"GIT_CONFIG_KEY_{i}", "") for i in range(count)]
    return found


def _names_remote(head: str, name: str) -> bool:
    """Does this section header name remote `name`?

    Both spellings git accepts, with the case rules git applies to each: the
    SECTION word is case-insensitive in both, the subsection is case-SENSITIVE
    inside quotes and case-insensitive in the dotted form. Getting that
    backwards would read `[remote "Origin"]` as origin, which git does not.
    """
    head = head.strip()
    lowered = head.lower()
    if lowered.startswith("remote "):
        return head[len("remote "):].strip() == '"%s"' % name
    return lowered == "remote.%s" % name.lower()


def rewrite_map_path(repo: Path) -> Path | None:
    """The commit-map `git filter-repo` leaves behind, or None if there is none.

    Measured 2026-08-30 on a real agent-written project: 12 of its 12 dead SHA
    references resolve through this file, and none of them resolves through
    `rev-list --all`, an unreachable-object scan or any reflog. A rewrite
    replaces every commit id at once, so it is a single event that kills a
    document's whole population of commit references - and it records exactly
    what each one became, at a fixed path, in the repository being checked.

    `--sha-map` has been able to REPAIR that since the flag existed. What was
    missing is that nobody looked: the operator had to know the flag existed
    and hand it this path.

    Finding the file does not repair anything. `--sha-map` stays the explicit
    opt-in for rewriting a document, because a validation run that edited
    prose on its own is the authoring this tool refuses.
    """
    shared = common_git_dir(repo)
    if shared is None:
        return None
    candidate = shared / "filter-repo" / "commit-map"
    return candidate if candidate.is_file() else None


def rewrite_journal_path(repo: Path) -> Path | None:
    """The journal the post-rewrite hook keeps, or None if there is none.

    A `filter-repo` run leaves the commit-map above; a rebase or an amend
    leaves nothing - except the `<old> <new>` pairs git writes to the
    post-rewrite hook's stdin, and to nothing else. The shipped hook
    appends them to `extant/rewrites` under the shared git directory, in
    the commit-map's own spelling, since 2026-09-15. Beside the commit-map
    rather than under the worktree, for the same reason it is: a rewrite
    belongs to the repository, and a linked worktree shares it.

    What this record can and cannot do is stated where it is written, in
    `hooks/extant-verify`: after a local rebase the old ids still resolve
    through the reflog, so no finding appears until that expires, and the
    file exists only on the machine that rewrote. It is the repair hint at
    the one moment the repair is cheap, not a new finding.
    """
    shared = common_git_dir(repo)
    if shared is None:
        return None
    candidate = shared / "extant" / "rewrites"
    return candidate if candidate.is_file() else None


# Environment variables that name a repository, and are dropped from every git
# process this package starts. `cwd=repo` decides which working tree git looks
# at; any of these decides whose HISTORY it answers about, and git exports
# `GIT_DIR` and `GIT_WORK_TREE` to every hook it runs. Verified before the
# fix: from a second repository, `GIT_DIR=../r1/.git git log -1` printed the
# first repository's subject while `rev-parse --show-toplevel` still named the
# second. So a hook checking any checkout other than the one it fired in - a
# submodule, a linked worktree, a sibling in a monorepo - had every git-backed
# rule answering about the wrong repository, in a run that printed exactly
# what a clean one prints. tests/test_git_environment.py pins the four that
# move the answer to "does this commit exist"; the other three are dropped
# with them because they name a repository in the same way.
_LOCATION_VARIABLES = frozenset((
    "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_NAMESPACE",
))

# What every child is told, over whatever the operator's shell says.
#
#   GIT_TERMINAL_PROMPT=0   never wait for a password. Nothing here should
#   GIT_ASKPASS=            need one, and a hook that blocks on a prompt - or
#                           pops an askpass dialog - is a hook that gets
#                           uninstalled.
#   GIT_OPTIONAL_LOCKS=0    do not take `index.lock` to refresh the index on
#                           the way past. A validator that made somebody's
#                           concurrent `git commit` fail with "index.lock
#                           exists" would be worse than one that found
#                           nothing.
#   LC_ALL=C                git's own messages in one language, whatever the
#                           locale. Nothing parses them; the reader of a
#                           report should still see the same stderr on every
#                           machine.
#   GIT_NO_LAZY_FETCH=1     in a partial repository, an object that is not
#                           present locally is MISSING rather than retrieved
#                           over the network mid-run. That retrieval is how a
#                           sweep of one repository once stalled for half an
#                           hour, and it contradicts the README's promise
#                           that nothing here touches the network. Honoured
#                           from git 2.42; older versions ignore it, and the
#                           partial-repository note beside the denominators
#                           is what remains for them.
_CHILD_SETTINGS = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_ASKPASS": "",
    "GIT_OPTIONAL_LOCKS": "0",
    "LC_ALL": "C",
    "GIT_NO_LAZY_FETCH": "1",
}


def environment() -> dict[str, str]:
    """The environment for a git process: the operator's, minus what names a
    repository, plus the settings above.

    Built per call rather than once at import. The environment can change
    between two calls in one process - a test sets a variable, a hook exports
    one - and a copy taken at import would silently answer from the state of
    the process at some earlier moment, which is the cache-lifetime failure
    `scope.py` exists to end.

    The `GIT_CONFIG_*` injections and `GIT_CONFIG_PARAMETERS` are deliberately
    NOT dropped. They carry configuration rather than a location - CI uses
    them for `safe.directory`, and `git -c` passes its arguments to hooks
    through them - and a child that lost them would fail where the parent
    works. What they CAN do is rewrite a remote URL; `remote_url` reads them
    for that and declines the fast path when they might.
    """
    env = {name: value for name, value in os.environ.items()
           if name not in _LOCATION_VARIABLES}
    env.update(_CHILD_SETTINGS)
    # `core.quotePath` off, carried in the environment rather than as a `-c`
    # in front of every subcommand, so that the argv every test and budget
    # records stays the question that was asked. On by default, it prints a
    # path holding any byte above ASCII as a quoted, octal-escaped string,
    # and the rename map read out of `log --name-status` then held
    # `"docs/\303\234bersicht.md"` where a document writes the umlaut - so
    # a renamed non-ASCII path was still reported dead but lost its "renamed
    # to" hint, and `--deleted-since` compared such a path against
    # `diff --name-only` and never matched it. The `-z` listings are
    # unaffected; `-z` already turns the quoting off.
    #
    # APPENDED to the operator's own `GIT_CONFIG_COUNT` set, never in place
    # of it: git reads the triplet from index 0 to count-1, and an empty
    # count is unset. A count git cannot parse is left exactly as it is,
    # because git refuses it with "bogus count" in the parent as well, and
    # repairing it here would have the child working where the operator's
    # own git does not.
    try:
        count = int(env.get("GIT_CONFIG_COUNT") or "0")
    except ValueError:
        return env
    if count < 0:
        return env
    env[f"GIT_CONFIG_KEY_{count}"] = "core.quotePath"
    env[f"GIT_CONFIG_VALUE_{count}"] = "false"
    env["GIT_CONFIG_COUNT"] = str(count + 1)
    return env


def _git(repo: Path, *args: str) -> str:
    """Run a git command in `repo`, returning stdout. Raises on non-zero.

    BYTES, decoded here, and the reason is the one `_document_at` in
    extant/deleted_since.py already writes at its own call site - it just never
    reached this function, which is the one every rule asks its questions
    through. `text=True` moves the decode INSIDE subprocess, and where it
    happens there is not the same on every platform:

    * On Windows a reader THREAD decodes. A byte git emits that is not valid
      UTF-8 kills that thread, `communicate()` hands back None, and this
      function returns None to callers annotated `str`. `_git_soft` cannot
      catch it because nothing was raised here to catch.
    * On POSIX the decode happens in this thread, at the end of
      `Popen._communicate`, and raises UnicodeDecodeError - which
      `_git_soft` does not list either, so the tolerant path is not tolerant
      of it.

    One silent wrong answer and one crash, out of the same line, decided by
    the operating system. The silent one is the worse of the two: a rule
    handed None finds nothing, and nothing prints exactly like a clean
    document.

    Neither is hypothetical. Any repository carrying pre-UTF-8 history - a
    latin-1 or Shift-JIS commit subject with no `encoding` header - emits
    such bytes from `git log`, and sweeping other people's repositories is
    what this tool is for.

    `errors="replace"` is right HERE and wrong one module over. This returns
    git's own METADATA - ref names, object ids, commit subjects - where a
    replaced character costs a garbled name inside a message. `_document_at`
    returns the DOCUMENT, where the same substitution would have every rule
    checking text the file does not contain, so that one decodes strictly
    and reports what it caught. Same bytes, different question, different
    answer.

    The newline translation is what `text=True` was doing - it is
    `subprocess._translate_newlines` verbatim - so a caller that splits on
    newlines sees exactly what it saw before.
    """
    done = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, check=True,
        env=environment(),
    )
    decoded = done.stdout.decode("utf-8", "replace")
    return decoded.replace("\r\n", "\n").replace("\r", "\n")
