"""What counts as one defect, and what must never be merged into one.

Measured over 60,076 findings in 83 repositories before this shipped: allowing
ANY path segment to vary merges 228 of 388 sibling-document groups that are not
parallel copies at all, and forbidding the FILENAME to vary removes 198 of those
228. That is why the key is directory-only, and it is the case most likely to be
"simplified" back out by someone who has not read the measurement.

The design and every figure behind it:
`extant-hardening/specs/2026-09-07-parallel-tree-dedup-design.md`.
"""
from __future__ import annotations

import json

from extant.finding import Finding, Located
from extant.report import (
    format_github, format_sarif, format_sweep_sections, format_text,
    format_text_grouped, group_parallel, sweep_entry_note,
)


def at(path, line=1, kind="dead-md-link",
       detail="links to `../g.md`, which does not exist",
       primary=False, stratum="ordinary"):
    return Located(path, Finding(line, kind, detail), primary, stratum=stratum)


def paths_of(groups):
    return sorted(tuple(sorted(i.path for i in g)) for g in groups)


def test_a_translated_page_is_one_defect():
    located = [at("docs/en/intro.md", 12), at("docs/ko/intro.md", 14),
               at("docs/uk/intro.md", 9)]
    groups = group_parallel(located)
    assert len(groups) == 1
    assert len(groups[0]) == 3


def test_the_filename_may_not_vary():
    """The single most valuable constraint in the key. See the module docstring."""
    located = [at("docs/CLI.md"), at("docs/MockFunctionAPI.md")]
    assert len(group_parallel(located)) == 2


def test_two_strata_never_merge():
    located = [at("build/README.md", stratum="generated"),
               at("hack/README.md", stratum="ordinary")]
    assert len(group_parallel(located)) == 2


def test_primary_and_non_primary_never_merge():
    located = [at("docs/en/x.md", primary=True),
               at("docs/ko/x.md", primary=False)]
    assert len(group_parallel(located)) == 2


def test_two_rules_never_merge():
    located = [at("docs/en/x.md", kind="dead-md-link"),
               at("docs/ko/x.md", kind="dead-md-anchor")]
    assert len(group_parallel(located)) == 2


def test_the_message_is_masked_only_inside_backticks():
    """`en` must not rewrite the word "when" in prose."""
    a = at("docs/en/x.md",
           detail="links to `docs/en/g.md`, which does not exist when read")
    b = at("docs/ko/x.md",
           detail="links to `docs/ko/g.md`, which does not exist when read")
    assert len(group_parallel([a, b])) == 1
    c = at("docs/en/x.md", detail="broken when parsed")
    d = at("docs/ko/x.md", detail="broken whko parsed")
    assert len(group_parallel([c, d])) == 2


def test_different_targets_do_not_merge():
    a = at("docs/en/x.md", detail="links to `a.md`, which does not exist")
    b = at("docs/ko/x.md", detail="links to `b.md`, which does not exist")
    assert len(group_parallel([a, b])) == 2


def test_repeats_in_one_document_group():
    located = [at("README.md", 4), at("README.md", 40), at("README.md", 90)]
    groups = group_parallel(located)
    assert len(groups) == 1 and len(groups[0]) == 3


def test_no_transitive_merge():
    """A-B differ in segment 1, B-C in segment 2. Three-way merge is refused."""
    located = [at("docs/en/a/x.md"), at("docs/ko/a/x.md"), at("docs/ko/b/x.md")]
    groups = group_parallel(located)
    assert len(groups) == 2
    assert max(len(g) for g in groups) == 2


def test_a_lone_finding_is_a_group_of_one():
    located = [at("docs/en/x.md"),
               at("other/y.md", kind="dead-sha", detail="`abc` does not resolve")]
    assert sorted(len(g) for g in group_parallel(located)) == [1, 1]


def test_order_is_stable():
    located = [at("z/en/x.md"), at("a/en/x.md"), at("z/ko/x.md"), at("a/ko/x.md")]
    assert paths_of(group_parallel(located)) == paths_of(group_parallel(located))
    assert group_parallel(located)[0][0].path.startswith("a/")


def test_a_group_of_one_renders_exactly_as_before():
    """The test that protects every other test in the suite."""
    located = [at("docs/only.md", 7)]
    groups = group_parallel(located)
    assert format_text_grouped(groups) == format_text(located)


def test_a_group_names_every_path_literally():
    """No brace form. `grep docs/ko/intro.md` must find the line."""
    located = [at("docs/en/intro.md", 12), at("docs/ko/intro.md", 14)]
    lines = format_text_grouped(group_parallel(located))
    body = "\n".join(lines)
    assert "docs/en/intro.md:12" in body
    assert "docs/ko/intro.md:14" in body
    assert "{" not in body


