"""Derive extant configuration by inspecting a repository.

Pure-ish detection functions, separated from install.py so they are testable
without copying files anywhere.

Everything here reports CONFIDENCE alongside the value, because the failure this
system is most prone to is a config that looks plausible and matches nothing.
A value marked "default" is a guess that was never confirmed against the repo,
and the installer says so out loud rather than letting it pass as derived.

Sampling is bounded throughout: a monorepo can have tens of thousands of commits
and thousands of branches, and detecting a naming convention needs a sample, not
a census.
"""
from __future__ import annotations

import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

COMMIT_SAMPLE = 500
BRANCH_SAMPLE = 400

DERIVED = "derived"    # measured from this repo
GUESSED = "guessed"    # inferred, but weak evidence - check it
DEFAULT = "default"    # not found here at all; carried over from elsewhere
UNKNOWN = "unknown"    # could not determine; needs a human


@dataclass(frozen=True)
class Observation:
    key: str
    value: object
    confidence: str
    evidence: str


def _git(repo: Path, *args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=repo, capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=True,
        ).stdout
    except (subprocess.CalledProcessError, OSError):
        return ""


# --- trunk -------------------------------------------------------------------

_TRUNK_CANDIDATES = ("main", "master", "develop", "trunk", "default")


_TAG_SHAPE = re.compile(r"^(.*?)(\d+\.\d+[\w.-]*)$")


def detect_release_tag(repo: Path) -> Observation:
    """The `release_tag` pattern, measured from the tags this repo actually has.

    The default recognises `v1.2.3` and `1.2.3`, which is what the corpus it was
    built against used. Plenty of projects do not: `release-1.2.3` is common in
    the JVM and .NET worlds, and a monorepo tags `api@2.0.0` per package. On
    those, the default captures nothing, the rule examines zero candidates, and
    a release claim is never checked at all - a rule that is inert while looking
    healthy, which is this project's defining failure.

    So the prefixes are read off the repository rather than assumed. Only
    prefixes that really occur become alternatives, which keeps the pattern as
    narrow as the evidence: a repo tagging `v1.2.3` gets exactly the default
    back, and one tagging `release-1.2.3` gets that shape and nothing wider.
    """
    tags = [t.strip() for t in _git(repo, "tag", "--list").splitlines() if t.strip()]
    prefixes: dict[str, int] = {}
    for tag in tags:
        match = _TAG_SHAPE.match(tag)
        if match:
            prefixes[match.group(1)] = prefixes.get(match.group(1), 0) + 1

    default = r"(?:released|shipped|tagged)\s+(?:in|as|at)\s+`?(v?\d+\.\d+[\w.-]*)`?"
    if not prefixes:
        why = "no version-shaped tags here" if not tags else f"{len(tags)} tags, none version-shaped"
        return Observation("release_tag", default, DEFAULT, why)

    # "" and "v" are what the default already covers; anything else is news.
    extra = sorted(p for p in prefixes if p not in ("", "v"))
    if not extra:
        return Observation("release_tag", default, DERIVED,
                           f"{len(tags)} tags, all v-prefixed or bare")

    alternatives = "|".join(re.escape(p) for p in [*extra, "v", ""])
    pattern = (r"(?:released|shipped|tagged)\s+(?:in|as|at)\s+"
               rf"`?((?:{alternatives})\d+\.\d+[\w.-]*)`?")
    shown = ", ".join(f"{p}N.N" for p in extra)
    return Observation("release_tag", pattern, DERIVED,
                       f"{len(tags)} tags; also matches {shown}")


