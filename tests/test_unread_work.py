"""Work whose answer nothing reads is not done, it is paid for.

Two places a sequential sweep of ruff (650 documents, 5.9 s) spent time on
answers no caller looked at, found by putting a clock around every scanner
rather than by profiling:

* `dead-md-anchor` slugged every document's own headings before it knew
  whether any link needed them - 0.84 s, 14% of the sweep, for 11 documents
  of 650 with a same-document `#fragment`.
* the sweep asked `count_examined` for all thirteen denominators and then
  discarded the ones for rules that had not read the document: the two
  entry-scoped rules' `split_entries` walk, twice per document, and the
  repository-scoped rule's configuration load, once per document - 0.63 s,
  11%, on a repository with no primary document at all.

Both are laziness rather than a change in what is reported, and the corpus
identity gate is what says so.
"""
from __future__ import annotations

import sys
from pathlib import Path

PAYLOAD = (Path(__file__).resolve().parent.parent / "plugin" / "skills"
           / "extant" / "payload")
sys.path.insert(0, str(PAYLOAD))


def _counting_anchors(monkeypatch) -> list[str]:
    """Replace the rule's binding of `anchors` with one that records its calls."""
    from extant.rules import md_anchor as rule_md_anchor

    slugged: list[str] = []
    real = rule_md_anchor.anchors

    def counted(text: str):
        slugged.append(text)
        return real(text)

    monkeypatch.setattr(rule_md_anchor, "anchors", counted)
    return slugged


def test_own_headings_are_not_slugged_for_a_document_with_no_same_document_fragment(
        git_repo, monkeypatch) -> None:
    """A document with headings and links but no `#fragment` into itself
    offers nothing the slugging could decide, so it is not asked for."""
    from extant import session as hc
    from extant.rules import md_anchor as rule_md_anchor
    repo, commit = git_repo
    commit("docs/guide.md", "# Guide\n", "docs: guide")
    slugged = _counting_anchors(monkeypatch)

    text = "## Setup\n\nRead [the guide](docs/guide.md) first.\n\n## Usage\n"
    assert rule_md_anchor.check(hc.context(repo), text) == []
    assert slugged == [], (
        f"the document's own headings were slugged {len(slugged)} time(s) for "
        "a document holding no same-document fragment link")


def test_a_same_document_fragment_reads_the_headings_once(
        git_repo, monkeypatch) -> None:
    """The headings are still read where a fragment needs them - once, not
    once per fragment - and the verdicts are the ones they always were."""
    from extant import session as hc
    from extant.rules import md_anchor as rule_md_anchor
    repo, _commit = git_repo
    slugged = _counting_anchors(monkeypatch)

    text = ("## Setup\n\nJump to [it](#setup) or [there](#nonexistent) "
            "or [back](#setup).\n")
    findings = rule_md_anchor.check(hc.context(repo), text)
    assert [(f.kind, f.subject) for f in findings] == [
        ("dead-md-anchor", "#nonexistent")]
    assert slugged == [text], (
        f"the headings were slugged {len(slugged)} time(s) for three "
        "fragments; one read answers all of them")


def _fake_rule(kind: str, scope: str, examined):
    from extant.contract import Rule
    return Rule(kind=kind, sequence=99, check=lambda ctx, text: [],
                scope=scope, in_archive=False, falsifiable="a fixture",
                probe=lambda ctx, text: None, examined=examined)


def test_count_examined_skips_the_denominator_of_a_rule_the_caller_excludes(
        git_repo, monkeypatch) -> None:
    """`applies` says which rules read this document; the others are not
    asked. A denominator that RAISES for an excluded rule is neither counted
    nor recorded as an error - its `check` never ran either, so recording it
    would report the failure of a rule that did not look."""
    from extant import registry
    from extant import session as hc
    repo, _commit = git_repo

    def exploding(ctx, text):
        raise RuntimeError("asked for a denominator nobody will read")

    fake = _fake_rule("fake-entry-rule", "newest-entry", exploding)
    monkeypatch.setattr(registry, "RULES", (*registry.RULES, fake))
    monkeypatch.setattr(registry, "RULE_ERRORS", [])
    ctx = hc.context(repo)

    counts = registry.count_examined(
        ctx, "nothing here\n", applies=lambda rule: rule is not fake)
    assert counts["fake-entry-rule"] == 0
    assert "dead-sha" in counts, "the applicable rules are still counted"
    assert registry.RULE_ERRORS == [], (
        "a rule the caller excluded was asked for its denominator anyway")

    # The control: without the predicate the same rule IS asked, and its
    # failure is reported - which is what makes the assertion above mean
    # something rather than pass against a rule that never raises.
    registry.count_examined(ctx, "nothing here\n")
    assert [kind for kind, _ in registry.RULE_ERRORS] == ["fake-entry-rule"]


def test_the_sweep_does_not_count_a_denominator_it_discards(
        git_repo, monkeypatch) -> None:
    """Outside the primary document an entry-scoped rule reads nothing, and
    the sweep prints no count for it - so it must not compute one. Measured
    on ruff, which has no primary document: the two entry-scoped rules'
    `split_entries` walk, twice per document, was 0.4 s of a 5.9 s sweep."""
    from extant import registry, sweep
    from extant import session as hc
    repo, commit = git_repo
    commit("docs/notes.md", "## Phase 1 - notes\n\nWork on `feature/x`.\n",
           "docs: notes")

    asked: list[str] = []

    def recording(ctx, text):
        asked.append(text)
        return 0

    fake = _fake_rule("fake-entry-rule", "newest-entry", recording)
    monkeypatch.setattr(registry, "RULES", (*registry.RULES, fake))
    monkeypatch.setattr(hc, "RULES", registry.RULES)

    with hc.run_scope():
        relative, _findings, unreadable, examined, errors = sweep._validate_one(
            repo, "docs/notes.md", False)
    assert unreadable is None and errors == []
    assert "fake-entry-rule" not in examined, (
        "the sweep reported a denominator for a rule that did not read the "
        "document")
    assert asked == [], (
        "the sweep computed a denominator it then discarded: the entry-scoped "
        f"rule was asked {len(asked)} time(s) outside the primary document")
