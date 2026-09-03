"""What kind of document did this finding come from?

The strata are a PARTITION, not tags: a path can be generated AND
version-snapshotted - bazel's is both - so `classify` returns exactly one name
and the precedence is what makes the per-stratum counts sum to the total.
Those precedence cases are the ones worth testing; a path that matches only
one pattern would pass under any ordering.
"""
from __future__ import annotations

import pytest

from extant.strata import ORDER, classify


@pytest.mark.parametrize("path, expected", [
    ("node_modules/left-pad/README.md", "vendored"),
    ("third_party/py/mock/docs/index.md", "vendored"),
    ("docs/versions/8.6.0/reference/cli.mdx", "version-snapshot"),
    ("versioned_docs/version-3.1/intro.md", "version-snapshot"),
    ("docs/api/client.md", "generated"),
    ("CHANGELOG.md", "historical-record"),
    ("doc/changelogs/CHANGELOG_V20.md", "historical-record"),
    ("scripts/parser-tests/flow/allowlist.md", "historical-record"),
    ("docs/guide/getting-started.md", "ordinary"),
    ("README.md", "ordinary"),
])
def test_classify_by_path(path, expected):
    assert classify(path) == expected


def test_vendored_beats_version_snapshot():
    """Both patterns match. Vendored wins, because a vendored tree is somebody
    else's repository whatever shape it has inside."""
    assert classify("node_modules/pkg/docs/v2/api.md") == "vendored"


def test_version_snapshot_beats_generated():
    """bazel's `docs/versions/8.6.0/reference/` is both. The snapshot is the
    fact that explains the DUPLICATION, which is the larger effect."""
    assert classify("docs/versions/8.6.0/reference/cli.mdx") == "version-snapshot"


def test_generated_beats_historical_record():
    assert classify("docs/api/CHANGELOG.md") == "generated"


def test_order_lists_every_stratum_once_in_precedence_order():
    assert ORDER == ("vendored", "version-snapshot", "generated",
                     "historical-record", "ordinary")
    assert len(set(ORDER)) == len(ORDER)


from extant.finding import Finding, Located
from extant.report import fingerprint


def test_located_carries_a_stratum_and_defaults_to_ordinary():
    item = Located("README.md", Finding(1, "dead-md-link", "x"), primary=True)
    assert item.stratum == "ordinary"


def test_located_accepts_an_explicit_stratum():
    item = Located("CHANGELOG.md", Finding(1, "dead-md-link", "x"),
                   primary=False, stratum="historical-record")
    assert item.stratum == "historical-record"


def test_fingerprint_ignores_the_stratum():
    """The stratum sits on `Located`, not `Finding`, and the fingerprint keys
    on (path, kind, detail). A baseline that stops matching does not fail
    loudly - it quietly re-raises findings a project agreed to leave alone.

    This asserts the INVARIANT rather than a hard-coded digest, which would
    have to be edited whenever the hash changed for a legitimate reason.
    """
    detail = "links to `gone.md`, which does not exist"
    before = fingerprint("CHANGELOG.md", "dead-md-link", detail)
    Located("CHANGELOG.md", Finding(1, "dead-md-link", detail),
            primary=False, stratum="historical-record")
    after = fingerprint("CHANGELOG.md", "dead-md-link", detail)
    assert before == after


import json

from extant.report import format_sarif


def test_sarif_results_carry_the_stratum(tmp_path):
    """Code scanning should be able to filter without the tool deciding for
    it, which is the same reason `gates` is already published."""
    items = [
        Located("CHANGELOG.md", Finding(1, "dead-md-link", "x"),
                primary=False, stratum="historical-record"),
        Located("docs/guide.md", Finding(2, "dead-md-link", "y"),
                primary=True, stratum="ordinary"),
    ]
    doc = json.loads(format_sarif(items, tmp_path, examined={},
                                  run_kind="sweep"))
    got = [r["properties"]["stratum"] for r in doc["runs"][0]["results"]]
    assert got == ["historical-record", "ordinary"]


from extant.strata import ORDER as STRATA_ORDER


def test_summary_breaks_findings_out_by_stratum(capsys):
    """The visible payoff. 54,790 findings and 4,431 of them ordinary is the
    gap this whole change exists to close, and a summary that prints only the
    first number is the misleading one."""
    from extant.sweep import summarise_strata

    items = [
        Located("CHANGELOG.md", Finding(1, "dead-md-link", "a"),
                primary=False, stratum="historical-record"),
        Located("CHANGELOG.md", Finding(2, "dead-md-link", "b"),
                primary=False, stratum="historical-record"),
        Located("docs/guide.md", Finding(3, "dead-md-link", "c"),
                primary=False, stratum="ordinary"),
    ]
    lines = summarise_strata(items, ["CHANGELOG.md", "docs/guide.md",
                                     "docs/untouched.md"])
    assert lines[0] == "  1 finding(s) in ordinary documents; 2 elsewhere:"
    assert "    historical-record  2 finding(s) in 1 of 1 document(s)" in lines


