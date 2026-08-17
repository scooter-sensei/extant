"""A documented version floor read against the manifest that declares it.

Every case here was drawn from a 39-repository corpus measured 2026-08-04, not
from what the wording ought to look like. Keyed on shape the rule disagreed at
169 of 192 sites and 97 of those sat in changelogs; keyed as it now is, it
examined 7 sites and found 2 real contradictions with nothing false. The tests
that look fussy - the Django decoy, the disjunction - are the two defects that
were actually found, and they are the ones most likely to be deleted as noise.

Each test names the wrong implementation it would catch.
"""
from __future__ import annotations

import sys
from pathlib import Path

from conftest import _install_into

PAYLOAD = (Path(__file__).resolve().parent.parent / "plugin" / "skills"
           / "extant" / "payload")
sys.path.insert(0, str(PAYLOAD))

PYPROJECT = '[project]\nname = "x"\nrequires-python = ">=3.10"\n'


def _prepare(git_repo, manifest: str = PYPROJECT):
    """A repository carrying a manifest, and a clean rule cache."""
    from extant import session as hc
    repo, commit = git_repo
    commit("pyproject.toml", manifest, "chore: manifest")
    # A fresh scope and a fresh document, rather than the two names this
    # helper happened to know about.
    hc._SCOPE = hc.RunScope()
    hc._DOC = hc.DocScope()
    return repo


def _check(repo, text: str, doc: str = "README.md"):
    """Findings from the rule alone, for a document at `doc`."""
    from extant import session as hc
    from extant.rules import manifest_floor as rule_manifest_floor
    hc._SCOPE.manifest_floors = {}
    hc.set_document(doc_path=doc)
    try:
        return rule_manifest_floor.check(hc.context(repo), text)
    finally:
        hc.set_document(doc_path=None)


def _examined(repo, text: str, doc: str = "README.md") -> int:
    from extant import session as hc
    from extant.rules import manifest_floor as rule_manifest_floor
    hc._SCOPE.manifest_floors = {}
    hc.set_document(doc_path=doc)
    try:
        return len(rule_manifest_floor._floor_claims(hc.context(repo), text))
    finally:
        hc.set_document(doc_path=None)


# --- the contradiction itself ------------------------------------------

def test_agreement_is_silent(git_repo) -> None:
    """Catches a rule that fires on every floor it can parse."""
    repo = _prepare(git_repo)
    assert _check(repo, "This requires Python 3.10+.\n") == []


def test_a_doc_offering_an_older_floor_is_reported(git_repo) -> None:
    """The datasette case, and the harmful direction.

    Its README offered Python 3.8 while `pyproject.toml` said `>=3.10`, so a
    reader on 3.9 followed the README into an install failure. Catches a rule
    that compares nothing, and a rule that only looks at the manifest.
    """
    repo = _prepare(git_repo)
    findings = _check(repo, "Datasette requires Python 3.8 or higher.\n")
    assert [f.kind for f in findings] == ["manifest-floor-mismatch"]
    assert "3.8" in findings[0].detail and ">=3.10" in findings[0].detail


def test_a_doc_demanding_a_newer_floor_is_also_reported(git_repo) -> None:
    """Catches a rule that only compares in one direction."""
    repo = _prepare(git_repo)
    assert len(_check(repo, "This requires Python 3.12+.\n")) == 1


def test_the_finding_names_the_manifest_it_disagreed_with(git_repo) -> None:
    """A finding a reader cannot act on is only half a finding."""
    repo = _prepare(git_repo)
    detail = _check(repo, "Requires Python 3.8+.\n")[0].detail
    assert "pyproject.toml" in detail


