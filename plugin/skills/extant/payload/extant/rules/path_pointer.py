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

__all__ = ["RULE", "check", "examined", "probe"]

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
    # Claims inside code are examples, not promises. See prose.
    text = prose(ctx.doc, text)
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
    for number, line in enumerate(text.splitlines(), start=1):
        linked = {text_part.strip(): url
                  for text_part, url in _LINKED_PATH.findall(line)}
        for raw in ctx.config.path_pointer.findall(line):
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
    """
    return len(ctx.config.path_pointer.findall(prose(ctx.doc, text)))


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
