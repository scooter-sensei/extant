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