def test_the_wording_does_not_promise_an_install_failure_for_go(git_repo) -> None:
    """Ecosystem semantics differ and the text must not overclaim.

    `requires-python` is a hard gate, but the `go` directive makes the
    toolchain fetch a newer version, so caddy's real contradiction is not an
    install failure. Catches a rule that hard-codes pip's behaviour into every
    ecosystem's message.
    """
    repo = _prepare(git_repo, PYPROJECT)
    _, commit = git_repo
    commit("go.mod", "module x\n\ngo 1.25.1\n", "chore: go.mod")
    detail = _check(repo, "Requires Go 1.25.0 or newer.\n")[0].detail
    assert "toolchain" in detail
    assert "refuses" not in detail


# --- which documents are read ------------------------------------------

def test_a_changelog_is_not_read(git_repo) -> None:
    """97 of 169 raw disagreements were this.

    "Aider now requires Python >= 3.9" was true the day it was written; the
    manifest moving on does not make it false. Catches a rule that reads every
    document it can find.
    """
    repo = _prepare(git_repo)
    assert _check(repo, "Now requires Python 3.9 or newer.\n",
                  doc="CHANGELOG.md") == []


def test_a_readme_inside_a_historical_directory_is_not_read(git_repo) -> None:
    """The one shape where the two document filters do not overlap.

    `changelog/README.md` satisfies the entry-point name and sits under a
    historical path. Without a case like it the historical filter is entirely
    shadowed by the entry-point filter and could be deleted with no test
    noticing - the code says the pair is redundant today, and this is what
    keeps that claim honest.
    """
    repo = _prepare(git_repo)
    assert _check(repo, "Requires Python 3.8+.\n",
                  doc="changelog/README.md") == []


def test_an_ordinary_document_is_not_read(git_repo) -> None:
    """ruff's docs discuss Python versions constantly and almost none of it is
    ruff's own floor. Catches a rule keyed on the sentence alone."""
    repo = _prepare(git_repo)
    assert _check(repo, "This requires Python 3.8+.\n",
                  doc="docs/internals/design.md") == []


def test_an_install_guide_is_read(git_repo) -> None:
    """Entry point is not only the README. Catches an over-narrow filter."""
    repo = _prepare(git_repo)
    assert len(_check(repo, "Requires Python 3.8+.\n",
                      doc="docs/installation.md")) == 1


def test_a_document_with_no_path_is_not_guessed_at(git_repo) -> None:
    """An unset document path means the caller did not say which document
    this is.

    Catches a rule that treats "unknown" as "entry point" and therefore fires
    on any text handed to it by a library caller.
    """
    from extant import session as hc
    from extant.rules import manifest_floor as rule_manifest_floor
    repo = _prepare(git_repo)
    hc._SCOPE.manifest_floors = {}
    hc.set_document(doc_path=None)
    assert rule_manifest_floor.check(hc.context(repo), "Requires Python 3.8+.\n") == []


# --- what makes a sentence operative -----------------------------------

def test_a_bare_mention_is_not_a_floor(git_repo) -> None:
    """"Python 3.8" with no `+`, `>=` or "or later" states no minimum.

    The sentence carries a requirement VERB on purpose, so the operative test
    admits it and the floor-versus-mention test is the only thing left holding
    it back. Phrased without a verb, two guards reject it and deleting either
    changes nothing.
    """
    repo = _prepare(git_repo)
    assert _check(repo, "This requires Python 3.8.\n") == []


def test_a_floor_with_no_verb_and_no_label_is_not_read(git_repo) -> None:
    """Catches dropping the operative-use test and keying on shape."""
    repo = _prepare(git_repo)
    assert _check(repo, "Python 3.8+ appears in this sentence.\n") == []


def test_a_bare_requirements_label_makes_the_list_below_it_operative(git_repo) -> None:
    """The caddy shape: no verb in the sentence, no matching heading.

    Catches keying on the verb alone, which misses one of the most common ways
    a requirement is written.
    """
    repo = _prepare(git_repo)
    text = ("## Build from source\n\nRequirements:\n\n- Python 3.8+\n")
    assert len(_check(repo, text)) == 1


