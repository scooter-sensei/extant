"""dead-path-pointer: does the file this document points a reader at exist?"""
from __future__ import annotations

import re

from extant.contract import Rule
from extant.finding import Finding
from extant.probes import MISSING_PATH, sub_group
from extant.refs import renamed_to
from extant.scope import Context
from extant.sites import resolve_reference
from extant.text import EXTERNAL, percent_decoded, prose

__all__ = ["RULE", "_PATH_SITES", "_path_pointer_sites",
           "_path_pointer_sites_uncached", "check", "examined", "probe"]

# A backticked path that is the VISIBLE TEXT of a markdown link.
#
#     read [`PULL_REQUEST_TEMPLATE.md`](./.github/PULL_REQUEST_TEMPLATE.md)
#
# The text names the file; the URL says where it is. This rule read the text
# as a pointer, resolved it against the repository root, and reported a link
# that works. Same shape as `_LINKED_SHA` in extant/commits.py, and settled the
# same way: the link BESIDE it is the authority, so if that resolves there is
# nothing to report.
#
# Measured on the held-out corpus: 4 findings have this shape and the URL
# resolves in 3. The fourth is Roo-Code citing an `ADDING-EVALS.md` that is
# absent both ways, and it is still reported.
_LINKED_PATH = re.compile(r"\[\s*`([^`]+)`\s*\]\(\s*([^)\s]+)")


# The scan `check` and `examined` used to run separately, over the same bytes,
# to reach the same candidate set. The same redundancy f3fb482 removed from
# `find_sha_candidates` and `merge_claims`, left here because the sweep grew a
# denominator after those were measured.
#
# Profiled by CALLER on a 29-document sweep of a real repository - by caller
# rather than by self time, which is what caught the previous pass's wrong
# diagnosis: `examined` ran 30 times and cost 0.177 s of `findall`, 5.9 ms for
# one call per document. `prose()` was measured separately and is NOT the cost:
# it is memoised in extant/text.py and is a hit by the time `examined` runs, so
# of that 5.9 ms the scan is 5.09 and everything else is 0.07.
#
# The key carries the PATTERN and the DOC FORMAT as well as the text. The
# format is there because `prose()` strips markdown and reStructuredText
# differently, which is exactly the incompleteness `_STRIPPED` (extant/text.py)
# is recorded as having; keyed on text alone this memo would be a second copy
# of that latent bug rather than a use of the precedent. The pattern is there
# because `reload_config` and the `reconfigure` fixture both build a fresh
# Config, so a changed `path_pointer` arrives as a different object and misses.
#
# Pure given those three, so it needs no invalidation and is NOT registered in
# `registry.forget_memos` - unlike `_POINTER_SITES` next door in
# extant/rules/line_pointer.py, which reads the filesystem and must be dropped.
_PATH_SITES: (
    "tuple[str, re.Pattern[str], str, list[tuple[int, str, list[str]]]] | None"
) = None


def _path_pointer_sites(
        ctx: Context, text: str) -> list[tuple[int, str, list[str]]]:
    """(line number, the line, its pointers) for every line offering one.

    Read by `check` and by `examined`, which is the whole point: the module
    that finds this rule's candidates is the module that counts them, and one
    scan is what stops the two describing different populations.

    Lines with NO pointer are dropped rather than carried, which is safe by
    construction and not merely by measurement: `check`'s per-line work is one
    `_LINKED_PATH` scan whose result is read only inside the loop over that
    line's pointers, so a line with none ran a scan whose answer nothing could
    consult. Measured at 0.48 ms per document over every line, and 33 lines of
    58,067 carried a pointer.
    """
    global _PATH_SITES
    if (_PATH_SITES is not None and _PATH_SITES[0] is text
            and _PATH_SITES[1] is ctx.config.path_pointer
            and _PATH_SITES[2] == ctx.doc.doc_format):
        return _PATH_SITES[3]
    sites = _path_pointer_sites_uncached(ctx, text)
    _PATH_SITES = (text, ctx.config.path_pointer, ctx.doc.doc_format, sites)
    return sites


