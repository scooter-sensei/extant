"""raw-lfs-blob: is a file `.gitattributes` routes through LFS really a pointer?

This module runs git through `subprocess` directly four times, which every
other rule reaches through `ctx.git`. Each needs something `run(repo, *args)`
cannot express: two `cat-file` batches fed on stdin, an `ls-tree -r -z` whose
NUL-separated output pairs with the `check-attr -z --stdin` beside it, and all
of them wanting BYTES rather than decoded text. tests/test_scope.py counts
those four rather than waving them through, so a fifth cannot appear unnoticed.
"""
from __future__ import annotations

import subprocess

from extant.contract import Rule
from extant.finding import Finding
from extant.scope import Context

__all__ = ["RULE", "check", "examined", "probe"]


# A Git LFS pointer is a small text stub. The spec fixes the first line, which
# is the whole test - no LFS binary is invoked and no network is touched.
_LFS_POINTER = b"version https://git-lfs.github.com/spec/v1"
# Pointers are ~130 bytes. Anything larger under an LFS filter cannot be one,
# so its size alone settles the question and its content is never read. That is
# what keeps this affordable on a repository with thousands of binaries.
_LFS_POINTER_MAX = 1024


def _lfs_is_configured(ctx: Context) -> bool:
    """Cheap gate: does this repository route anything through LFS at all?

    One file read, so a project with no `.gitattributes` - which is most of
    them - pays nothing for this rule beyond that.
    """
    try:
        text = (ctx.repo / ".gitattributes").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return any("filter=lfs" in line and not line.lstrip().startswith("#")
               for line in text.splitlines())


def _lfs_governed(ctx: Context) -> list[tuple[str, str]]:
    """(path, blob sha) for every tracked file the LFS filter governs.

    `git check-attr --stdin` answers for every path in ONE call. Asking per
    file is the same mistake the merge-claim rule made before it was batched,
    and a game repository has thousands of assets rather than a document's
    handful of claims.

    Attributes are read rather than the patterns re-implemented, because
    `.gitattributes` composes: nested files, negations and later rules
    overriding earlier ones. Re-deriving that from the text would be a second,
    worse implementation of something git already exposes.
    """
    key = str(ctx.repo)
    if key in ctx.run.lfs:
        return ctx.run.lfs[key]
    if not _lfs_is_configured(ctx):
        ctx.run.lfs[key] = []
        return []
    # HEAD's tree, not the index. This runs after a commit, so the committed
    # state is the thing being judged - and reading the index made the rule
    # examine ZERO files on a repository whose checkout had not completed,
    # while `.gitattributes` sat right there saying 47 patterns were LFS. A
    # denominator of 0 on a project full of assets is the shape of failure this
    # rule exists to report, so it must not be the rule's own behaviour.
    try:
        listing = subprocess.run(
            ["git", "ls-tree", "-r", "-z", "HEAD"], cwd=ctx.repo,
            capture_output=True, check=True).stdout.decode("utf-8", "replace")
    except (subprocess.CalledProcessError, OSError):
        ctx.run.lfs[key] = []
        return []   # unborn HEAD: nothing is committed to judge
    blobs: dict[str, str] = {}
    for record in listing.split("\0"):
        meta, _, path = record.partition("\t")
        parts = meta.split()
        if path and len(parts) >= 3 and parts[1] == "blob":
            blobs[path] = parts[2]
    if not blobs:
        ctx.run.lfs[key] = []
        return []
    # BYTES and NUL separators, for two separate reasons that both bit here.
    #
    # `text=True` makes Python translate "\n" to "\r\n" on the pipe under
    # Windows, so git received every path with a trailing carriage return,
    # treated it as a literal path character, and answered `unspecified`. Only
    # the LAST path - the one with no trailing newline - was matched. The rule
    # then reported 1 examined out of 4 and found the single real problem
    # anyway, so it looked perfect. Had the bad file sorted first it would have
    # printed 0 findings over 0 examined and read as a clean repository.
    #
    # `-z` removes the other half: without it git QUOTES any path containing a
    # space or a non-ASCII character, and game projects are full of both, so a
    # line-and-colon parse would silently skip exactly those assets.
    payload = ("\0".join(blobs) + "\0").encode("utf-8")
    try:
        raw = subprocess.run(
            ["git", "check-attr", "-z", "--stdin", "filter"], cwd=ctx.repo,
            input=payload, capture_output=True, check=True).stdout
    except (subprocess.CalledProcessError, OSError):
        ctx.run.lfs[key] = []
        return []
    fields = raw.decode("utf-8", "replace").split("\0")
    governed = []
    # `-z` emits a flat NUL-separated stream of (path, attribute, value).
    for i in range(0, len(fields) - 2, 3):
        path, _attr, value = fields[i], fields[i + 1], fields[i + 2]
        if value == "lfs" and path in blobs:
            governed.append((path, blobs[path]))
    ctx.run.lfs[key] = governed
    return governed