def test_a_heading_retires_the_label_above_it(git_repo) -> None:
    """Catches a label that leaks into every later section of the document."""
    repo = _prepare(git_repo)
    text = ("Requirements:\n\n- Python 3.10+\n\n"
            "## Notes\n\n- Python 3.8+ is mentioned here\n")
    assert _check(repo, text) == []


def test_a_third_party_subject_is_not_this_project(git_repo) -> None:
    """"Remove if Python 3.13+ support lands in pydub upstream" is about pydub.

    Catches a rule that reads any floor in an operative sentence as the
    project's own.
    """
    repo = _prepare(git_repo)
    assert _check(repo, "Requires a plugin, if you are on Python 3.8+.\n") == []


# --- reading the numbers -----------------------------------------------

def test_a_language_name_inside_another_word_is_not_a_floor(git_repo) -> None:
    """The largest defect the corpus measurement contained.

    Without word boundaries and with re.I, `Go` matches inside "Django 4.2",
    "Mongo 6.0", "cargo 1.75.0" and the substring `LGO9` of a base64 key;
    `Rust` inside "trust 1.0". 57 of 116 harvested `go` sites, 49%, were this.
    Nothing in the funnel looked wrong, because a plausible number of extra
    sites is indistinguishable from a corpus that has them.

    Every decoy carries a floor SUFFIX and sits behind a requirement verb, and
    the manifests for both ecosystems are present. Without all three the
    boundary is only one of several guards rejecting the input, and deleting
    it changes nothing - which is precisely what the first version of this
    test did, and a mutation run is what exposed it.
    """
    repo = _prepare(git_repo)
    _, commit = git_repo
    commit("go.mod", "module x\n\ngo 1.25.1\n", "chore: go.mod")
    commit("Cargo.toml", '[package]\nname = "x"\nrust-version = "1.70"\n',
           "chore: Cargo.toml")
    text = ("Requires Django 4.2+, Mongo 6.0 or newer, and cargo 1.75.0+.\n"
            "It also requires that you trust 1.0 or newer of these.\n")
    assert _check(repo, text) == []


def test_a_coarser_statement_is_not_a_disagreement(git_repo) -> None:
    """"Python 3" against `>=3.10` is coarser, not contradictory.

    Catches a rule that manufactures a finding out of rounding.
    """
    repo = _prepare(git_repo)
    assert _check(repo, "This requires Python 3 or later.\n") == []


def test_only_the_lower_bound_of_a_capped_manifest_is_read(git_repo) -> None:
    """`>=3.9,<4.0` has floor 3.9.

    Catches folding the upper bound in, which would report every capped
    manifest as disagreeing with every document that matches its floor.
    """
    repo = _prepare(git_repo,
                    '[project]\nname = "x"\nrequires-python = ">=3.9,<4.0"\n')
    assert _check(repo, "Requires Python 3.9+.\n") == []


def test_a_disjunction_is_not_examined_rather_than_guessed(git_repo) -> None:
    """vite declares `^20.19.0 || >=22.12.0`.

    Reading the first branch would report "Node 22+" as wrong when the
    manifest admits it. No corpus repository exercised this, so it is
    unmeasured rather than safe, and the rule must stay silent AND say it
    examined nothing. Catches a rule that guesses the first branch.

    "22.0" rather than "22": a one-component version is rejected by the
    precision guard, so with the coarser spelling the disjunction guard could
    be deleted without any test noticing.
    """
    repo = _prepare(git_repo)
    _, commit = git_repo
    commit("package.json",
           '{"name":"x","engines":{"node":"^20.19.0 || >=22.12.0"}}\n',
           "chore: package.json")
    assert _check(repo, "Requires Node 22.0+.\n") == []


# --- the denominator ---------------------------------------------------

