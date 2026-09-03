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