def test_summary_is_silent_when_everything_is_ordinary():
    """A repository with nothing to separate should not gain a table saying
    so. The breakdown earns its space only when it changes the number."""
    from extant.sweep import summarise_strata

    items = [Located("docs/a.md", Finding(1, "dead-md-link", "a"),
                     primary=False, stratum="ordinary")]
    assert summarise_strata(items, ["docs/a.md"]) == []


def test_summary_orders_strata_by_the_declared_precedence():
    from extant.sweep import summarise_strata

    items = [Located("x.md", Finding(1, "k", "d"), primary=False,
                     stratum=name)
             for name in ("historical-record", "vendored", "generated")]
    lines = summarise_strata(items, ["x.md"])
    names = [ln.split()[0] for ln in lines[1:]]
    assert names == [n for n in STRATA_ORDER if n in names]


def test_every_stratum_count_sums_to_the_total():
    """The property that catches an overlapping pattern.

    If two patterns can both claim a path and the precedence is wrong, the
    per-stratum counts stop summing to the total - and a table that does not
    add up is the one failure a reader would not notice, because each row
    looks reasonable alone.
    """
    paths = [
        "node_modules/pkg/docs/v2/api.md",
        "docs/versions/8.6.0/reference/cli.mdx",
        "docs/api/client.md",
        "CHANGELOG.md",
        "docs/guide.md",
        "third_party/x/CHANGELOG.md",
        "versioned_docs/version-3.1/api/index.md",
    ]
    items = [Located(p, Finding(1, "k", "d"), primary=False,
                     stratum=classify(p)) for p in paths]
    counts = {name: sum(1 for i in items if i.stratum == name)
              for name in ORDER}
    assert sum(counts.values()) == len(items)
    assert set(counts) == set(ORDER)


def test_a_sweep_stamps_the_stratum_it_should(tmp_path):
    """Runs the real entry point, because the bug this guards against is a
    construction site nobody updated - and every unit test would still pass
    with `Located(...)` left unchanged at one of the four.

    The `stratum` field defaults to "ordinary", so a missed site reports a
    FALSE CLEAN: findings from a changelog would be counted in the headline
    the change exists to protect. Only a run through the real entry point
    can tell the difference.
    """
    import pathlib
    import subprocess
    import sys

    repo = tmp_path / "r"
    (repo / "docs").mkdir(parents=True)
    (repo / "CHANGELOG.md").write_text(
        "# Changelog\n\nSee [gone](docs/gone.md).\n", encoding="utf-8")
    (repo / "docs" / "guide.md").write_text(
        "# Guide\n\nSee [also-gone](also-gone.md).\n", encoding="utf-8")
    for args in (["init", "-q", "-b", "main"], ["add", "-A"]):
        subprocess.run(["git", *args], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=T",
                    "commit", "-qm", "x"], cwd=repo, check=True)

    shim = (pathlib.Path(__file__).resolve().parent.parent / "plugin"
            / "skills" / "extant" / "payload" / "extant_collect.py")
    done = subprocess.run([sys.executable, str(shim), "--repo", str(repo),
                           "--sweep"], capture_output=True, text=True)
    combined = done.stdout + done.stderr
    assert "historical-record" in combined, combined
    assert "1 finding(s) in ordinary documents" in combined, combined


@pytest.mark.parametrize("path", [
    "doc/en/changelog.rst",
    "doc/en/announce/release-2.5.2.rst",
    "CHANGELOG.markdown",
    "HISTORY.rst",
    "NEWS.rst",
])
def test_historical_records_are_found_in_every_swept_suffix(path):
    """The tool sweeps md, markdown, mdx AND rst - see the suffix set in
    `refs.py` - so a pattern anchored on `.md|.mdx` silently drops the other
    two into `ordinary`.

    That is the dangerous direction. A missed vendored tree only fails to
    shrink the headline; a missed CHANGELOG puts a historical record INTO the
    number a reader acts on, which is the one stratum this whole change exists
    to keep honest. Measured on the corpus: cpython's `Misc/NEWS.d/*.rst` and
    pytest's `doc/en/changelog.rst` were being counted as ordinary.
    """
    assert classify(path) == "historical-record"


def test_a_changelog_DIRECTORY_does_not_make_its_contents_historical():
    """Deliberate, and the reason is the admission bar rather than an oversight.

    `Misc/NEWS.d/3.10.0a1.rst` in cpython is a per-release news fragment, and a
    reader would call it a historical record. Eleven findings on the measured
    corpus sit under such a directory - ten in cpython, one in uv - and they
    stay `ordinary`.

    Widening the pattern to changelog-ish DIRECTORY names would move them, and
    would be tuned on the very corpus being measured, which `design.md` refuses:
    a rule has to be quiet on repositories it was NOT designed on. A directory
    called `news/` is very often a project's live blog, and labelling that
    `historical-record` would push live documentation into a stratum readers
    filter out - a suppression firing wrongly, which deletes signal silently
    instead of appearing in the output for somebody to argue with.

    The filename anchor is what keeps this honest, so it is pinned here.
    """
    assert classify("Misc/NEWS.d/3.10.0a1.rst") == "ordinary"
    assert classify("docs/news/2026-01-release.md") == "ordinary"
    # ...while the filename form is still caught, in every swept suffix.
    assert classify("Misc/NEWS.rst") == "historical-record"