def test_the_group_header_carries_no_line_number():
    """Four translations carry one defect at four different lines."""
    located = [at("docs/en/x.md", 12), at("docs/ko/x.md", 99)]
    header = format_text_grouped(group_parallel(located))[0]
    assert "12" not in header and "99" not in header
    assert "dead-md-link" in header


def test_the_header_counts_occurrences_and_documents():
    located = [at("docs/en/x.md", 1), at("docs/en/x.md", 5),
               at("docs/ko/x.md", 3)]
    header = format_text_grouped(group_parallel(located))[0]
    assert "3 occurrences in 2 documents" in header


def test_repeats_within_one_document_share_its_line():
    """Grouping must not make the output LONGER.

    The largest real group in the corpus is 28 citations of one dead anchor in
    a single PX4 page. One output line per occurrence would be a header plus 28
    identical paths - 29 lines where the ungrouped output was 28.
    """
    located = [at("docs/en/x.md", 12), at("docs/en/x.md", 40),
               at("docs/en/x.md", 92)]
    lines = format_text_grouped(group_parallel(located))
    assert len(lines) == 2
    assert "3 occurrences in 1 document" in lines[0]
    assert lines[1] == "    docs/en/x.md:12, 40, 92"


def test_a_multi_document_group_still_lists_each_document_once():
    located = [at("docs/en/x.md", 1), at("docs/en/x.md", 9),
               at("docs/ko/x.md", 3)]
    lines = format_text_grouped(group_parallel(located))
    assert len(lines) == 3
    assert lines[1] == "    docs/en/x.md:1, 9"
    assert lines[2] == "    docs/ko/x.md:3"


def test_the_machine_formats_never_group():
    """SARIF and annotations are location-per-result consumers.

    Collapse four language copies into one annotation and the three that lost
    get none, so a reviewer looking at `docs/ko/intro.md` in the diff sees
    nothing. Merging drops locations from the security tab for the same reason.
    """
    located = [at("docs/en/x.md", 12), at("docs/ko/x.md", 14),
               at("docs/uk/x.md", 9), at("docs/zh/x.md", 7)]
    assert len(format_github(located)) == 4
    results = json.loads(format_sarif(located))["runs"][0]["results"]
    assert len(results) == 4


def test_a_section_reports_fewer_entries_than_findings():
    """A count that shrinks without saying why is a denominator failure."""
    results = {"vetted": [at("docs/en/x.md", 1), at("docs/ko/x.md", 2)],
               "unvetted": [], "repository": []}
    lines, entries = format_sweep_sections(results)
    assert entries == 1
    assert sum(len(v) for v in results.values()) == 2
    body = "\n".join(lines)
    assert "CONFIGURED - these decide the exit code" in body
    assert "docs/en/x.md:1" in body
    assert "docs/ko/x.md:2" in body


def test_the_entry_note_is_silent_when_nothing_grouped():
    """"reported as 12 entries" under "12 finding(s)" trains readers to skip."""
    assert sweep_entry_note(12, 12) == []
    assert sweep_entry_note(13, 12) == []
    note = sweep_entry_note(1393, 4490)
    assert len(note) == 1 and "1393" in note[0]


def test_the_entry_note_is_silent_for_the_machine_formats():
    """Only the text branch groups, so they arrive here with entries still 0.

    Without this, a `--format=github` sweep printed `reported as 0 entr(y/ies)`
    beneath its annotations and a SARIF one printed it to stderr, where a
    stdout-only comparison could not see it.
    """
    assert sweep_entry_note(0, 40) == []
    assert sweep_entry_note(0, 0) == []


def test_grouping_never_loses_or_duplicates_a_finding():
    """Conservation. The property that would make a bug catastrophic and quiet.

    Verified across all 83 corpus repositories before shipping; pinned here on
    a shape that exercises every branch of the key - a translated trio, a
    same-document repeat, a lone finding and one that must not merge.
    """
    located = [at("docs/en/a.md", 1), at("docs/ko/a.md", 2),
               at("docs/uk/a.md", 3), at("README.md", 4), at("README.md", 9),
               at("docs/CLI.md"), at("docs/Other.md"),
               at("x/y.md", kind="dead-sha", detail="`abc` does not resolve")]
    groups = group_parallel(located)
    flat = [item for group in groups for item in group]
    assert len(flat) == len(located)
    assert sorted(map(id, flat)) == sorted(map(id, located))


def test_an_empty_sweep_renders_nothing():
    lines, entries = format_sweep_sections(
        {"vetted": [], "unvetted": [], "repository": []})
    assert lines == [] and entries == 0
