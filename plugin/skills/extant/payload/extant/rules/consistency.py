"""inconsistent-artifact: do the files configured to agree actually agree?"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from extant.config import load_config
from extant.contract import Rule
from extant.finding import Finding
from extant.scope import Context

__all__ = ["RULE", "check", "examined", "probe"]


def _consistency_for(ctx: Context) -> dict:
    """The consistency block belonging to the repository being checked."""
    try:
        return load_config(ctx.repo).consistency
    except ValueError:
        return {}


class _Captured:
    """A stand-in exposing the one method the caller uses on a match.

    `_search_with_limit` cannot return a real `re.Match` from a subprocess,
    because a match object holds a reference to the compiled pattern and the
    subject string and does not survive being pickled across a pipe. The caller
    only ever asks for `group(1)`, so that is what this provides.
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def group(self, _index: int = 0) -> str:
        return self._value


def _search_with_limit(pattern: "re.Pattern[str]", content: str,
                       timeout: float | None):
    """`pattern.search(content)`, optionally under a wall-clock bound.

    Unbounded by default, and that is deliberate rather than neglected. Python's
    `re` does not release the GIL while matching, so a watchdog thread never
    runs and cannot interrupt a catastrophic backtrack. Process isolation is the
    only mechanism that actually works, and it costs a spawn per pattern -
    which `stress.py` case 11 puts at 200 per verify. Charging every user that
    for a problem almost none of them have is the wrong trade, so it is opt-in.

    Raises TimeoutError when the bound is exceeded. Returns None or an object
    exposing `group(1)`, matching what the caller does with a real match.
    """
    if timeout is None:
        return pattern.search(content)
    program = (
        "import re, sys, json\n"
        "spec = json.loads(sys.stdin.read())\n"
        "found = re.compile(spec['p'], spec['f']).search(spec['c'])\n"
        "sys.stdout.write(json.dumps("
        "found.group(1) if found and found.groups() else None))\n"
    )
    payload = json.dumps({"p": pattern.pattern, "f": pattern.flags,
                          "c": content})
    try:
        done = subprocess.run(
            [sys.executable, "-c", program], input=payload, text=True,
            capture_output=True, timeout=timeout, encoding="utf-8",
        )
    except subprocess.TimeoutExpired:
        raise TimeoutError(timeout) from None
    if done.returncode != 0:
        # The child failed for some reason other than time - a pattern the
        # parent compiled but the child could not, say. Fall back rather than
        # invent a finding about a pattern that may be perfectly good.
        return pattern.search(content)
    captured = json.loads(done.stdout or "null")
    return None if captured is None else _Captured(captured)


def _file_identity(path: Path) -> tuple:
    """A value equal for two paths that reach the same file.

    `(st_dev, st_ino)` is the filesystem's own answer, and it handles symlinks,
    hardlinks and case variants uniformly without knowing which it is looking
    at. It is not universally available: FAT32 and some network shares report
    `st_ino` as 0, and keyed on that every file on the volume would compare
    equal - reporting self-comparison on every configuration, which is a false
    positive on every run and worse than the hole this closes.

    A zero inode therefore falls back to the resolved, case-normalised path,
    which still follows symlinks and still collapses case variants on the
    platforms where those exist. A test asserts this distinguishes two
    known-different files before anything is built on it.
    """
    try:
        stat = path.stat()
        if stat.st_ino:
            return ("stat", stat.st_dev, stat.st_ino)
    except OSError:
        pass
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    return ("path", os.path.normcase(str(resolved)))


