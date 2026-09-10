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
import re
from pathlib import Path
from urllib.parse import quote

from extant import registry as _registry
from extant import strata
from extant.finding import Finding, Located

__all__ = [
    "BASELINE_NAME", "Collector", "FORMATS", "fingerprint", "format_github",
    "SWEEP_SECTIONS", "format_sarif", "format_sweep_sections", "format_text",
    "format_text_grouped", "group_parallel",
    "load_baseline", "render_findings", "sweep_entry_note",
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


# RFC 3986 3.3: a path segment is `pchar`, which is unreserved / pct-encoded /
# sub-delims / ":" / "@". Everything outside that has to be escaped. Listed
# rather than inferred so the set is arguable in review.
_PCHAR_SAFE = "!$&'()*+,;=:@"


def _sarif_uri(path: str) -> str:
    """A repository path as an RFC 3986 relative reference naming that file.

    SARIF 3.4.3 says `artifactLocation.uri` SHALL be a URI, and 3.10.1 repeats
    it for every URI-valued property. A raw repository path is often not one,
    and the failures differ in kind:

      `source/F#/LICENSE.md`  `#` is a DELIMITER, so a conformant consumer
                              reads the path `source/F` and a fragment. The
                              alert lands on a file that does not exist.
      `01 - Topics.md`        a space is forbidden outright. Measured in the
                              wild: this is what made SonarQube reject an
                              entire Trivy report rather than one result.
      `four%.md`              `%` not followed by two hex digits is a
                              malformed escape.
      `literal%20thing.md`    the worst, because it is VALID: it decodes to
                              `literal thing.md`, so the alert quietly names a
                              different file.

    Rejecting the whole document is the sharp end - every finding in it
    disappears, which is the silent failure one layer out. That is the same
    reasoning `--check-text --format=sarif` already applies when it refuses to
    emit `<stdin>`; this is that repair reaching the paths that are real.

    Encodes the MINIMUM. Every character RFC 3986 already permits in a segment
    is left exactly as it is, so this is a no-op on the 52,812 of 52,929
    corpus documents whose paths are valid references today and only the 117
    that are not change. Over-encoding would also be conformant and is not
    free: a consumer that matches literally instead of decoding would stop
    recognising the paths that work now, which trades this defect for a wider
    one.
    """
    segments = [quote(segment, safe=_PCHAR_SAFE) for segment in path.split("/")]
    # 3986 4.2: a first segment containing ":" is read as a scheme name, so
    # `weird:name/x.md` is not a relative reference at all. Escaping the colon
    # is the repair rather than the `./` prefix the RFC also offers - GitHub
    # matches this string against the pull-request diff, and a `./` prefix
    # matches no line of it. That was already found and fixed once, in
    # config.normalise_document; reintroducing it here would undo it.
    if segments and ":" in segments[0]:
        segments[0] = segments[0].replace(":", "%3A")
    return "/".join(segments)


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
                    "artifactLocation": {"uri": _sarif_uri(item.path)},
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


_BACKTICKED = re.compile(r"`([^`]*)`")


def _mask(message: str, value: str) -> str:
    """Blank one path segment's VALUE wherever it appears in a backticked token.

    Inside backticks only, and only as a whole `/`-delimited segment.
    `message.replace("en", "*")` also rewrites "when" and "documentation", which
    merges findings that say different things - and a measurement keyed on the
    raw message instead reports PX4 as 2,958 defects at 1.52x, which reads as
    "translation does not multiply anything" and reverses the conclusion.
    """
    def fix(match: "re.Match[str]") -> str:
        token = match.group(1)
        return "`" + "/".join("*" if part == value else part
                              for part in token.split("/")) + "`"
    return _BACKTICKED.sub(fix, message)


def _identity_keys(item: Located) -> list[tuple]:
    """Every identity this finding could share with another.

    One key per DIRECTORY segment, plus the finding's own path unchanged so
    that repeats inside a single document group even when that document sits at
    the repository root and has no directory to vary.

    The filename is never wildcarded, and that is the single most valuable
    constraint in this key rather than an oversight: allowing it merged
    `docs/CLI.md` with `docs/MockFunctionAPI.md` and `phase12-plan.md` with
    `phase13-plan.md`, which is 198 of the 228 wrong merges measured across the
    corpus.

    `kind`, `stratum` and `primary` are all in the key. The strata are a
    partition, and a primary finding renders bare while a non-primary renders
    with its path, so a group may not straddle either.
    """
    parts = item.path.split("/")
    base = (item.finding.kind, item.stratum, item.primary)
    keys = [base + (tuple(parts), item.finding.message())]
    for i in range(len(parts) - 1):
        wild = parts[:i] + ["*"] + parts[i + 1:]
        keys.append(base + (tuple(wild), _mask(item.finding.message(), parts[i])))
    return keys


def group_parallel(located: list[Located]) -> list[list[Located]]:
    """One group per distinct defect. Every finding appears in exactly one.

    A finding joins the LARGEST group available to it, ties broken by the
    leftmost path. Connected components are deliberately not used: they would
    chain A-B differing in segment 1 with B-C differing in segment 2 and report
    three findings that differ in two places as one defect. Measured cost of
    refusing that across the corpus: 6 findings.
    """
    keyed: dict[tuple, list[int]] = {}
    for index, item in enumerate(located):
        for key in _identity_keys(item):
            keyed.setdefault(key, []).append(index)

    taken: set[int] = set()
    groups: list[list[Located]] = []
    for _, members in sorted(keyed.items(), key=lambda kv: (-len(kv[1]), kv[0][3])):
        fresh = [i for i in members if i not in taken]
        if len(fresh) < 2:
            continue
        taken.update(fresh)
        groups.append([located[i] for i in fresh])
    groups.extend([located[i]] for i in range(len(located)) if i not in taken)

    for group in groups:
        group.sort(key=lambda item: (item.path, item.finding.line))
    groups.sort(key=lambda g: (g[0].path, g[0].finding.line))
    return groups


def format_text_grouped(groups: list[list[Located]]) -> list[str]:
    """Grouped human output. A group of one is byte-identical to `format_text`.

    Takes the groups `group_parallel` already formed rather than the findings,
    so a caller can report how many entries there are without grouping twice.
    `sweep.py` needs exactly that for its summary line.

    Every path is printed in full, one per line. A brace form like
    `docs/{en,ko}/intro.md` is shorter and makes `grep docs/ko/intro.md` find
    nothing, and text output is what people grep and pipe.

    Printing every path is also what keeps a wrong grouping cheap: nothing is
    hidden by one, so its whole cost is a heading that reads oddly. That is why
    a key with a 1.6 per cent wrong-merge rate is acceptable here and one with
    59 per cent is not.

    The header carries no line number. Four translations of one page hold the
    defect at four different lines, so a single number would be a false claim
    about three of them; the lines are on the per-document lines below it.

    ONE LINE PER DOCUMENT, not per occurrence, and that is not a tidy. The
    largest real group in the corpus is 28 citations of one dead anchor inside
    a single PX4 page: printed one per occurrence, that is a header plus 28
    identical paths, so grouping would turn 28 lines into 29 and make the
    output it exists to shorten longer. Repeats within a document collapse onto
    its line as `path:12, 40, 92`.
    """
    lines: list[str] = []
    for group in groups:
        if len(group) == 1:
            lines.extend(format_text(group))
            continue
        head = group[0].finding
        per_document: dict[str, list[int]] = {}
        for item in group:
            per_document.setdefault(item.path, []).append(item.finding.line)
        noun = "document" if len(per_document) == 1 else "documents"
        lines.append(f"[{head.kind}] {head.message()}"
                     f"   ({len(group)} occurrences in "
                     f"{len(per_document)} {noun})")
        lines.extend(f"    {path}:{', '.join(str(n) for n in numbers)}"
                     for path, numbers in per_document.items())
    return lines


SWEEP_SECTIONS = (
    ("vetted", "CONFIGURED - these decide the exit code"),
    ("unvetted", "UNREVIEWED - surveyed only, not gated"),
    ("repository", "REPOSITORY - about the repository itself, not gated"),
)


def format_sweep_sections(results: dict) -> tuple[list[str], int]:
    """A sweep's three sections as lines, plus how many entries they hold.

    Here rather than in `sweep.py`, and the reason is a ceiling rather than
    taste: `sweep.py` sat at exactly 896 lines against a 896-line module
    ceiling - it WAS the high-water mark the ceiling was set to - so the
    grouping could not be added to that file at all. This is a formatter, it
    returns lines like every other function in this module, and the module it
    came from shrinks.

    Grouping is per SECTION because that is where the batch is. A parallel copy
    of a page is the same kind of document as its siblings, so a translated
    tree is either wholly configured or wholly not and does not straddle the
    split. Measured rather than assumed: across 83 repositories and 60,076
    findings, sectioning costs exactly zero collapses.

    Returns the entry count alongside the lines so the caller can say
    `4,490 findings, 1,393 entries` without grouping a second time.
    """
    lines: list[str] = []
    entries = 0
    for label, heading in SWEEP_SECTIONS:
        if results[label]:
            grouped = group_parallel(results[label])
            entries += len(grouped)
            lines.append("")
            lines.append(heading)
            lines.extend(format_text_grouped(grouped))
    return lines, entries


def sweep_entry_note(entries: int, findings: int) -> list[str]:
    """The line saying grouping happened, or nothing when it did not.

    BOTH numbers whenever they differ. A reader who saw 4,490 findings last
    release and 1,393 entries this one has to be told nothing was dropped: a
    count that shrinks without saying why is the denominator failure this
    project exists to surface, arriving through one of its own features.

    Silent when the two agree, because "reported as 12 entries" beneath
    "12 finding(s)" is a line that tells a reader nothing and trains them to
    skip the summary.

    ZERO ENTRIES BESIDE ANY FINDINGS MEANS GROUPING DID NOT RUN, and is also
    silent. Only the text branch groups, so the machine formats reach here with
    `entries` still 0 - and without this clause a `--format=github` sweep
    printed `reported as 0 entr(y/ies)` beneath its annotations, and a SARIF
    one printed it to stderr where a stdout-only comparison could not see it.
    A group always holds at least one finding, so this cannot mask a real zero.
    """
    if not entries or entries >= findings:
        return []
    return [f"  reported as {entries} entr(y/ies): findings differing only in "
            f"one directory segment are grouped, and every document is named"]


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