def _path_pointer_sites_uncached(
        ctx: Context, text: str) -> list[tuple[int, str, list[str]]]:
    """The scan itself. Separate only so the cache above stays readable."""
    # Claims inside code are examples, not promises. See prose.
    sites: list[tuple[int, str, list[str]]] = []
    for number, line in enumerate(prose(ctx.doc, text).splitlines(), start=1):
        raws = ctx.config.path_pointer.findall(line)
        if raws:
            sites.append((number, line, raws))
    return sites


def check(ctx: Context, text: str) -> list[Finding]:
    """Paths offered as pointers must resolve; a pointer to nothing is useless.

    Only OPERATIVE references are checked - a path introduced by "Plan:",
    "Design:", "see", or "read". A path merely MENTIONED ("we deleted X",
    "Phase 8 had X", "Phase 10 will add X") is description or intent, not a
    pointer, and flagging it would be noise. See the note above `path_pointer`
    in extant/config.py for the corpus measurement behind that distinction.

    Checked whole-file and in the archive, like merge claims: a pointer is an
    operative promise at any age, and archiving an entry does not make its
    broken pointer work.
    """
    findings: list[Finding] = []
    # Resolved from the repository root AND from the directory holding the
    # document, because both are how people write these.
    #
    # The rule used to try the root alone. A nested `SKILL.md` saying "see
    # `references/cli.md`" was reported dead while the file sat in the very
    # next directory entry, because `references/cli.md` does not exist at the
    # root. 61 findings on the held-out corpus, every one of them a pointer a
    # reader can follow, and `dead-md-link` two rules down had resolved
    # relative to the document all along - the inconsistency was the bug.
    #
    # Strictly narrowing: a pointer resolving either way is a working
    # pointer, so nothing that was a real defect stops being one.
    base = ctx.doc.link_base or ctx.repo
    for number, line, raws in _path_pointer_sites(ctx, text):
        linked = {text_part.strip(): url
                  for text_part, url in _LINKED_PATH.findall(line)}
        for raw in raws:
            url = linked.get(raw)
            if url is not None and not EXTERNAL.match(url):
                target = percent_decoded(url.split("#")[0])
                if (resolve_reference(ctx, base, target)[0]
                        or resolve_reference(ctx, ctx.repo,
                                             target.lstrip("/"))[0]):
                    continue
            exists, actual_case = resolve_reference(ctx, ctx.repo, raw)
            if not exists and base != ctx.repo:
                beside, beside_case = resolve_reference(ctx, base, raw)
                if beside:
                    continue
                actual_case = actual_case or beside_case
            if not exists:
                if actual_case:
                    detail = (f"points at `{raw}`, but the file on disk is "
                              f"`{actual_case}`; the case differs, which fails "
                              f"on a case-sensitive filesystem")
                else:
                    detail = f"points at `{raw}`, which does not exist"
                    moved = renamed_to(ctx, raw)
                    if moved:
                        detail += f"; git shows it renamed to `{moved}`"
                findings.append(Finding(number, "dead-path-pointer", detail,
                                        subject=raw))
    return findings


def examined(ctx: Context, text: str) -> int:
    """Every path the operative-marker pattern finds, counted over prose.

    The keying is what makes this number honest. Keyed on path SHAPE the rule
    would emit 23 findings on this repository alone, every one false, so the
    denominator has to count what the rule reads - pointers - rather than every
    path-shaped token on the page.

    Counted off the SAME scan `check` reads, rather than by a second pass over
    the whole prose blob. Measured over 39 documents and 58,067 lines from two
    repositories, the two routes count the same 33 pointers, and where they
    could differ the per-line one is the honest number: a pointer the line loop
    cannot reach is one `check` never examined, and counting it would be the
    denominator claiming coverage the rule does not have.
    `test_the_path_pointer_denominator_did_not_move` pins that equality against
    the blob scan this replaced, so a pattern edit that separates them goes red
    rather than quiet.
    """
    return sum(len(raws) for _n, _line, raws in _path_pointer_sites(ctx, text))


def probe(ctx: Context, text: str) -> str | None:
    return sub_group(text, ctx.config.path_pointer, 1, MISSING_PATH)


RULE = Rule(
    kind="dead-path-pointer",
    sequence=6,   # matches the pre-refactor examined: dict literal's order
    check=check,
    scope="whole-file",
    in_archive=True,
    falsifiable="does the referenced path exist on disk?",
    probe=probe,
    examined=examined,
)
