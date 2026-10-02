"""The skip-list: which tracked paths `exclude_paths` removes, and which
patterns it cannot read.

Pure, and read by both surveys that apply a configured skip-list - `--sweep`
through `apply_exclusions` in extant/sweep.py, and `--introduced-since`
through the same function and the `unusable_note` line here. Nothing in it
asks git or the disk, and nothing in it reads the configuration: the patterns
arrive as arguments, so a test can hold the matcher against `git check-ignore`
one pattern at a time.

Moved here byte for byte on 2026-10-02 (Phase 62), when sweep.py stood at 926
of its 927-line ceiling and the matcher needed room for a repair. The
functions kept their names, `_exclusion_regex` its underscore - no sibling
calls it.
"""
from __future__ import annotations

import re
from typing import Iterable

__all__ = [
    "excluded_documents", "unusable_exclusion", "unusable_note",
]


def unusable_exclusion(pattern: str) -> str | None:
    """Why `pattern` cannot mean what gitignore would make of it, or None.

    A leading `!` is NEGATION to gitignore and `[` opens a character class;
    this matcher implements neither, and used to escape both into literal
    characters - so `!docs/keep.md` matched only a path beginning with `!`,
    and `docs/[a-z]*.md` a directory literally named `[a-z]`. Each was a
    pattern quietly meaning something other than what it said. Named instead
    of supported, because no configuration here or in a known install writes
    either (Phase 48 counted); `!` anywhere but first is literal to gitignore
    too, and stays usable. A comment or an empty entry is no pattern at all,
    set aside by `_exclusion_regex` before this is asked, so it is refused
    nothing here either.
    """
    body = pattern.strip()
    if not body or body.startswith("#"):
        return None
    if body.startswith("!"):
        return "negation is not supported"
    if "[" in body:
        return "a character class is not supported"
    return None


def unusable_note(patterns: Iterable[str]) -> str | None:
    """The one line both surveys print for the patterns `unusable_exclusion`
    refuses, or None when there are none - one wording, from one place, so
    the two cannot come to describe the same pattern differently."""
    named = [f"{p} ({why})" for p in sorted(patterns)
             if (why := unusable_exclusion(p)) is not None]
    if not named:
        return None
    return ("  unusable, so they exclude nothing: " + ", ".join(named))


def _exclusion_regex(pattern: str) -> re.Pattern[str] | None:
    """Compile one gitignore-shaped path pattern, or None if it is unusable.

    `*` stops at a separator, `**` spans them where it is a whole segment,
    `?` matches one non-separator character. A pattern with NO separator
    matches a path segment anywhere, so `testdata` covers
    `hugolib/testdata/x.md` and nobody has to discover that `**/testdata/**`
    was required.

    Deliberately not `fnmatch`, whose `*` crosses `/` silently. A user writing
    `docs/*` to mean "the documents directly in docs" would have excluded the
    whole tree beneath it, and the only evidence would be a smaller number.
    """
    pattern = pattern.strip().replace("\\", "/")
    if not pattern or pattern.startswith("#"):
        return None
    if unusable_exclusion(pattern) is not None:
        return None
    anchored = "/" in pattern.rstrip("/")
    # A trailing slash names a DIRECTORY, as it does in a .gitignore, so a
    # file of that name is not matched and everything beneath it is. The
    # matcher took the file too until 2026-09-20, when git's own matcher was
    # fed every tracked path of 152 corpus clones beside it: five
    # disagreements in 793,684 distinct paths, every one a Debian packaging
    # FILE called `docs` or `vendor`, none of them a document. Closed so the
    # two agree on every shape this docstring claims.
    directory_only = pattern.endswith("/")
    body = pattern.strip("/")
    out: list[str] = []
    index = 0
    while index < len(body):
        if body.startswith("**", index):
            end = index + 2
            while end < len(body) and body[end] == "*":
                end += 1
            # A run of stars is git's `**` only where a separator or an end
            # bounds it on BOTH sides - `**/x`, `x/**/y`, `x/**` - and a
            # bounded `***` is one too. Anywhere else git reads the run as a
            # single `*`, so `a/**b` takes `a/xb` and not `a/x/b`. Every `**`
            # crossed separators here until a property held this matcher
            # beside `git check-ignore` (Phase 62): seven of eleven shapes
            # asked of git disagreed, all this one cause, none in any
            # configuration the project knows of.
            if ((index == 0 or body[index - 1] == "/")
                    and (end == len(body) or body[end] == "/")):
                # `**/` spans whole segments including none at all; a
                # trailing `**` swallows the rest of the path.
                if end < len(body):
                    out.append("(?:[^/]+/)*")
                    index = end + 1
                else:
                    out.append(".*")
                    index = end
                continue
            # Unbounded: the run's last star is read below as a lone `*`.
            index = end - 1
        char = body[index]
        if char == "*":
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(char))
        index += 1
    core = "".join(out)
    # What may follow the matched name: something beneath it, or nothing when
    # the name itself may be the file - never nothing for a directory pattern.
    beneath = r"(?:/.*)" if directory_only else r"(?:/.*)?"
    if anchored:
        # Rooted at the repository. A directory pattern also covers what is
        # underneath it, which is what a reader means by excluding a folder.
        source = rf"^{core}{beneath}$"
    else:
        # A bare name is a segment anywhere, and everything beneath it.
        source = rf"^(?:.*/)?{core}{beneath}$"
    try:
        return re.compile(source)
    except re.error:
        return None


def excluded_documents(paths: list[str],
                       patterns: tuple[str, ...]) -> tuple[list[str], dict[str, int]]:
    """(kept, {pattern: how many it matched}) for a configured skip-list.

    Returns the per-pattern count rather than a bare list, because a skip-list
    is the single most dangerous thing in a checker of this kind and the ways
    it goes wrong are both silent. One excludes more than intended - this
    project shipped a lint whose skip-list excluded every file it was meant to
    scan and passed on an empty scan. The other is a pattern that matches
    NOTHING, which is dead configuration that reads as a working exclusion
    forever.

    The caller prints both. A count nobody sees is the same as no count.
    """
    matched: dict[str, int] = {pattern: 0 for pattern in patterns}
    compiled = [(pattern, _exclusion_regex(pattern)) for pattern in patterns]
    kept: list[str] = []
    for path in paths:
        normalised = path.replace("\\", "/")
        hit = None
        for pattern, regex in compiled:
            if regex is not None and regex.match(normalised):
                hit = pattern
                break
        if hit is None:
            kept.append(path)
        else:
            matched[hit] += 1
    return kept, matched
