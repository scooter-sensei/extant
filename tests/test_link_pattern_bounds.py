"""MD_LINK is bounded, and unbounded it was quadratic TWICE over.

The sibling of tests/test_consistency_timeout.py, and the distinction between
them is the point. That one is about a pattern the USER supplies, where the
hang is documented, deliberate and opt-in to bound. This one is about the
pattern the tool SHIPS, applied to any markdown document `--sweep` happens to
find, where nothing needed configuring and nothing was documented.

Measured through the shipped CLI before the bound, one line of `[a](` repeated:

      n= 2,000    8 KB      1.11s
      n= 4,000   16 KB      3.33s   x3.01
      n= 8,000   32 KB     12.14s   x3.65
      n=16,000   64 KB     47.60s   x3.92
      n=32,000  128 KB    188.83s   x3.97

The ratio converges on x4 per doubling of n, which is quadratic. A 128 KB file
cost over three minutes; extrapolated, ~1.4 MB exhausts a six-hour CI job.

Both halves are bounded because bounding one is not enough: with only
`[^\\]]{0,N}` in place, the same input still cost 23.5s of its measured 23.8s.
The lazy `[^)\\s]+?` is the worse half - with no `)` anywhere it expands to the
end of the subject once per opener.
"""
from __future__ import annotations

import concurrent.futures
import time


def _with_deadline(call, *, seconds: float):
    """Run `call`, failing the test rather than hanging the suite.

    Borrowed deliberately from tests/test_consistency_timeout.py, for the same
    reason it exists there: `re` holds the GIL while matching, so the worker
    cannot be killed. It is left to finish on a daemon executor while the test
    reports the timeout, so a regression surfaces as ONE failed test rather
    than as a suite that never returns.
    """
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = pool.submit(call)
    try:
        return future.result(timeout=seconds)
    except concurrent.futures.TimeoutError:
        raise AssertionError(
            "MD_LINK did not finish within %ss, so its bound is gone" % seconds
        ) from None
    finally:
        pool.shutdown(wait=False)


def test_the_link_pattern_states_a_bound_on_both_halves() -> None:
    """The deterministic half, which needs no clock.

    A wall-clock assertion alone would pin this loosely and flake under load.
    Matching exactly at the bound and NOT one character past it pins the
    number itself: remove either bound and the over-long case starts matching,
    and this fails on every machine at the same input.
    """
    from extant.text import MD_LINK, _MD_LINK_SPAN

    at_bound = "[" + "a" * _MD_LINK_SPAN + "](target.md)"
    past_bound = "[" + "a" * (_MD_LINK_SPAN + 1) + "](target.md)"
    assert MD_LINK.findall(at_bound) == ["target.md"]
    assert MD_LINK.findall(past_bound) == [], "the link text is not bounded"

    target_at = "[t](" + "a" * _MD_LINK_SPAN + ")"
    target_past = "[t](" + "a" * (_MD_LINK_SPAN + 1) + ")"
    assert MD_LINK.findall(target_at) == ["a" * _MD_LINK_SPAN]
    assert MD_LINK.findall(target_past) == [], "the target is not bounded"


def test_ordinary_links_are_untouched_by_the_bound() -> None:
    """The regression guard, and the reason 4096 was the number chosen.

    4096 is the smallest power of two above the longest real instance of
    either half, measured over 694,676 markdown links in 176 repositories:
    link text tops out at 1,278 characters and a target at 3,064. A corpus
    differential over all 52,928 documents found the bounded and unbounded
    patterns extracting identical target lists, so the number of real links
    this stops matching is zero.
    """
    from extant.text import MD_LINK

    assert MD_LINK.findall("see [the guide](docs/guide.md) now") == ["docs/guide.md"]
    assert MD_LINK.findall("[a](x) and [b](y)") == ["x", "y"]
    # Whitespace around the target is stripped, which the bound must not break.
    assert MD_LINK.findall("[a](  spaced.md  )") == ["spaced.md"]
    # The longest real link text in the corpus, and the longest real target,
    # both still match.
    assert MD_LINK.findall("[" + "t" * 1278 + "](x.md)") == ["x.md"]
    assert MD_LINK.findall("[t](" + "u" * 3064 + ")") == ["u" * 3064]


def test_a_document_of_link_openers_does_not_take_minutes() -> None:
    """The behavioural half: the bound has to BITE, not merely be present.

    n=8,000 measured 12.14s unbounded. Bounded it is roughly 8,000 * 4096
    character steps, which is well under a tenth of a second, so five seconds
    is a large margin over the bounded cost and a clear failure against the
    unbounded one. Deliberately not tighter: this must not become the test
    that flakes under load.
    """
    from extant.text import MD_LINK

    hostile = "[a](" * 8000
    start = time.perf_counter()
    _with_deadline(lambda: MD_LINK.findall(hostile), seconds=5.0)
    elapsed = time.perf_counter() - start
    assert elapsed < 5.0, elapsed

    # The other shape, which the link-text bound alone already handled. Kept
    # because the two bounds are separate and a repair to one must not be
    # allowed to stand in for the other.
    brackets = "[" * 8000 + "("
    _with_deadline(lambda: MD_LINK.findall(brackets), seconds=5.0)
