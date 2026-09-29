"""`--suggest-fixes`: the patch that repoints a reference at where git says
the file went.

Not a mode. Both gating modes in extant/gate.py call it - `--validate` and
`--verify` for a document on disk, `--check-text` for one on stdin with an
`--as-path` - and it writes nothing: it returns a unified diff for the person
whose document it is to read and apply. Split out of extant/gate.py on
2026-09-28 (Phase 57), when that module stood at 899 lines against the
927-line ceiling in tests/test_module_quality.py, the patch still needed a
fix of its own, and the next tranche is to rework a NOTE there. Not forced:
the fix alone would have fitted. Made because it was the cheaper of the two
cuts available - this function has callers in both gating modes, is not a
mode itself, and depends on none of that module's private helpers, so it
moved whole; `--check-text`, the cut planned before, calls four of them.
"""
from __future__ import annotations

import difflib
from pathlib import Path

from extant import session
from extant.finding import Finding
from extant.links import link_sites
from extant.refs import renamed_to
from extant.sites import reference_path, relative_spelling, resolve_reference
from extant.text import prose

__all__ = ["suggest_renames"]


def suggest_renames(repo: Path, base: Path, text: str, relative: str,
                    findings: list[Finding]) -> str:
    """A unified diff repointing references at where git says the file went.

    Emitted to stdout as a PATCH, never written. That is not caution for its own
    sake: this tool's authority rests entirely on the fact that it checks claims
    and never writes them. A validator that edits prose can be wrong in a new
    way - it can author a falsehood itself - and the first time it did, nothing
    would be left to catch it.

    A patch keeps the boundary and loses nothing. `git apply` is one command,
    the diff is reviewable before it is applied, and the decision stays with the
    person whose document it is.

    Only renames GIT RECORDED are offered. A path that is merely missing gets no
    suggestion, because guessing where it went is exactly the authoring this
    refuses to do.
    """
    replacements: list[tuple[str, str]] = []
    ctx = session.context(repo)

    # THE INVARIANT: a patch is only ever offered for a claim a rule REPORTED.
    # Before this, `suggest_renames` scanned the document itself, with a filter
    # that differed from the rule's five ways - so it offered to rewrite a link
    # split across a newline that `--validate` had just declared clean, while
    # exiting 0. A patch is an edit to somebody's prose; the authority for it
    # has to be a finding, not a second opinion.
    #
    # Taken from the findings BEFORE the baseline is applied, deliberately. A
    # baselined finding is still wrong - it is only not new - and keying this
    # on what survived suppression would have quietly coupled the patch
    # generator to the baseline, so adopting one would stop offering repairs
    # for everything it forgave.
    linked = {f.subject for f in findings
              if f.kind == "dead-md-link" and f.subject}
    pointed = {f.subject for f in findings
               if f.kind == "dead-path-pointer" and f.subject}

    for _number, raw, target, _html in link_sites(ctx.doc, text):
        if target not in linked or resolve_reference(ctx, base, target)[0]:
            continue
        # `target` is what RESOLVES; `raw` is what the document actually says,
        # and the replacement below matches text on the page. They differ for a
        # percent-encoded link, and there the two cannot be reconciled without
        # GUESSING an encoding for the replacement - `docs/new guide.md` has to
        # go back as `docs/new%20guide.md` to stay a working link, and choosing
        # that spelling is authoring rather than checking. Refused, explicitly:
        # the finding is still reported, and no patch is offered for it.
        path_part = raw.split("#", 1)[0].split("?", 1)[0]
        if path_part != target:
            continue
        # Looked up under the path the link RESOLVES to and spelled back
        # RELATIVE TO THE DOCUMENT, the two halves of one fact: the map's keys
        # and answers are repository-relative, a link is relative to its page.
        # Asked as written, `[it](old.md)` in `docs/` found nothing; answered
        # as written, it would have been repointed at `docs/new.md`, which from
        # `docs/` names `docs/docs/new.md`. A root-relative link stays rooted.
        rooted = target.startswith("/")
        named = (target.lstrip("/") if rooted
                 else reference_path(repo, base, target) or target)
        moved = renamed_to(ctx, named)
        if moved:
            spelled = "/" + moved if rooted else relative_spelling(repo, base, moved)
            # The fragment or query survives the move. `[x](a.md#install)` is
            # repointed to `[x](b.md#install)`, which the previous code could
            # not do at all: it replaced on the fragment-stripped target, so
            # `](a.md)` matched nothing in a document that says `](a.md#install)`
            # and the patch came out empty.
            replacements.append((raw, spelled + raw[len(path_part):]))

    for raw in ctx.config.path_pointer.findall(prose(ctx.doc, text)):
        if raw not in pointed or resolve_reference(ctx, repo, raw)[0]:
            continue
        # The rule's own order: from the root as written, then from beside
        # the document, spelled back the way each was asked.
        moved = renamed_to(ctx, raw)
        if moved:
            replacements.append((raw, moved))
            continue
        if base != repo:
            beside_path = reference_path(repo, base, raw)
            moved = renamed_to(ctx, beside_path) if beside_path is not None else None
            if moved:
                replacements.append((raw, relative_spelling(repo, base, moved)))

    if not replacements:
        return ""

    updated = text
    for old, new in dict.fromkeys(replacements):
        # Replaced only where the path is USED as a reference - inside a link
        # target or a backticked pointer - rather than anywhere the characters
        # happen to appear. A bare replace would also rewrite prose discussing
        # the old name, which is often the very sentence explaining the move.
        updated = updated.replace(f"]({old})", f"]({new})")
        updated = updated.replace(f"`{old}`", f"`{new}`")

    if updated == text:
        return ""

    diff = difflib.unified_diff(
        text.splitlines(keepends=True), updated.splitlines(keepends=True),
        fromfile=f"a/{relative}", tofile=f"b/{relative}", n=3,
    )
    return "".join(diff)
