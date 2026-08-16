"""dead-pinned-ref: does the version an install snippet pins actually exist?"""
from __future__ import annotations

import re
import subprocess

from extant.contract import Rule
from extant.finding import Finding
from extant.scope import Context

__all__ = ["RULE", "check", "examined", "probe"]

# An install snippet pins a version. `repo:` and `rev:` are pre-commit's fixed
# syntax rather than any project's habit, so like markdown link syntax there is
# nothing here to measure and nothing to configure.
# YAML quoting around a rev. Named rather than inlined so the mutation that
# removes it has a legible anchor.
_PIN_QUOTES = "'\""
_PIN_REPO = re.compile(r"^\s*(?:-\s*)?repo:\s*(\S+)")
_PIN_REV = re.compile(r"^\s*rev:\s*([^\s#]+)")


def _normalise_remote(url: str) -> str | None:
    """A remote URL reduced to `owner/name`, lowercased.

    Both spellings of the same repository must compare equal: an SSH remote
    reads `git@github.com:owner/name.git` and the URL a README tells people to
    use reads `https://github.com/owner/name`.
    """
    url = url.strip().rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    parts = [p for p in url.replace(":", "/").split("/") if p]
    return "/".join(parts[-2:]).lower() if len(parts) >= 2 else None


def _own_remote(ctx: Context) -> str | None:
    """This repository as `owner/name`, or None when it has no origin.

    Memoised, because the answer is a property of the REPOSITORY and this is
    asked once per DOCUMENT. `--sweep` therefore spawned one `git remote
    get-url` per file to receive the same string every time: profiled over 400
    documents, that was 11.3 seconds of a 16.2 second run - 70 percent of the
    work, for one answer.

    A remote cannot change while a process runs, and every mode here is a
    single short-lived process. `None` is a real answer, meaning no origin, so
    membership decides rather than truthiness.
    """
    key = str(ctx.repo)
    if key not in ctx.run.own_remote:
        ctx.run.own_remote[key] = _normalise_remote(
            ctx.git.soft(ctx.repo, "remote", "get-url", "origin"))
    return ctx.run.own_remote[key]


def _pinned_refs(ctx: Context, text: str) -> list[tuple[int, str]]:
    """Every `rev:` pin governed by a `repo:` naming THIS repository.

    The governing `repo:` is what keeps this rule honest. A project documenting
    somebody else's pre-commit hook writes `rev: v4.5.0` for a tag that lives in
    somebody else's repository, and checking that here would report a finding on
    a line that is perfectly correct. Only pins aimed at us are answerable, so
    only those are asked about.
    """
    own = _own_remote(ctx)
    if own is None:
        return []
    found: list[tuple[int, str]] = []
    governing: str | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        match = _PIN_REPO.match(line)
        if match:
            governing = _normalise_remote(match.group(1))
            continue
        match = _PIN_REV.match(line)
        if match and governing == own:
            # `rev: ''` is pre-commit's OWN documented placeholder - the state
            # a snippet ships in for `pre-commit autoupdate` to fill. It is not
            # a pin that broke; it is the absence of one, and reporting it
            # accuses a project of the idiom its own tool prescribes.
            # python-poetry/poetry ships two, and both were reported.
            #
            # Quotes come off for the same reason a bare rev is accepted:
            # `rev: 'v1.2.3'` is the same pin, and looking it up with the
            # quotes attached finds nothing. Measured across 30 repositories -
            # 69 bare, 4 quoted, 2 empty - so the quoted spelling is a latent
            # false positive waiting on the first project to pin itself
            # that way.
            ref = match.group(1).strip(_PIN_QUOTES)
            if ref:
                found.append((number, ref))
    return found


def check(ctx: Context, text: str) -> list[Finding]:
    """An install snippet pinning a version of THIS repository that does not exist.

    The one rule that deliberately reads INSIDE code blocks. Every other claim
    rule blanks them first, because an example in a fence is not a promise - but
    an install snippet is the opposite of an example. It is the one block on the
    page a reader will copy verbatim, and a version that does not exist fails
    for them on first use.

    This exists because it happened twice here. A README pinned `rev: v0.5.0`
    for a fortnight while the repository had no tags at all, and the rule that
    would have caught the claim in prose - `dead-release-tag` - cannot see into
    a fence by design. The blind spot was documented, understood, and still cost
    two broken instructions.

    Fenced and indented blocks both work, and neither is parsed: the `repo:` and
    `rev:` shape does not occur in prose, so matching them line by line covers
    every block style without needing to know where blocks begin.
    """
    findings: list[Finding] = []
    for number, ref in _pinned_refs(ctx, text):
        try:
            ctx.git.run(ctx.repo, "rev-parse", "--verify", f"{ref}^{{commit}}")
        except (subprocess.CalledProcessError, OSError):
            findings.append(Finding(
                number, "dead-pinned-ref",
                f"install snippet pins `{ref}`, which does not exist here; "
                f"anyone copying this block gets an error",
                subject=ref,
            ))
    return findings


def examined(ctx: Context, text: str) -> int:
    """Counted the same way the rule finds them, so a repository with no origin
    remote reports 0 examined rather than a silent pass."""
    return len(_pinned_refs(ctx, text))


def probe(ctx: Context, text: str) -> str | None:
    """Repoint a real install pin at a version that does not exist.

    Located by line rather than by pattern, because only a pin governed by a
    `repo:` naming this repository is checked at all. Corrupting the first
    `rev:` on the page would prove nothing if that one belongs to somebody
    else's hook, and would report a working rule as broken.
    """
    pins = _pinned_refs(ctx, text)
    if not pins:
        return None
    number, ref = pins[0]
    lines = text.splitlines(keepends=True)
    target = lines[number - 1]
    lines[number - 1] = target.replace(ref, "v0.0.0-extant-selftest", 1)
    return "".join(lines)


RULE = Rule(
    kind="dead-pinned-ref",
    check=check,
    scope="whole-file",
    in_archive=True,
    falsifiable="does `git rev-parse <ref>` resolve, for a pin naming this repository?",
    probe=probe,
    examined=examined,
)