def detect_trunk(repo: Path) -> Observation:
    """The integration branch, asked of git rather than inferred from prose.

    The previous version guessed the trunk from phrases in the document, which
    fails on any repo whose document happens not to mention a merge - and quietly
    produced "main" for a repo whose trunk was called something else.
    """
    head = _git(repo, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD").strip()
    if head:
        name = head.rsplit("/", 1)[-1]
        return Observation("trunk", name, DERIVED, f"origin/HEAD -> {name}")

    local = {ln.strip() for ln in _git(repo, "branch", "--format=%(refname:short)").splitlines()}
    for candidate in _TRUNK_CANDIDATES:
        if candidate in local:
            others = [c for c in _TRUNK_CANDIDATES if c in local and c != candidate]
            note = f"branch exists locally{'; also present: ' + ', '.join(others) if others else ''}"
            return Observation("trunk", candidate, DERIVED if not others else GUESSED, note)

    current = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    if current and current != "HEAD":
        return Observation("trunk", current, GUESSED, "no conventional trunk found; using current branch")
    return Observation("trunk", "main", UNKNOWN, "could not determine a trunk branch")


# --- branch naming -----------------------------------------------------------

_TICKET = re.compile(r"^([A-Z][A-Z0-9]{1,9})-\d+")


def detect_branch_pattern(repo: Path) -> Observation:
    """How branch names look in THIS repo, for the in-prose branch token.

    Handles the three shapes real repos use: slash-prefixed (`feature/x`),
    ticket-prefixed (`ABC-123-thing`), and flat. A large repo usually mixes them,
    so the pattern covers whatever clears a frequency floor rather than only the
    single most common.
    """
    names = [ln.strip() for ln in _git(
        repo, "branch", "-a", "--format=%(refname:short)"
    ).splitlines() if ln.strip()]
    names = [n.split("/", 1)[1] if n.startswith("remotes/origin/") else n for n in names]
    names = [n for n in names if n and n != "HEAD"][:BRANCH_SAMPLE]

    if not names:
        return Observation(
            "branch_token", r"`((?:feature|feat|fix)/[^`]+)`", DEFAULT,
            "no branches found to sample",
        )

    prefixes = Counter(n.split("/", 1)[0] for n in names if "/" in n)
    tickets = Counter(m.group(1) for n in names if (m := _TICKET.match(n)))

    floor = max(2, len(names) // 20)
    common = sorted(p for p, c in prefixes.items() if c >= floor)
    ticket_keys = sorted(t for t, c in tickets.items() if c >= floor)

    parts: list[str] = []
    evidence: list[str] = []
    if common:
        parts.append("(?:" + "|".join(re.escape(p) for p in common) + r")/[^`]+")
        evidence.append("slash prefixes: " + ", ".join(f"{p}/ x{prefixes[p]}" for p in common))
    if ticket_keys:
        parts.append("(?:" + "|".join(re.escape(t) for t in ticket_keys) + r")-\d+[^`]*")
        evidence.append("ticket keys: " + ", ".join(f"{t}- x{tickets[t]}" for t in ticket_keys))

    if not parts:
        return Observation(
            "branch_token", r"`([\w.-]+/[^`]+)`", GUESSED,
            f"{len(names)} branches, no repeated prefix; matching any slashed name",
        )
    return Observation(
        "branch_token", "`(" + "|".join(parts) + ")`", DERIVED,
        f"{len(names)} branches sampled; " + "; ".join(evidence),
    )


# --- commit conventions ------------------------------------------------------

_CONVENTIONAL = re.compile(r"^(\w+)(?:\([^)]*\))?!?: ")
_PHASEY = re.compile(r"\((\d+(?:\.\d+)+[a-z]?)\s+\w+\s*\d*\)")


def detect_commit_convention(repo: Path) -> list[Observation]:
    """Whether commit subjects carry a parseable grouping key.

    The status groups commits by "phase". Most repos have no such concept, and
    saying so plainly is better than shipping a regex that silently labels
    everything "unknown".
    """
    subjects = [s for s in _git(
        repo, "log", f"-n{COMMIT_SAMPLE}", "--format=%s"
    ).splitlines() if s.strip()]

    if not subjects:
        return [Observation("phase_task", None, UNKNOWN, "no commit history to sample")]

    conventional = Counter(m.group(1) for s in subjects if (m := _CONVENTIONAL.match(s)))
    phasey = sum(1 for s in subjects if _PHASEY.search(s))
    ticketed = sum(1 for s in subjects if _TICKET.search(s))
    n = len(subjects)

    out: list[Observation] = []
    if phasey >= max(3, n // 20):
        out.append(Observation(
            "phase_task", r"\((\d+(?:\.\d+)*[a-z]?)\s+\w+\b", DERIVED,
            f"{phasey}/{n} subjects carry a (version Task N) marker",
        ))
    elif ticketed >= max(3, n // 10):
        out.append(Observation(
            "phase_task", r"\b([A-Z][A-Z0-9]{1,9}-\d+)\b", DERIVED,
            f"{ticketed}/{n} subjects carry a ticket id; grouping by ticket",
        ))
    else:
        top = ", ".join(f"{k}: x{v}" for k, v in conventional.most_common(4))
        out.append(Observation(
            "phase_task", None, UNKNOWN,
            f"no grouping key found in {n} subjects"
            + (f" (conventional-commit types present: {top})" if top else ""),
        ))
    return out


# --- the document ------------------------------------------------------------

_DOC_NAMES = (
    "NEXT_SESSION.md", "HANDOFF.md", "STATUS.md", "CURRENT.md", "STATE.md",
    "PROGRESS.md", "CHANGELOG.md",
)
_DOC_DIRS = ("", "docs", "doc", ".github", "meta", "notes")


def find_documents(repo: Path) -> list[Path]:
    """Every plausible status document, nearest the root first.

    Returns ALL of them. A large repo often has several, and picking the first
    silently is how the tool ends up validating the wrong file.
    """
    found: list[Path] = []
    for directory in _DOC_DIRS:
        base = repo / directory if directory else repo
        if not base.is_dir():
            continue
        for name in _DOC_NAMES:
            candidate = base / name
            if candidate.is_file():
                found.append(candidate)
    return found


_HEADER = re.compile(r"^(#{1,4})\s+(\S+)", re.MULTILINE)
_DATEISH = re.compile(r"\b(20\d\d[-/]\d\d|v?\d+\.\d+)")
_MERGEISH = re.compile(
    r"(merged|shipped|released|landed|deployed)\s+(?:to|into|in|on)\s+"
    r"`?([\w./-]+)`?\s+(?:at|in|as)\s+`?([0-9a-f]{7,40})`?",
    re.IGNORECASE,
)


def inspect_document(path: Path) -> dict[str, object]:
    """Measure one document: entry headers, merge phrasing, size."""
    # open() rather than Path.read_text(newline=""): read_text did not accept a
    # newline argument until Python 3.13, so this line raised TypeError on 3.11
    # and 3.12 and took the whole installer down with it. write_text has taken
    # newline since 3.10, which is why only the read side broke.
    with open(path, encoding="utf-8", errors="replace", newline="") as fh:
        text = fh.read()

    # An ENTRY header repeats AND tends to carry a date or version. A reference
    # header repeats too ("## Notes"), so repetition alone picks the wrong one.
    scored: Counter[str] = Counter()
    for line in text.splitlines():
        match = _HEADER.match(line)
        if not match:
            continue
        prefix = f"{match.group(1)} {match.group(2)}"
        scored[prefix] += 2 if _DATEISH.search(line) else 1

    merges = _MERGEISH.findall(text)
    verbs = sorted({v.lower() for v, _t, _s in merges})
    targets = Counter(t for _v, t, _s in merges)

    return {
        "path": path,
        "lines": len(text.splitlines()),
        "header_scores": scored.most_common(6),
        "merge_verbs": verbs,
        "merge_count": len(merges),
        "merge_targets": targets.most_common(3),
    }