def check(ctx: Context, text: str) -> list[Finding]:
    """A file `.gitattributes` says lives in LFS, stored as a raw blob instead.

    `.gitattributes` is a document making a falsifiable claim: it says files
    matching these patterns are stored as LFS pointers. That claim can be
    false, and when it is, nothing says so. Git accepts the commit, the engine
    loads the asset, and the repository quietly carries a real binary in its
    history forever - where removing it means rewriting history.

    It happens two ways, both ordinary: a binary committed BEFORE
    `.gitattributes` covered its extension, and a commit made from a clone with
    no LFS filter installed. Neither produces a warning from anything.

    Deliberately NOT the other direction. "Is the LFS object present locally"
    looks like the same question and is unusable: a fresh CI checkout without
    `git lfs pull` holds zero objects, so that rule would report every asset in
    the project as missing on every run. Measured, not assumed.

    Reads no document, like `inconsistent-artifact`, and is silent on any
    repository that does not use LFS.
    """
    findings: list[Finding] = []
    governed = _lfs_governed(ctx)
    if not governed:
        return findings
    sizes: dict[str, int] = {}
    # Bytes again, and for the same reason: a "\r" appended to each SHA makes
    # every one of them unresolvable, and cat-file would report nothing.
    request = ("\n".join(sha for _p, sha in governed) + "\n").encode("ascii")
    try:
        out = subprocess.run(
            ["git", "cat-file", "--batch-check=%(objectname) %(objectsize)"],
            cwd=ctx.repo, input=request, capture_output=True,
            check=True).stdout.decode("utf-8", "replace")
    except (subprocess.CalledProcessError, OSError):
        return findings
    for line in out.split("\n"):
        parts = line.split()
        if len(parts) == 2 and parts[1].isdigit():
            sizes[parts[0]] = int(parts[1])

    # Only blobs small enough to BE a pointer need their contents read; anything
    # larger under an LFS filter is settled by its size alone. Those reads are
    # then batched into one `cat-file --batch`, because one subprocess per file
    # cost 40 seconds on a 7802-file project - which is not a slow hook, it is
    # an uninstalled one. Exactly the mistake the merge-claim rule already made.
    small = [sha for _p, sha in governed
             if 0 < sizes.get(sha, 0) <= _LFS_POINTER_MAX]
    pointers: set[str] = set()
    if small:
        request = ("\n".join(dict.fromkeys(small)) + "\n").encode("ascii")
        try:
            stream = subprocess.run(["git", "cat-file", "--batch"], cwd=ctx.repo,
                                    input=request, capture_output=True,
                                    check=True).stdout
        except (subprocess.CalledProcessError, OSError):
            return findings
        # `<sha> blob <size>\n<content>\n`, repeated. Parsed by declared length
        # rather than by splitting on newlines, because blob content is
        # arbitrary bytes and may contain them.
        cursor = 0
        while cursor < len(stream):
            end = stream.find(b"\n", cursor)
            if end == -1:
                break
            header = stream[cursor:end].split()
            cursor = end + 1
            if len(header) != 3 or not header[2].isdigit():
                break
            length = int(header[2])
            if stream[cursor:cursor + len(_LFS_POINTER)] == _LFS_POINTER:
                pointers.add(header[0].decode("ascii", "replace"))
            cursor += length + 1

    for path, sha in governed:
        size = sizes.get(sha)
        if size is None or sha in pointers:
            continue
        # An EMPTY file is not a violation. git-lfs passes zero bytes through
        # unchanged rather than writing a pointer, because there is nothing to
        # store, so a 0-byte blob under a filter is LFS behaving correctly.
        #
        # Verified rather than assumed: committing an empty file and a real one
        # under the same filter produces a 0-byte blob and a 126-byte pointer.
        # Measured on o3de/o3de, which declares 123 filters over 2,948 governed
        # files - 44 of its 45 findings were empty test fixtures, and the only
        # true one was an asset planted to check the rule still fires.
        if size == 0:
            continue
        findings.append(Finding(
            1, "raw-lfs-blob",
            f"`{path}` is tracked by an LFS filter but stored as a raw "
            f"{size}-byte blob, so it is committed into git itself",
        ))
    return findings


def examined(ctx: Context, text: str) -> int:
    """Paths under an LFS filter. A project not using LFS reports 0, which is
    the honest answer rather than a quiet pass."""
    return len(_lfs_governed(ctx))


def probe(ctx: Context, text: str) -> str | None:
    """No probe. This rule reads the repository, never the document.

    `--selftest` corrupts a claim in the prose and re-runs; there is no prose
    here to corrupt. Reported as "no probe" rather than passed off as working,
    which is the same treatment `inconsistent-artifact` gets.
    """
    return None


RULE = Rule(
    kind="raw-lfs-blob",
    check=check,
    scope="repository",
    in_archive=False,
    falsifiable="does every path under an LFS filter store a pointer?",
    probe=probe,
    examined=examined,
    subject_file=".gitattributes",
)
