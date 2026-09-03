"""Turning findings into the three shapes a reader or a machine consumes.

Text for a person, GitHub workflow annotations for a pull request, SARIF for a
code-scanning tool - plus the baseline file, which is the same information
written down so that a project adopting this on an old codebase can agree to
leave what is already there and still gate on what is new.

Nothing here reads ambient state or asks git anything. Every function takes the
findings it is to render and returns lines or a string, which is what makes the
formats testable without a repository and what keeps `--format` from being a
branch inside every mode. `format_sarif` reads the registry, because a rule's
`falsifiable` question becomes its published description; that is the one
outward reference in this file.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from extant import registry as _registry
from extant import strata
from extant.finding import Finding, Located

__all__ = [
    "BASELINE_NAME", "Collector", "FORMATS", "fingerprint", "format_github",
    "format_sarif", "format_text", "load_baseline", "render_findings",
    "write_baseline",
]


FORMATS = ("text", "github", "sarif")
_TOOL_URI = "https://github.com/scooter-sensei/extant"


# Public, because extant/cli.py matches a finding against the baseline with it
# and a leading underscore on a name a sibling reaches for is a false claim
# about the boundary - the rule text.py's own promotions state.
def fingerprint(path: str, kind: str, detail: str) -> str:
    """Stable identity for a finding, deliberately EXCLUDING the line number.

    GitHub uses partialFingerprints to recognise the same result across runs.
    Folding the line number in would make every finding brand new the moment
    text above it shifted, which is the churn the field exists to prevent.
    """
    payload = f"{path}\x00{kind}\x00{detail}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:32]


BASELINE_NAME = ".extant-baseline.json"


def _baseline_entry(item: Located, count: int = 1) -> dict[str, object]:
    """One recorded finding, written so a human can review the diff.

    The fingerprint alone would be enough to match on, and would make the file
    unreadable. A baseline is a list of things a project has agreed to leave
    broken for now, which is exactly the kind of file that must be legible in
    review - otherwise it becomes a place to hide things, which is the fair
    objection to having one at all.
    """
    return {
        "fingerprint": fingerprint(item.path, item.finding.kind, item.finding.detail),
        "path": item.path,
        "kind": item.finding.kind,
        "detail": item.finding.detail,
        # How many occurrences this amnesty covers. The fingerprint excludes
        # the line number so that reflowing a paragraph does not un-suppress
        # everything, and the price of that was forgiving the same claim pasted
        # anywhere, forever. Bounding the count keeps the churn-immunity and
        # removes the unbounded part.
        "count": count,
    }


def load_baseline(path: Path) -> dict[str, dict[str, str]]:
    """Recorded findings, keyed by fingerprint.

    A missing file is an error rather than an empty baseline. Treating it as
    empty would silently suppress nothing while the caller believed suppression
    was active, so a typo'd path would turn a ratcheted run back into an
    ordinary one without saying so.
    """
    if not path.is_file():
        raise ValueError(
            f"no baseline at {path}. Record one with --write-baseline, or drop "
            f"--baseline to check everything."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = data["findings"]
        return {e["fingerprint"]: e for e in entries}
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError(f"{path} is not a baseline this version can read: {exc}") from exc


def write_baseline(path: Path, located: list[Located]) -> int:
    """Record every current finding. Returns how many were written."""
    # Grouped by fingerprint, not one entry per occurrence. A baseline is a
    # list of things a project has agreed to leave broken and it is read in
    # review, so a repeated claim must stay one legible line with a count.
    tally: dict[str, int] = {}
    first: dict[str, Located] = {}
    for item in located:
        key = fingerprint(item.path, item.finding.kind, item.finding.detail)
        tally[key] = tally.get(key, 0) + 1
        first.setdefault(key, item)
    entries = [_baseline_entry(first[key], tally[key]) for key in sorted(tally)]
    document = {
        "version": 1,
        "tool": "extant",
        "note": ("Findings this project has accepted for now. Each is still "
                 "wrong; they are simply not new. Prune with --baseline-check."),
        "findings": sorted(entries, key=lambda e: (e["path"], e["kind"], e["detail"])),
    }
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(document, fh, indent=2, ensure_ascii=True)
        fh.write("\n")
    return len(entries)


class Collector:
    """Findings from one run, with the baseline applied as they arrive.

    Four values move together - what was recorded, what has been matched, how
    many occurrences of each are already spent, and how many were suppressed -
    and every one of them is meaningless without the other three. They used to
    be four locals in `run_validate` closed over by a nested `record()`, which
    is what kept that function from being split at all: the closure was the
    only thing holding them in one place.

    Here rather than beside the modes because this IS the baseline, and the
    baseline lives in this file. Nothing below reads ambient state or asks git
    anything, in keeping with the rest of the module: the caller supplies the
    recorded entries and decides where an echoed line goes.

    `echo` is how text output stays interleaved with its summaries, which is
    what a reader following along expects and what the existing tests pin.
    Passing a callable rather than a stream keeps the choice of stdout or
    stderr - which depends on whether stdout must carry pure JSON or a pure
    patch - with the mode that knows about it.
    """

    def __init__(self, baselined: dict[str, dict[str, str]] | None = None, *,
                 echo=None) -> None:
        # Empty, never None, so a caller that records without a baseline takes
        # the same path as one that records with an empty one.
        self.baselined = baselined or {}
        self.echo = echo
        self.located: list[Located] = []
        # Fingerprints seen this run. `--baseline-check` subtracts these from
        # the recorded set to find amnesties that have outlived their finding.
        self.matched: set[str] = set()
        # Occurrences already forgiven, per fingerprint, for this run.
        self.used: dict[str, int] = {}
        self.suppressed = 0

    def record(self, path: str, items: list[Finding], *, primary: bool) -> int:
        """Take one document's findings. Returns how many were NOT baselined.

        That count is what decides the exit code. A baselined finding is still
        wrong; it is simply not new.
        """
        new = 0
        for finding in items:
            item = Located(path, finding, primary,
                           stratum=strata.classify(path))
            mark = fingerprint(path, finding.kind, finding.detail)
            if mark in self.baselined:
                # Bounded by what was recorded. An entry written before counts
                # existed has none, and forgives one - the shape it had when
                # it was written.
                allowed = self.baselined[mark].get("count", 1)
                try:
                    allowed = int(allowed)
                except (TypeError, ValueError):
                    allowed = 1
                if self.used.get(mark, 0) < max(allowed, 1):
                    self.used[mark] = self.used.get(mark, 0) + 1
                    self.matched.add(mark)
                    self.suppressed += 1
                    continue
            new += 1
            self.located.append(item)
            if self.echo is not None:
                self.echo(format_text([item])[0])
        return new

    def stale(self) -> list[dict[str, str]]:
        """Recorded entries whose finding no longer occurs, in a stable order.

        A granted amnesty that outlives its finding is a suppression nobody
        can see the cost of, which is the fair objection to having a baseline
        at all. Sorted by fingerprint so two runs over one repository print
        the same list in the same order.
        """
        return [entry for mark, entry in sorted(self.baselined.items())
                if mark not in self.matched]


def _gh_escape(value: str, *, prop: bool = False) -> str:
    """Escape a workflow-command string.

    GitHub parses `::error k=v,k=v::message`, so a raw comma or colon inside a
    property silently truncates the annotation, and a newline in the message
    ends the command early. Paths and details here contain backticks and
    punctuation routinely, so this is the ordinary case rather than a corner.
    """
    out = value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    if prop:
        out = out.replace(":", "%3A").replace(",", "%2C")
    return out


def format_github(located: list[Located]) -> list[str]:
    """GitHub Actions annotations, which surface inline on the pull request.

    The severity mirrors the exit code, exactly as SARIF's does. A survey
    finding is a `notice`: `--sweep` and `--deleted-since` both exit 0 by
    design, and annotating them as errors put red marks on a pull request for
    claims the tool had already decided could not fail it.

    This was fixed in SARIF first and missed here for one commit, which is the
    cheaper half of the same lesson: when a misrepresentation is found in one
    output, the sibling formats are where to look next.
    """
    lines = []
    for item in located:
        level = "error" if item.gating else "notice"
        lines.append(
            f"::{level} file={_gh_escape(item.path, prop=True)},"
            f"line={item.finding.line},"
            f"title={_gh_escape(item.finding.kind, prop=True)}"
            f"::{_gh_escape(item.finding.message())}"
        )
    return lines


def format_sarif(located: list[Located], repo: Path | None = None, *,
                 examined: dict[str, int] | None = None,
                 run_kind: str = "verify") -> str:
    """SARIF 2.1.0, the format code-scanning tools interchange.

    The rule descriptors are generated from the registry, so a rule's
    `falsifiable` question becomes its published description. That is the same
    field the admission test already requires, which means a rule cannot reach
    this output without having stated the exact question it asks.

    `repo` and `examined` are optional so the function stays callable with a
    bare list, which is how the tests exercise it. Their absence costs
    presentation and the denominator, never correctness.
    """
    kinds = {rule.kind: rule for rule in _registry.RULES}
    seen: list[str] = []
    for item in located:
        if item.finding.kind not in seen:
            seen.append(item.finding.kind)

    descriptors = []
    for kind in seen:
        rule = kinds.get(kind)
        question = rule.falsifiable if rule else "not a registry rule"
        descriptors.append({
            "id": kind,
            "name": "".join(part.title() for part in kind.split("-")),
            "shortDescription": {"text": kind.replace("-", " ")},
            "fullDescription": {"text": f"Checks: {question}"},
            "help": {
                "text": f"This finding is falsifiable: {question}",
                # GitHub renders the markdown on the alert page and falls back
                # to `text` elsewhere, so both are supplied rather than one.
                "markdown": (
                    f"**{kind}**\n\n"
                    f"This finding is falsifiable, and the question it asks is:\n\n"
                    f"> {question}\n\n"
                    "No rule here judges whether a value is *correct* - only "
                    "whether something a document names still exists or still "
                    f"holds. See [the rule table]({_TOOL_URI}#what-it-covers)."
                ),
            },
            "helpUri": f"{_TOOL_URI}#what-it-covers",
            # Findings that reach `--verify` decide its exit code, so error is
            # the right DEFAULT. A survey result overrides it per result below.
            "defaultConfiguration": {"level": "error"},
            "properties": {
                "tags": ["documentation", rule.scope if rule else "unknown"],
                # Honest rather than flattering: the admission test requires
                # zero false positives on a real corpus before a rule ships.
                "precision": "very-high",
                "problem.severity": "error",
            },
        })

    results = []
    for item in located:
        region: dict[str, object] = {"startLine": max(1, item.finding.line)}
        snippet = _sarif_snippet(repo, item)
        if snippet is not None:
            # The subject is the bare token the claim is about, so pointing at
            # it turns "somewhere on line 12" into the claim itself underlined.
            # Computed against the FULL line, because SARIF columns are offsets
            # into the artifact rather than into the snippet.
            subject = item.finding.subject
            if subject and subject in snippet:
                at = snippet.index(subject)
                # UTF-16 CODE UNITS, because `columnKind` above says so. Python
                # indexes by code point, and the two differ for anything
                # outside the BMP: one emoji before the token shifts every
                # column after it by one. Measured on the corpus, 47 markdown
                # files carry 156 non-BMP characters, so this is a real
                # off-by-N rather than a theoretical one - and declaring a
                # column kind the numbers do not follow is worse than
                # declaring none.
                start = _utf16_len(snippet[:at]) + 1
                width = _utf16_len(subject)
            else:
                start = width = 0
            if 0 < start <= _SARIF_SNIPPET_LIMIT - width:
                region["startColumn"] = start
                region["endColumn"] = start + width
            if len(snippet) > _SARIF_SNIPPET_LIMIT:
                snippet = snippet[:_SARIF_SNIPPET_LIMIT] + " ..."
            region["snippet"] = {"text": snippet}
        results.append({
            "ruleId": item.finding.kind,
            "ruleIndex": seen.index(item.finding.kind),
            # A survey finding is reported and never gates. Publishing it as an
            # error contradicted the exit code and the README both.
            "level": "error" if item.gating else "note",
            # `message()`, not `detail`: the repair a finding can point at
            # belongs wherever a person reads it, and the fingerprint
            # below deliberately does not move with it.
            "message": {"text": item.finding.message()},
            "partialFingerprints": {
                "statusClaim/v1": fingerprint(
                    item.path, item.finding.kind, item.finding.detail),
            },
            # `stratum` beside `gates` for the same reason `gates` is here: a
            # consumer should be able to filter on what kind of document this
            # was without the tool having decided for it by hiding the result.
            "properties": {"gates": item.gating, "stratum": item.stratum},
            "locations": [{
                "physicalLocation": {
                    "artifactLocation": {"uri": item.path},
                    "region": region,
                },
            }],
        })

    run: dict[str, object] = {
        "tool": {"driver": {
            "name": "extant",
            "informationUri": _TOOL_URI,
            "rules": descriptors,
        }},
        # Lets a sweep upload and a verify upload sit side by side in code
        # scanning instead of one silently replacing the other.
        "automationDetails": {"id": f"extant/{run_kind}"},
        "columnKind": "utf16CodeUnits",
        "results": results,
    }
    if examined is not None:
        # THE DENOMINATOR. Every other output states what was examined, and
        # this one did not: a consumer seeing zero results could not tell a
        # clean repository from a run that checked nothing. SARIF carries it as
        # a notification rather than a result, because it is not a finding.
        summary = ", ".join(f"{kind} {n}" for kind, n in examined.items())
        blind = [kind for kind, n in examined.items() if n == 0]
        run["invocations"] = [{
            "executionSuccessful": True,
            "toolExecutionNotifications": [
                {"level": "note",
                 "message": {"text": f"examined: {summary}"}},
                *([{"level": "warning",
                    "message": {"text":
                                "examined nothing, so these rules report "
                                "nothing either: " + ", ".join(blind)}}]
                  if blind else []),
            ],
        }]
        run["properties"] = {"examined": examined}

    return json.dumps({
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [run],
    }, indent=2)


# A snippet exists to give an alert context, and no reader needs more than a
# line's worth. Uncapped it is an upload hazard: the longest single markdown
# line in the 39-repository corpus is 123,427 characters, and GitHub rejects a
# SARIF upload over 10 MB. One base64 image or minified block on a cited line
# would have been enough.
_SARIF_SNIPPET_LIMIT = 400


def _utf16_len(text: str) -> int:
    """Length in UTF-16 code units, which is what SARIF columns count.

    A character outside the Basic Multilingual Plane - an emoji, most of the
    rarer CJK - is one Python character and TWO UTF-16 code units. Anything
    that indexes with `len()` and then declares `columnKind` as
    `utf16CodeUnits` is quietly wrong past the first such character.
    """
    return len(text) + sum(1 for ch in text if ord(ch) > 0xFFFF)


def _sarif_snippet(repo: Path | None, item: Located) -> str | None:
    """The cited line, so an alert shows the claim rather than a line number.

    Optional because `format_sarif` is called in tests and by callers that
    have no repository in hand. A missing snippet costs presentation; a WRONG
    one would misreport where a finding is, so anything unreadable returns
    None rather than a guess.
    """
    if repo is None or item.finding.line < 1:
        return None
    try:
        with open(repo / item.path, encoding="utf-8", errors="replace",
                  newline="") as fh:
            for number, line in enumerate(fh, start=1):
                if number == item.finding.line:
                    return line.rstrip("\r\n")
    except OSError:
        return None
    return None


def format_text(located: list[Located]) -> list[str]:
    """The original human output, unchanged.

    A finding in the requested document prints bare; anything from the archive
    or an extra document is prefixed with its path. That asymmetry is preserved
    deliberately rather than tidied: it is what a reader of the primary case
    already expects, and what the existing tests pin.
    """
    return [
        item.finding.render() if item.primary
        else f"{item.path}: {item.finding.render()}"
        for item in located
    ]


def render_findings(located: list[Located], fmt: str, repo: Path | None = None,
                    *, examined: dict[str, int] | None = None,
                    run_kind: str = "verify") -> tuple[list[str], bool]:
    """Render for `fmt`. Returns the lines and whether they belong on stdout.

    SARIF has to be the ONLY thing on stdout or it is not parseable JSON, so
    the caller sends every human diagnostic to stderr in that mode. Text and
    annotation output are line-oriented and mix freely.

    `repo`, `examined` and `run_kind` reach SARIF only. Text and annotation
    output already carry the denominator on their own summary lines.
    """
    if fmt == "sarif":
        return [format_sarif(located, repo, examined=examined,
                             run_kind=run_kind)], True
    if fmt == "github":
        return format_github(located), True
    return format_text(located), True
