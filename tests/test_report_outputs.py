"""What extant/report.py renders, compared WHOLE: the SARIF document, the
annotations, the baseline file, the grouped text.

D7 ran mutmut over the package and 187 of report.py's 843 mutants survived
the whole suite, 118 of them in `format_sarif`. The tests asserted pieces of
each output - a level here, a URI there - so a mutant that renamed a key,
changed a fixed value or moved a column at a boundary went unseen. These
compare the complete output on fixtures built to reach the branches, and
`format_sarif`'s formatting as well as its content.

Every expected value is stated from the fixture and the format's rule, not
pasted from a run: a column is the subject's offset in its line plus one,
in UTF-16 code units; a descriptor's question is the registry rule's own
`falsifiable` text, which is what the SARIF publishes. The prose the outputs
carry is written once here, so a rewording is one edit.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from extant import registry, report
from extant.finding import Finding, Located
from extant.report import (_gh_escape, _utf16_len, fingerprint, format_github,
                           format_sarif, format_sweep_sections, format_text,
                           format_text_grouped, group_parallel, load_baseline,
                           render_findings, sarif_overflow_note, write_baseline)

TOOL = "https://github.com/scooter-sensei/extant"
STRATA = "ordinary, historical-record, generated, version-snapshot, vendored"


def _located(path: str, line: int, kind: str, detail: str, *,
             subject: str | None = None, repair: str | None = None,
             primary: bool = True, gating: bool = True,
             stratum: str = "ordinary") -> Located:
    return Located(path, Finding(line, kind, detail, subject, repair),
                   primary, gating, stratum)


# --- SARIF -------------------------------------------------------------------

# A descriptor's fixed parts, keyed by kind: the name (each hyphen-separated
# word title-cased and joined) and the short description (hyphens to spaces).
NAMES = {
    "dead-sha": ("DeadSha", "dead sha"),
    "dead-release-tag": ("DeadReleaseTag", "dead release tag"),
    "dead-md-link": ("DeadMdLink", "dead md link"),
    "inconsistent-artifact": ("InconsistentArtifact", "inconsistent artifact"),
    "not-a-rule": ("NotARule", "not a rule"),
    "raw-lfs-blob": ("RawLfsBlob", "raw lfs blob"),
    "dead-pinned-ref": ("DeadPinnedRef", "dead pinned ref"),
}


def _descriptor(kind: str) -> dict[str, Any]:
    """The rule descriptor SARIF publishes for `kind`. A kind the registry
    does not hold gets the fallback question and the `unknown` tag."""
    rules = {rule.kind: rule for rule in registry.RULES}
    rule = rules.get(kind)
    question = rule.falsifiable if rule else "not a registry rule"
    name, short = NAMES[kind]
    return {
        "id": kind,
        "name": name,
        "shortDescription": {"text": short},
        "fullDescription": {"text": f"Checks: {question}"},
        "help": {
            "text": f"This finding is falsifiable: {question}",
            "markdown": (
                f"**{kind}**\n\n"
                "This finding is falsifiable, and the question it asks is:\n\n"
                f"> {question}\n\n"
                "No rule here judges whether a value is *correct* - only whether "
                "something a document names still exists or still holds. See "
                f"[the rule table]({TOOL}#what-it-covers)."),
        },
        "helpUri": f"{TOOL}#what-it-covers",
        "defaultConfiguration": {"level": "error"},
        "properties": {"tags": ["documentation", rule.scope if rule else "unknown"],
                       "precision": "very-high", "problem.severity": "error"},
    }


def _result(item: Located, rule_index: int, uri: str,
            region: dict[str, Any]) -> dict[str, Any]:
    return {
        "ruleId": item.finding.kind,
        "ruleIndex": rule_index,
        "level": "error" if item.gating else "note",
        "message": {"text": item.finding.message()},
        "partialFingerprints": {"statusClaim/v1": fingerprint(
            item.path, item.finding.kind, item.finding.detail)},
        "properties": {"gates": item.gating, "stratum": item.stratum},
        "locations": [{"physicalLocation": {
            "artifactLocation": {"uri": uri}, "region": region}}],
    }


# The cited document. Each line is built to reach one branch of the snippet
# and column logic; the comment says which.
LINES = [
    # 1: the subject twice - the column is the FIRST occurrence, 5 characters
    # in ("see `"), so column 6 to 13.
    "see `abc1234` and `abc1234` again",
    # 2: the subject at column 1, and trailing spaces the snippet keeps.
    "v9.9 shipped the fix   ",
    # 3: exactly 400 characters - the cap, so not cut - with the subject
    # ending on the last column a region may name: 392 + 1 = 393, to 400.
    "x" * 392 + "def5678" + ".",
    # 4: past the cap - cut to 400 and marked - with the subject one column
    # beyond where a region may start (394 > 400 - 7), so no columns.
    "y" * 393 + "fed8765" + "z" * 10,
    # 5: the finding's subject is not on its line: no columns.
    "nothing cited here",
    # 6: a line ending in a capital letter the snippet must keep.
    "built `badc0de` for Mac OS X",
    # 7: a character outside ASCII, read as UTF-8 whatever the locale:
    # "caf\u00e9 `" is 6 code units, so column 7 to 14.
    "caf\u00e9 `feed123`",
]


def test_a_sarif_document_is_compared_whole(tmp_path: Path) -> None:
    """Every part of one run: descriptors from the registry and the fallback
    for a kind it does not hold, a result per finding with its region at
    each snippet boundary, the denominator, the NOTE lines, a rule switched
    off and a rule that raised - and the document's indentation."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_bytes(
        ("\n".join(LINES) + "\n").encode("utf-8"))
    found = [
        _located("docs/a.md", 1, "dead-sha", "`abc1234` is not a commit",
                 subject="abc1234", repair="the commit-map names `1234abc`"),
        _located("docs/a.md", 2, "dead-release-tag", "`v9.9` is not a tag",
                 subject="v9.9"),
        _located("docs/a.md", 3, "dead-sha", "`def5678` is not a commit",
                 subject="def5678"),
        _located("docs/a.md", 4, "dead-sha", "`fed8765` is not a commit",
                 subject="fed8765"),
        _located("docs/a.md", 5, "dead-sha", "`c0ffee1` is not a commit",
                 subject="c0ffee1"),
        _located("docs/a.md", 6, "dead-sha", "`badc0de` is not a commit",
                 subject="badc0de"),
        _located("docs/a.md", 7, "dead-sha", "`feed123` is not a commit",
                 subject="feed123"),
        # A survey finding in a vendored document that is not on disk: a
        # note, and no snippet.
        _located("vendor/lib/README.md", 3, "dead-md-link",
                 "links to `gone.md`, which does not exist", primary=False,
                 gating=False, stratum="vendored"),
        # A repository-scoped finding at line 0: the region starts at 1.
        _located("pyproject.toml", 0, "inconsistent-artifact",
                 "the version differs between two files"),
        # A kind the registry does not hold: its line is read, nothing to
        # point at.
        _located("docs/a.md", 1, "not-a-rule", "a finding of no rule"),
    ]

    out = format_sarif(
        found, tmp_path, examined={"dead-sha": 6, "dead-md-link": 0},
        notes=["  NOTE: one rule examined nothing"], off=["raw-lfs-blob"],
        errors=[("dead-pinned-ref", "ValueError: bad value: x")], run_kind="sweep")

    def snippet(n: int, **columns: int) -> dict[str, Any]:
        region: dict[str, Any] = {"startLine": n}
        if columns:
            region["startColumn"] = columns["start"]
            region["endColumn"] = columns["end"]
        region["snippet"] = {"text": LINES[n - 1]}
        return region

    cut = {"startLine": 4, "snippet": {"text": "y" * 393 + "fed8765" + " ..."}}
    kinds = ["dead-sha", "dead-release-tag", "dead-md-link",
             "inconsistent-artifact", "not-a-rule", "raw-lfs-blob", "dead-pinned-ref"]
    expected = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {"name": "extant", "informationUri": TOOL,
                                "rules": [_descriptor(kind) for kind in kinds]}},
            "automationDetails": {"id": "extant/sweep"},
            "columnKind": "utf16CodeUnits",
            "results": [
                _result(found[0], 0, "docs/a.md", snippet(1, start=6, end=13)),
                _result(found[1], 1, "docs/a.md", snippet(2, start=1, end=5)),
                _result(found[2], 0, "docs/a.md", snippet(3, start=393, end=400)),
                _result(found[3], 0, "docs/a.md", cut),
                _result(found[4], 0, "docs/a.md", snippet(5)),
                _result(found[5], 0, "docs/a.md", snippet(6, start=8, end=15)),
                _result(found[6], 0, "docs/a.md", snippet(7, start=7, end=14)),
                _result(found[7], 2, "vendor/lib/README.md", {"startLine": 3}),
                _result(found[8], 3, "pyproject.toml", {"startLine": 1}),
                _result(found[9], 4, "docs/a.md", snippet(1)),
            ],
            "invocations": [{
                "executionSuccessful": False,
                "toolExecutionNotifications": [
                    {"level": "note",
                     "message": {"text": "examined: dead-sha 6, dead-md-link 0"}},
                    {"level": "warning",
                     "message": {"text": "one rule examined nothing"}},
                    {"level": "error",
                     "message": {"text": "dead-pinned-ref raised ValueError: bad "
                                         "value: x. A rule that raised has not "
                                         "found nothing, it has failed to look."},
                     "associatedRule": {"id": "dead-pinned-ref", "index": 6},
                     "exception": {"kind": "ValueError",
                                   "message": "ValueError: bad value: x"}},
                ],
                "ruleConfigurationOverrides": [
                    {"descriptor": {"id": "raw-lfs-blob", "index": 5},
                     "configuration": {"enabled": False}}],
            }],
            "properties": {"examined": {"dead-sha": 6, "dead-md-link": 0}},
        }],
    }
    assert json.loads(out) == expected
    # Indented by two: the document is read in review as well as parsed.
    assert out == json.dumps(json.loads(out), indent=2)