def test_a_document_with_no_floor_reports_nothing_examined(git_repo) -> None:
    """Silence is this rule's normal output, so 0 findings and 0 examined must
    be distinguishable. Catches a denominator counted before the keying."""
    repo = _prepare(git_repo)
    assert _examined(repo, "Nothing about versions here.\n") == 0


def test_an_examined_floor_is_counted_even_when_it_agrees(git_repo) -> None:
    """Catches a denominator that counts findings rather than candidates."""
    repo = _prepare(git_repo)
    assert _examined(repo, "This requires Python 3.10+.\n") == 1


def test_a_site_the_rule_cannot_decide_is_not_counted_as_examined(git_repo) -> None:
    """The express case, and a real discrepancy caught by an acceptance run.

    `expressjs/express` states "Node 18" against `>= 18`: two coarse
    statements with nothing to compare. Counting it made the shipped rule
    report 8 examined where the measurement said 7, and a denominator that
    includes sites the rule cannot decide reports coverage that does not
    exist. The comparability test therefore lives in the denominator, not
    after it, so both numbers describe one population.
    """
    repo = _prepare(git_repo)
    _, commit = git_repo
    commit("package.json", '{"name":"x","engines":{"node":">= 18"}}\n',
           "chore: package.json")
    assert _examined(repo, "This requires Node 18 or later.\n") == 0
    assert _check(repo, "This requires Node 18 or later.\n") == []


def test_count_examined_exposes_the_rule(git_repo) -> None:
    """The registry's denominator must reach the reported one."""
    from extant import session as hc
    repo = _prepare(git_repo)
    hc.set_document(doc_path="README.md")
    try:
        counts = hc.count_examined(repo, "This requires Python 3.10+.\n")
    finally:
        hc.set_document(doc_path=None)
    assert counts["manifest-floor-mismatch"] == 1


# --- wiring ------------------------------------------------------------

def test_validate_passes_the_document_path_through(git_repo) -> None:
    """The rule is useless unless the dispatcher tells it which file this is.

    Catches wiring `doc=` into the signature and forgetting to hand it over
    from the sweep, which would leave the rule permanently silent while every
    unit test above still passed.
    """
    from extant import session as hc
    repo = _prepare(git_repo)
    findings = hc.validate(repo, "Requires Python 3.8+.\n",
                           has_entries=False, doc="README.md")
    assert "manifest-floor-mismatch" in {f.kind for f in findings}


