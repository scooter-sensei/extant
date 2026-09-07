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

import importlib.util
import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

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


def _tracked_paths(repo: Path) -> list[str]:
    """Every tracked path, read once. Git rather than a filesystem walk, so a
    vendored copy under an ignored directory cannot be resolved to."""
    return [ln.strip() for ln in _git(repo, "ls-files").splitlines()
            if ln.strip()]


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

    default = r"(?:released|shipped|tagged)\s+(?:in|as|at)\s+`?(v?\d+\.\d+(?:[\w.-]*[\w])?)`?"
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
               rf"`?((?:{alternatives})\d+\.\d+(?:[\w.-]*[\w])?)`?")
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
    # `--format=%(refname:short)` emits `origin/main`, NOT
    # `remotes/origin/main`, so the old prefix matched nothing and every
    # remote branch was counted under a phantom `origin/` prefix. The bare
    # `origin` and `origin/HEAD` symbolic ref are not branches at all.
    names = [n.split("/", 1)[1] if n.startswith("origin/") else n for n in names]
    names = [n for n in names if n and n not in ("HEAD", "origin")][:BRANCH_SAMPLE]

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
            # `+`, matching `_PHASEY` above. With `*` the EMITTED pattern
            # accepted single-component markers that the count never measured,
            # so the evidence and the rule installed from it described
            # different populations.
            "phase_task", r"\((\d+(?:\.\d+)+[a-z]?)\s+\w+\b", DERIVED,
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


# --- the wider document set --------------------------------------------------
#
# Measured across the 50-repository benchmark: what `install.py` configures
# unaided gates 12 findings of the 4,429 the survey sees in ordinary documents,
# and 40 of the 45 repositories it agreed to configure would exit 0 forever. A
# green run that learned nothing is the failure this whole project is about,
# arriving through document SELECTION rather than through the rules.
#
# Five policies were priced. The one below - the root plus three levels under a
# documentation directory, restricted to the ordinary stratum - gates 1,126
# ordinary findings across 3,305 pinned paths and makes 25 of 50 repositories
# report something, at 98.7-98.8 per cent precision.

# Conventional documentation directories. A NAME LIST, not a shape rule ("any
# directory that holds markdown"), for the reason `refs.py` gives for its own:
# a shape rule pulls in every test-fixture tree in the repository.
DOC_DIRS = ("docs", "doc", "documentation", "website", "site")

# EVERY SWEPT SUFFIX, taken from `refs.tracked_markdown`. Pinning a suffix the
# tool does not read writes an extra_docs entry no rule ever examines; missing
# one it does read drops a document out of the gate for no stated reason.
# `strata.py` carries the same list and the same instruction to keep it in step.
DOC_SUFFIXES = ("md", "markdown", "mdx", "rst")

# `payload/extant/strata.py`, by a path relative to this file. That path is an
# author-time fact: `detect.py` is not shipped - neither PAYLOAD nor
# PAYLOAD_TREES in install.py names it - so nothing here can reach an installed
# target, and the payload always sits beside the installer that copies it.
_STRATA_PATH = Path(__file__).resolve().parent / "payload" / "extant" / "strata.py"

# Depth 4 is a cliff, not a slope: 16 more findings for 2,220 more pinned paths,
# because `dead-md-link`'s false positives concentrate at depth 4 to 7.
WIDE_DEPTH = 3


def _strata_classifier() -> tuple[Callable[[str], str] | None, str]:
    """`strata.classify`, or None. The caller must refuse rather than degrade.

    Loaded BY PATH rather than imported. `install.py` and `detect.py` reach for
    argparse, re, shutil and pathlib and each other, and nothing else; putting
    `payload/` on sys.path to get one 96-line module would make every later
    import in the installer ambiguous about which tree it came from.

    Re-implementing the patterns here was refused on precedent. A hand-listed
    generator set drifted from `sites.py`, made a real improvement read as a
    regression, and both instruments were changed to derive from the tool
    rather than to describe it.
    """
    if not _STRATA_PATH.is_file():
        return None, f"strata.py not found at {_STRATA_PATH.as_posix()}"
    try:
        spec = importlib.util.spec_from_file_location("extant_strata", _STRATA_PATH)
        if spec is None or spec.loader is None:
            return None, f"{_STRATA_PATH.as_posix()} is not loadable as a module"
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:                                       # noqa: BLE001
        # Broad ON PURPOSE, and it REPORTS what it caught, which is the one
        # shape this project allows: executing a module can raise anything the
        # module can raise, and the entire value of this branch is that the
        # refusal below names which failure produced it instead of printing
        # what a healthy run prints.
        return None, f"strata.py did not load: {exc!r}"
    classify = getattr(module, "classify", None)
    if not callable(classify):
        return None, f"{_STRATA_PATH.as_posix()} has no classify()"
    return classify, f"strata from {_STRATA_PATH.as_posix()}"