def check(ctx: Context, text: str) -> list[Finding]:
    """Named values that must agree across several files in the repository.

    THE RULE THAT CAME FROM THIS PROJECT'S OWN FAILURE. Three manifests
    advertised version 0.1.0 while the CHANGELOG documented 0.3.0. Anyone
    installing was told they were getting the first release. Nothing here could
    catch it, because no rule inspects numbers.

    That restriction still stands, and this does not weaken it. The forbidden
    question is whether a number is CORRECT - "the suite was 2238" has nothing
    to be checked against, so a rule that tried would cry wolf. Asking whether
    two files CONTRADICT EACH OTHER is a different question with a definite
    answer, needing nothing but the filesystem. Every value here is compared to
    another value in the same repository, never to a judgement about the world.

    `text` is ignored: this is about the repository, not the document. It runs
    once per validation, on the primary pass only, or the same disagreement
    would be reported once per document checked.
    """
    repo = ctx.repo
    # Configuration comes from the REPOSITORY BEING CHECKED, not from the
    # ambient CONFIG every other rule uses. This rule reads files by path,
    # so pointing it at one repository while holding another's file list is
    # meaningless - and it happened immediately: every temporary repository in
    # the test suite inherited this project's own version-consistency block and
    # was told four files were missing.
    #
    # Cheap, because it is one small TOML parse per validation, and only for
    # this rule.
    try:
        consistency = _consistency_for(ctx)
    except ValueError:
        # A malformed config in the target repo is reported by the loader on the
        # path that reads it for real; re-raising here would turn a validation
        # run into a crash about a different repository's settings.
        return []

    timeout = ctx.config.consistency_timeout
    findings: list[Finding] = []
    for name, sources in consistency.items():
        seen: dict[str, list[str]] = {}
        # Two spellings of one path are rejected at config load, by string.
        # A symlink, a hardlink, or a case variant on a case-insensitive
        # filesystem is a genuinely different route to the same bytes, and no
        # string comparison can see it - so the filesystem is asked instead.
        # Such a block agrees with itself forever while appearing to compare
        # two things, which is the shape of failure this project exists to
        # make visible.
        present = [rel for rel, _pattern in sources if (repo / rel).is_file()]
        if len(present) >= 2 and len({_file_identity(repo / rel)
                                      for rel in present}) < 2:
            findings.append(Finding(
                1, "inconsistent-artifact",
                f"consistency check `{name}` reads {len(present)} paths that "
                f"are the same file, so it compares a value with itself",
            ))
            continue
        for relative, pattern in sources:
            target = repo / relative
            if not target.is_file():
                findings.append(Finding(
                    1, "inconsistent-artifact",
                    f"consistency check `{name}` reads `{relative}`, "
                    f"which does not exist",
                ))
                continue
            content = target.read_text(encoding="utf-8", errors="replace")
            try:
                match = _search_with_limit(pattern, content, timeout)
            except TimeoutError:
                # A hang is a worse failure than an error, which is the whole
                # reason the bound exists. Naming the file and the pattern is
                # what makes it actionable.
                findings.append(Finding(
                    1, "inconsistent-artifact",
                    f"consistency check `{name}` gave up on `{relative}` after "
                    f"{timeout}s; the pattern backtracks and needs "
                    f"simplifying",
                ))
                continue
            if match is None:
                # A pattern matching nothing is the silent failure this project
                # is about: the check would pass forever having compared one
                # value with itself.
                findings.append(Finding(
                    1, "inconsistent-artifact",
                    f"consistency check `{name}` found no value in `{relative}`; "
                    f"the pattern matches nothing, so nothing is being compared",
                ))
                continue
            seen.setdefault(match.group(1), []).append(relative)

        if len(seen) > 1:
            parts = "; ".join(
                f"`{value}` in {', '.join(files)}" for value, files in sorted(seen.items())
            )
            findings.append(Finding(
                1, "inconsistent-artifact",
                f"`{name}` disagrees across files: {parts}",
            ))
    return findings


def examined(ctx: Context, text: str) -> int:
    """Every configured source file, across every block.

    A repository with no consistency block reports 0, which is the honest
    answer for a rule that speaks only when it is configured to.
    """
    return sum(len(sources) for sources in _consistency_for(ctx).values())


def probe(ctx: Context, text: str) -> str | None:
    """Not probeable by corrupting text, and honest about it.

    Every other probe mutates the document. This rule never reads the document,
    so no edit to `text` can make it fire. Returning None reports NO PROBE
    rather than inventing a pass, which keeps --selftest's report true.
    """
    return None


RULE = Rule(
    kind="inconsistent-artifact",
    sequence=9,   # matches the pre-refactor examined: dict literal's order
    check=check,
    scope="repository",
    in_archive=False,
    falsifiable="do the configured files state the same value?",
    probe=probe,
    examined=examined,
    subject_file=".extant.toml",
)