def test_a_real_sweep_reaches_the_rule(git_repo) -> None:
    """End to end, as a subprocess, through `--sweep`.

    The unit tests above pass `doc=` to `validate` themselves, so all of them
    keep passing if `run_sweep` forgets to hand the path over - and the rule
    would then be permanently silent in the only mode most repositories ever
    use. A mutation removing `doc=relative` from the sweep survived every
    other test in this file.
    """
    import subprocess
    repo, commit = git_repo
    commit("pyproject.toml", PYPROJECT, "chore: manifest")
    commit("README.md", "# x\n\nThis requires Python 3.8 or higher.\n",
           "docs: readme")
    result = subprocess.run(
        [sys.executable, str(PAYLOAD / "extant_collect.py"),
         "--repo", str(repo), "--sweep"],
        cwd=repo, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    combined = result.stdout + result.stderr
    assert "manifest-floor-mismatch" in combined, combined


def test_verify_reaches_the_rule_for_an_extra_document(git_repo) -> None:
    """--verify is a separate wiring from --sweep, and it was missed.

    0.17.0 shipped with the rule working in --sweep and silent in --verify:
    that path calls validate and count_examined without saying which document
    it is reading, so a project listing README.md in extra_docs got nothing,
    and the denominator agreed with it by reporting 0 examined beside 0
    findings. Found by running the corpus gate, not by any test here.

    The payload has to sit in tools/ for the target's own .extant.toml to be
    read at all; a first attempt put it at the repository root and the config
    was silently ignored, which made a broken run look like a clean one.
    """
    import subprocess
    repo, commit = git_repo
    commit("pyproject.toml", PYPROJECT, "chore: manifest")
    commit("README.md", "# d\n\nRequirements:\n\n- Python 3.8 or higher\n",
           "docs: readme")
    commit("NEXT_SESSION.md", "# Status\n\nnothing here\n", "docs: status")
    commit(".extant.toml", 'extra_docs = ["README.md"]\n', "chore: config")
    tools = _install_into(repo)
    result = subprocess.run(
        [sys.executable, str(tools / "extant_collect.py"),
         "--verify", "--repo", str(repo)],
        cwd=repo, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    combined = result.stdout + result.stderr
    assert "settings came from defaults" not in combined, (
        f"the target's config was not read, so this proves nothing:\n{combined}")
    assert "manifest-floor-mismatch" in combined
    assert "manifest-floor-mismatch 1" in combined, (
        f"the finding fired but the denominator said 0:\n{combined}")


def test_verify_reaches_the_rule_for_the_primary_document(git_repo) -> None:
    """`primary_doc` is configurable, and a project may point it at a README.

    The extra-document path and the primary-document path are two separate
    call sites in --verify, and a mutation proved the test above watches only
    the first: blanking the primary one survived every other test in this file.
    """
    import subprocess
    repo, commit = git_repo
    commit("pyproject.toml", PYPROJECT, "chore: manifest")
    commit("README.md", "# d\n\nRequirements:\n\n- Python 3.8 or higher\n",
           "docs: readme")
    commit(".extant.toml", 'primary_doc = "README.md"\n', "chore: config")
    tools = _install_into(repo)
    result = subprocess.run(
        [sys.executable, str(tools / "extant_collect.py"),
         "--verify", "--repo", str(repo)],
        cwd=repo, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    combined = result.stdout + result.stderr
    assert "settings came from defaults" not in combined, (
        f"the target's config was not read, so this proves nothing:\n{combined}")
    assert "manifest-floor-mismatch 1" in combined, (
        f"the primary document was not read as itself:\n{combined}")


def test_the_document_path_is_restored_after_validate(git_repo) -> None:
    """A leaked global makes the NEXT document be judged as this one."""
    from extant import session as hc
    repo = _prepare(git_repo)
    hc.set_document(doc_path="sentinel.md")
    try:
        hc.validate(repo, "Requires Python 3.8+.\n", has_entries=False,
                    doc="README.md")
        assert hc._DOC.doc_path == "sentinel.md"
    finally:
        hc.set_document(doc_path=None)


def test_the_probe_makes_a_clean_document_fire(git_repo) -> None:
    """A rule that cannot state how to make itself fire cannot be shown to
    work. Catches a probe that corrupts a mention rather than the claim."""
    from extant import session as hc
    from extant.rules import manifest_floor as rule_manifest_floor
    repo = _prepare(git_repo)
    text = "This requires Python 3.10+.\n"
    hc.set_document(doc_path="README.md")
    try:
        assert _check(repo, text) == []
        hc._SCOPE.manifest_floors = {}
        hc.set_document(doc_path="README.md")
        probed = rule_manifest_floor.probe(hc.context(repo), text)
        assert probed is not None
        hc._SCOPE.manifest_floors = {}
        assert len(rule_manifest_floor.check(hc.context(repo), probed)) == 1
    finally:
        hc.set_document(doc_path=None)


def test_the_probe_declines_when_there_is_nothing_to_corrupt(git_repo) -> None:
    """None is the honest answer for a document stating no floor, and
    `--selftest` reports it as NO PROBE rather than as a pass."""
    from extant import session as hc
    from extant.rules import manifest_floor as rule_manifest_floor
    repo = _prepare(git_repo)
    hc.set_document(doc_path="README.md")
    try:
        assert rule_manifest_floor.probe(hc.context(repo), "Nothing here.\n") is None
    finally:
        hc.set_document(doc_path=None)