def find_wide_documents(
    repo: Path, depth: int = WIDE_DEPTH
) -> tuple[list[str] | None, list[str]]:
    """Tracked documents at the root, plus `depth` levels under a documentation
    directory, restricted to the ordinary stratum.

    Returns (paths, notes) - `notes` is the account for the caller to print,
    never an empty list with no explanation.

    THREE outcomes, not two. `None` is a REFUSAL: something here could not be
    answered, the notes say which, and the caller must stop rather than write a
    config. `[]` is an ANSWER: this repository keeps no ordinary documents
    beyond the one already chosen, which is the honest result for a project
    whose documentation is all generated. Collapsing the two would turn every
    refusal into a repository that reads as clean.

    The refusal on a missing `strata` is the load-bearing safety property.
    Without the ordinary restriction this same enumeration measures 0.081
    findings per pinned path against the status quo's 0.106 - it is the one
    policy the measurement REJECTED, so a silent fallback would ship it.

    The notes are LINES rather than one sentence because the per-stratum
    exclusions are the point. Unstated, the restriction is invisible, and
    `strata.py`'s whole argument is that a label a reader can see beats an
    exclusion they cannot.
    """
    if depth < 0:
        return None, [f"--wide-docs: {depth} is not a depth"]

    classify, why = _strata_classifier()
    if classify is None:
        return None, [
            f"--wide-docs: {why}",
            "  REFUSED. Without the ordinary/vendored/generated/historical "
            "split this enumerates every tracked document, which measured "
            "WORSE than configuring nothing (0.081 findings per pinned path, "
            "against 0.106 today).",
        ]

    tracked = _tracked_paths(repo)
    if not tracked:
        return None, [
            "--wide-docs: git ls-files reported no tracked paths",
            "  REFUSED. An empty index reads exactly like a repository with "
            "nothing to check, which is a clean sweep on a repository nobody "
            "looked at.",
        ]

    # git QUOTES a path holding unusual bytes - `"caf\303\251.md"` - whenever
    # core.quotePath is on, which is the default. Pinning that spelling writes
    # an extra_docs entry naming a file that is not there, and `gate.py` reports
    # an absent entry as `missing-document` - a finding this installer would
    # have manufactured. Left out, and COUNTED, because a silent drop is the
    # other way to be wrong here.
    quoted = [p for p in tracked if p.startswith('"')]
    docs = [p for p in tracked if not p.startswith('"')
            and p.rsplit(".", 1)[-1] in DOC_SUFFIXES]

    keep = {d for d in docs if "/" not in d}
    for d in docs:
        parts = d.split("/")
        if 2 <= len(parts) <= depth + 1 and parts[0].lower() in DOC_DIRS:
            keep.add(d)

    excluded: Counter[str] = Counter()
    ordinary: list[str] = []
    for d in sorted(keep):
        stratum = classify(d)
        if stratum == "ordinary":
            ordinary.append(d)
        else:
            excluded[stratum] += 1

    at_root = sum(1 for d in ordinary if "/" not in d)
    notes = [f"--wide-docs: {len(ordinary)} "
             f"document{'' if len(ordinary) == 1 else 's'} "
             f"(root {at_root}, docs/ {len(ordinary) - at_root}), "
             f"ordinary stratum only, depth {depth}"]
    if excluded:
        notes.append("  " + ", ".join(
            f"{count} excluded as {stratum}"
            for stratum, count in sorted(excluded.items(),
                                         key=lambda kv: (-kv[1], kv[0]))))
    if quoted:
        notes.append(f"  {len(quoted)} tracked path(s) left out: git quoted "
                     f"them, and a quoted spelling names no file on disk")
    if not any("/" in d and d.split("/")[0].lower() in DOC_DIRS for d in docs):
        # "No documents under", not "no directory": a `docs/` holding only
        # images or a mkdocs.yml is a directory that exists and contributes
        # nothing, and saying the directory is absent would send a reader
        # looking for the wrong thing.
        notes.append("  no tracked documents under "
                     + ", ".join(f"{d}/" for d in DOC_DIRS)
                     + "; root documents only")
    if ordinary:
        # Every pinned path is a standing liability: `gate.py` makes an absent
        # extra_docs entry a `missing-document` finding and exit 1, on purpose.
        # Said BEFORE the config is written, because the cost is real and its
        # rate has not been measured.
        notes.append("  each becomes an extra_docs entry; a moved file will be "
                     "reported as missing")
    else:
        notes.append("  no ordinary documents found; writing NO extra_docs key "
                     "- an empty list is a claim, and there is nothing to claim")
    return ordinary, notes


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