def test_a_run_past_the_limit_says_how_many_it_left_out(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The cut in each of the three ways `format_sarif` is called past the
    limit, at a limit of 2 as the selection's own test does: as every mode
    calls it, handing the NOTE in with its other NOTE lines; with the
    denominator and no NOTE; and with neither. Each says the cut once, as a
    warning, and counts what it left out."""
    monkeypatch.setattr(report, "SARIF_RESULT_LIMIT", 2)
    found = [_located(f"docs/d{n}.md", n, "dead-md-link",
                      f"links to `x{n}.md`, which does not exist") for n in (1, 2, 3)]
    note = ("1 of 3 results are left out of the SARIF, because GitHub code "
            "scanning rejects a run holding more than 2. Kept first: the "
            f"findings that gate, then by document stratum ({STRATA}). The "
            "text format lists every one.")
    assert sarif_overflow_note(3) == [f"  NOTE: {note}"]
    examined = {"level": "note", "message": {"text": "examined: dead-md-link 3"}}
    warning = {"level": "warning", "message": {"text": note}}

    def run_of(**handed: Any) -> dict[str, Any]:
        run: dict[str, Any] = json.loads(format_sarif(found, **handed))["runs"][0]
        assert [r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
                for r in run["results"]] == ["docs/d1.md", "docs/d2.md"]
        return {key: run.get(key) for key in ("invocations", "properties")}

    assert run_of(examined={"dead-md-link": 3}, notes=sarif_overflow_note(3)) == {
        "invocations": [{"executionSuccessful": True,
                         "toolExecutionNotifications": [examined, warning]}],
        "properties": {"examined": {"dead-md-link": 3}, "omitted": 1}}
    assert run_of(examined={"dead-md-link": 3}) == {
        "invocations": [{"executionSuccessful": True,
                         "toolExecutionNotifications": [examined, warning]}],
        "properties": {"examined": {"dead-md-link": 3}, "omitted": 1}}
    assert run_of() == {
        "invocations": [{"executionSuccessful": True,
                         "toolExecutionNotifications": [warning]}],
        "properties": {"omitted": 1}}


def test_the_overflow_note_at_the_real_limit() -> None:
    """At GitHub's 25,000 itself, with the thousands separated."""
    assert sarif_overflow_note(25_000) == []
    assert sarif_overflow_note(25_001) == [
        "  NOTE: 1 of 25,001 results are left out of the SARIF, because GitHub "
        "code scanning rejects a run holding more than 25,000. Kept first: the "
        f"findings that gate, then by document stratum ({STRATA}). The text "
        "format lists every one."]


def test_columns_count_utf16_code_units_either_side_of_the_plane_boundary() -> None:
    """U+FFFF is the last character one code unit holds; U+10000 the first
    that takes two."""
    assert _utf16_len("\uffff") == 1
    assert _utf16_len("\U00010000") == 2
    assert _utf16_len("a\U0001f600b") == 4


# --- GitHub annotations ------------------------------------------------------

def test_the_workflow_command_escape_whole() -> None:
    """A property escapes `:` and `,` as well as what a message escapes -
    `%` first, so an escape is never escaped twice - and a message keeps
    them, because GitHub reads only the properties as delimited."""
    raw = "50%\rof\na:b,c"
    assert _gh_escape(raw) == "50%25%0Dof%0Aa:b,c"
    assert _gh_escape(raw, prop=True) == "50%25%0Dof%0Aa%3Ab%2Cc"


def test_annotations_are_compared_whole() -> None:
    found = [
        _located("docs/50%,off:a.md", 12, "dead-md-link",
                 "links to `b.md`: gone, moved"),
        _located("docs/c.md", 3, "dead-sha", "`abc1234` is not a commit",
                 repair="the commit-map names `1234abc`", gating=False),
    ]
    assert format_github(found) == [
        "::error file=docs/50%25%2Coff%3Aa.md,line=12,title=dead-md-link"
        "::links to `b.md`: gone, moved",
        "::notice file=docs/c.md,line=3,title=dead-sha"
        "::`abc1234` is not a commit; the commit-map names `1234abc`",
    ]


# --- the baseline ------------------------------------------------------------

def test_a_baseline_file_is_written_whole(tmp_path: Path) -> None:
    """One entry per (path, kind, detail), with how many occurrences it
    covers, sorted for review; ASCII on disk, LF endings, indented by two.
    Each neighbour differs from the repeated claim in one of the three
    fields, so none of them may share its entry."""
    claim = ("docs/a.md", "dead-sha", "`abc1234` is not a commit")
    found = [
        Located(claim[0], Finding(4, claim[1], claim[2]), True),
        Located(claim[0], Finding(9, claim[1], claim[2]), True),
        Located("docs/b.md", Finding(4, claim[1], claim[2]), True),
        Located(claim[0], Finding(5, "dead-release-tag", claim[2]), True),
        Located(claim[0], Finding(6, claim[1], "caf\u00e9 is not a commit"), True),
    ]
    path = tmp_path / ".extant-baseline.json"

    assert write_baseline(path, found) == 4

    def entry(where: str, kind: str, detail: str, escaped: str, count: int) -> str:
        return ("    {\n"
                f'      "fingerprint": "{fingerprint(where, kind, detail)}",\n'
                f'      "path": "{where}",\n'
                f'      "kind": "{kind}",\n'
                f'      "detail": "{escaped}",\n'
                f'      "count": {count}\n'
                "    }")

    entries = [
        entry("docs/a.md", "dead-release-tag", claim[2], claim[2], 1),
        entry("docs/a.md", "dead-sha", claim[2], claim[2], 2),
        entry("docs/a.md", "dead-sha", "caf\u00e9 is not a commit",
              "caf\\u00e9 is not a commit", 1),
        entry("docs/b.md", "dead-sha", claim[2], claim[2], 1),
    ]
    assert path.read_bytes() == (
        "{\n"
        '  "version": 1,\n'
        '  "tool": "extant",\n'
        '  "note": "Findings this project has accepted for now. Each is still '
        'wrong; they are simply not new. Prune with --baseline-check.",\n'
        '  "findings": [\n' + ",\n".join(entries) + "\n  ]\n}\n").encode("ascii")

    loaded = load_baseline(path)
    assert loaded == {
        fingerprint(where, kind, detail): {
            "fingerprint": fingerprint(where, kind, detail), "path": where,
            "kind": kind, "detail": detail, "count": count}
        for where, kind, detail, count in [
            ("docs/a.md", "dead-release-tag", claim[2], 1),
            ("docs/a.md", "dead-sha", claim[2], 2),
            ("docs/a.md", "dead-sha", "caf\u00e9 is not a commit", 1),
            ("docs/b.md", "dead-sha", claim[2], 1)]}


def test_a_baseline_edited_by_hand_is_read_as_utf8(tmp_path: Path) -> None:
    """The file is written in ASCII; one a person edits may not be, and it
    is read as UTF-8 whatever the platform's locale."""
    path = tmp_path / ".extant-baseline.json"
    path.write_bytes(json.dumps({"findings": [
        {"fingerprint": "f" * 32, "path": "docs/caf\u00e9.md", "kind": "dead-sha",
         "detail": "caf\u00e9", "count": 1}]}, ensure_ascii=False).encode("utf-8"))
    assert load_baseline(path) == {"f" * 32: {
        "fingerprint": "f" * 32, "path": "docs/caf\u00e9.md", "kind": "dead-sha",
        "detail": "caf\u00e9", "count": 1}}


def test_a_baseline_that_cannot_be_read_says_why(tmp_path: Path) -> None:
    missing = tmp_path / "nowhere.json"
    with pytest.raises(ValueError) as absent:
        load_baseline(missing)
    assert str(absent.value) == (
        f"no baseline at {missing}. Record one with --write-baseline, or drop "
        "--baseline to check everything.")

    wrong = tmp_path / "wrong.json"
    wrong.write_text('{"version": 1}', encoding="utf-8")
    with pytest.raises(ValueError) as unreadable:
        load_baseline(wrong)
    assert str(unreadable.value) == (
        f"{wrong} is not a baseline this version can read: 'findings'")


# --- every format through one entry point ------------------------------------

def test_every_format_goes_to_stdout_with_everything_it_was_handed(
        tmp_path: Path) -> None:
    """`render_findings` is what every mode calls. Each format renders its
    own lines, and SARIF receives every argument - the repository its
    snippets come from among them - and names a verify run when told
    nothing else. Only the lines are compared: every caller takes them and
    decides the stream itself."""
    (tmp_path / "a.md").write_text("see `abc1234`\n", encoding="utf-8")
    found = [_located("a.md", 1, "dead-sha", "`abc1234` is not a commit",
                      subject="abc1234")]
    handed: dict[str, Any] = {
        "examined": {"dead-sha": 1}, "notes": ["  NOTE: a note"],
        "off": ["raw-lfs-blob"], "errors": [("dead-md-link", "OSError: x")]}

    assert render_findings(found, "text")[0] == format_text(found)
    assert render_findings(found, "github")[0] == format_github(found)
    assert render_findings(found, "sarif", tmp_path, run_kind="sweep",
                           **handed)[0] == [
        format_sarif(found, tmp_path, run_kind="sweep", **handed)]
    assert render_findings(found, "sarif")[0] == [format_sarif(found)]
    assert json.loads(render_findings(found, "sarif")[0][0])[
        "runs"][0]["automationDetails"] == {"id": "extant/verify"}


# --- grouped text ------------------------------------------------------------

def _translations() -> list[Located]:
    """Two translations of one page holding one dead link, one claim
    repeated within a single document, and one finding alone."""
    return [
        _located("docs/ko/guide.md", 3, "dead-md-link",
                 "links to `docs/ko/gone.md`, which does not exist", primary=False),
        _located("docs/en/guide.md", 3, "dead-md-link",
                 "links to `docs/en/gone.md`, which does not exist", primary=False),
        _located("README.md", 9, "dead-sha", "`abc1234` is not a commit"),
        _located("README.md", 4, "dead-sha", "`abc1234` is not a commit"),
        _located("README.md", 7, "dead-release-tag", "`v9.9` is not a tag"),
    ]


def test_grouped_text_is_compared_whole() -> None:
    """A group heads with its FIRST member by path, which for a translated
    page is the language that sorts first; a group in one document says
    "document"; a group of one prints as the plain format does."""
    assert format_text_grouped(group_parallel(_translations())) == [
        "[dead-sha] `abc1234` is not a commit   (2 occurrences in 1 document)",
        "    README.md:4, 9",
        "line 7: [dead-release-tag] `v9.9` is not a tag",
        "[dead-md-link] links to `docs/en/gone.md`, which does not exist   "
        "(2 occurrences in 2 documents)",
        "    docs/en/guide.md:3",
        "    docs/ko/guide.md:3",
    ]


def test_a_sweep_counts_its_entries_across_every_section() -> None:
    """Each section grouped on its own, a blank line before each heading, an
    empty section left out, and the entry count summed over all three."""
    found = _translations()
    lines, entries = format_sweep_sections(
        {"vetted": found[2:], "unvetted": [], "repository": found[:2]})
    assert entries == 3
    assert lines == [
        "",
        "CONFIGURED - these decide the exit code",
        "[dead-sha] `abc1234` is not a commit   (2 occurrences in 1 document)",
        "    README.md:4, 9",
        "line 7: [dead-release-tag] `v9.9` is not a tag",
        "",
        "REPOSITORY - about the repository itself, not gated",
        "[dead-md-link] links to `docs/en/gone.md`, which does not exist   "
        "(2 occurrences in 2 documents)",
        "    docs/en/guide.md:3",
        "    docs/ko/guide.md:3",
    ]
