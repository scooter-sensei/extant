"""Splitting a status document into entries, and retiring the old ones.

Two functions, one of which is the only irreversible file operation in this
system. `archive` rewrites the status document and its archive in place, so it
asserts conservation rather than trusting it: every original line has to turn
up in one output or the other, counted as a MULTISET, or it writes nothing.

Both take the `Config` they read instead of the eight module-level globals they
used to, for the reason extant/collect.py's functions take one: `reload_config`
REBINDS the settings object rather than mutating it, so a value captured at
import describes whichever project the module was first imported in.

TRAP for a test written against the old shape. `archive` calls the
`split_entries` in THIS module, so a test that swaps `extant_collect
.split_entries` to prove the conservation guard is independent of the splitter
no longer intercepts anything - it has to swap `extant.entries.split_entries`.
That is not a hypothetical: tests/test_extant_collect.py does exactly this, and
the guard it proves is the one standing between a bug in `split_entries` and a
silently truncated status document.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from extant.config import Config
from extant.text import lone_cr_to_lf

__all__ = ["archive", "split_entries"]


def split_entries(text: str,
                  config: Config) -> tuple[str, list[tuple[str, str]], str]:
    """Split a status doc into (preamble, [(kind, text)], reference base).

    GA-4: splits on EVERY top-level section, not just `## Phase `. Sections
    classified "other" are reference material interleaved among the phase
    entries, and archiving them as history would lose them.
    """
    if not isinstance(config, Config):
        # The two configuration types are structurally similar enough that
        # passing the wrong one is a repeatable mistake, not a one-off typo:
        # StatusConfig is the raw parsed settings, Config is the 21 values
        # DERIVED from it (see the module docstring above and extant/config.py).
        # Left unchecked, `config.section_header` a few lines down raises a
        # bare AttributeError that names a field sounding like a typo of
        # `archive_header` - which sends whoever is debugging it to the wrong
        # place. Checked here, at the one function `archive` and every rule
        # funnels a config through, the failure names its actual cause.
        raise TypeError(
            f"split_entries needs the derived Config, got "
            f"{type(config).__name__}. Build one with Config.build(status), "
            f"or pass ctx.config / session.context(repo).config."
        )
    # The same normalisation `prose` applies, for the callers that do not go
    # through it: two counters in cli.py and the probe scanner all hand raw
    # document text straight here. Idempotent and length-preserving, so it
    # changes nothing for a caller that already normalised.
    text = lone_cr_to_lf(text)
    base_match = config.base_header.search(text)
    base_start = base_match.start() if base_match else len(text)
    body, base = text[:base_start], text[base_start:]

    starts = [m.start() for m in config.section_header.finditer(body)]
    if not starts:
        return body, [], base
    preamble = body[: starts[0]]
    bounds = starts + [len(body)]
    segments: list[tuple[str, str]] = []
    for index in range(len(starts)):
        chunk = body[bounds[index]: bounds[index + 1]]
        kind = "phase" if chunk.startswith(config.phase_prefix) else "other"
        segments.append((kind, chunk))
    return preamble, segments, base


def archive(repo: Path, retain: int | None, config: Config) -> dict[str, int]:
    """Move all but the newest `retain` phase entries into the archive doc.

    `retain` is None to mean "however many this project keeps", and the
    fallback is read from `config` INSIDE the call rather than written as a
    parameter default. A default expression is evaluated once at import:
    written the other way it froze whatever the module was configured with
    at import time, so `reload_config` could update the setting and this
    function would go on using the stale one. Passing the Config in keeps
    that property for a caller that reloads between two calls.

    Fails closed if any original line would be lost. This is the only
    irreversible file operation in the system, so conservation is asserted
    rather than trusted.
    """
    if retain is None:
        retain = config.retain_entries
    doc = repo / config.primary_doc
    with open(doc, encoding="utf-8", newline="") as fh:
        original = fh.read()
    # The terminator this file arrived in is the one it leaves in, and a bare
    # `\r` is one of the three. Detecting only `\r\n` and defaulting to `\n`
    # rewrote every line ending in a CR-only document as a side effect of
    # retiring two entries - a change to every line of a file, from an
    # operation asked to move two sections, in the one place here that writes
    # irreversibly.
    #
    # Normalising has to cover it too, and for a sharper reason: `^` in a
    # MULTILINE pattern follows a newline, and `\r` is not one. Left as it
    # arrived, a CR-only document is a single line to every entry-header
    # pattern, so nothing splits, nothing moves, and `--archive` reports a
    # document with no entries in it rather than failing - the reassuring zero
    # this project exists to refuse, in its most expensive location.
    if "\r\n" in original:
        newline = "\r\n"
    elif "\r" in original:
        newline = "\r"
    else:
        newline = "\n"
    normalised = original.replace("\r\n", "\n").replace("\r", "\n")

    preamble, segments, base = split_entries(normalised, config)

    # Idempotency: the pointer this function writes below is tool-generated
    # bookkeeping, not content - a PRIOR run's pointer must never survive
    # into this run's output, kept inline or archived. split_entries files
    # it under "other" (GA-6's own top-level header), and GA-4 keeps every
    # "other" segment inline forever, so without this a stale pointer would
    # ride along unchanged while a fresh one gets appended alongside it: N
    # runs, N stacked pointer blocks, none ever removed.
    live_segments = [
        (kind, chunk) for kind, chunk in segments
        if not chunk.startswith(config.pointer_prefix)
    ]
    stale_pointer_text = "".join(
        chunk for _, chunk in segments if chunk.startswith(config.pointer_prefix)
    )

    phase_count = sum(1 for kind, _ in live_segments if kind == "phase")
    if phase_count <= retain:
        return {"retained": phase_count, "archived": 0}

    kept: list[str] = []
    moved: list[str] = []
    seen = 0
    for kind, chunk in live_segments:
        if kind != "phase":
            kept.append(chunk)  # GA-4: reference sections are never archived
            continue
        (kept if seen < retain else moved).append(chunk)
        seen += 1

    # GA-6: the pointer gets its own top-level `## ` header so a later
    # split_entries() classifies it as a standalone "other" segment instead
    # of gluing it onto the tail of whichever phase chunk precedes it - an
    # un-headered pointer would otherwise end up embedded inside that
    # entry's body once the entry itself is archived.
    pointer = (
        "## Archive pointer\n\n"
        f"> Entries older than the newest {retain} live in "
        f"`{config.archive_doc}`.\n\n"
    )
    remaining = preamble + "".join(kept) + pointer + base

    archive_path = repo / config.archive_doc
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    existing = ""
    if archive_path.exists():
        with open(archive_path, encoding="utf-8", newline="") as fh:
            existing = fh.read().replace("\r\n", "\n")
    # GA-6: new phase entries are always PREPENDED to NEXT_SESSION.md, so
    # whatever falls out of the retain window on THIS run is chronologically
    # newer than anything archived on a prior run. `moved` (already
    # newest-first, per split_entries order) must land directly under the
    # header, above everything previously archived - never appended after it.
    existing_body = existing.removeprefix(config.archive_header)
    archived_text = config.archive_header + "".join(moved) + existing_body

    # GA-3: multiset comparison. A set-membership check cannot detect the loss
    # of DUPLICATE lines - blanks, "---" rules - because one surviving copy
    # satisfies it. Counter subtraction keeps only positive residuals.
    #
    # The baseline is `normalised` with the stale pointer's own lines
    # subtracted, NOT rebuilt from `live_segments` (preamble + join + base).
    # Those two are equal whenever split_entries partitions losslessly - but
    # anchoring to `normalised` keeps the guard independent of split_entries
    # itself, so it still catches a bug THERE (see
    # test_archive_detects_loss_of_duplicate_lines, which monkeypatches
    # split_entries to drop a line and asserts this guard still fires). A
    # live_segments-rebuilt baseline would launder that exact class of bug:
    # both the baseline and remaining+archived would be built from the same
    # corrupted segments and agree with each other, silently.
    #
    # Subtracting the stale pointer's lines here - rather than comparing
    # against the raw on-disk text as-is - is what makes idempotent archive
    # runs possible: on run 2+, `normalised` (read fresh from disk) already
    # contains run 1's pointer block, which this run deliberately discards
    # (never placed in `kept` or `moved` above). Without this subtraction
    # the guard would see that discarded block's lines as "lost" and raise
    # a false positive on every run after the first.
    cleaned_baseline = (
        Counter(normalised.splitlines()) - Counter(stale_pointer_text.splitlines())
    )
    lost = (
        cleaned_baseline
        - Counter(remaining.splitlines())
        - Counter(archived_text.splitlines())
    )
    if lost:
        raise RuntimeError(
            f"archive would lose {sum(lost.values())} line(s); "
            f"examples: {list(lost)[:3]}"
        )

    # ADDITIVE WRITE FIRST, destructive second, and the order is the whole
    # of the crash-safety here. The conservation check above proves the two
    # output texts hold every input line, but it proves it about VALUES in
    # memory; it says nothing about a process that dies between the two
    # writes. Written the other way round - the primary truncated first -
    # that window leaves the retired entries in NEITHER file, which is the
    # one outcome this function exists to make impossible, reached by a
    # route the Counter cannot see. This way the same crash leaves them in
    # BOTH, and a duplicated entry is something a reader can fix.
    with open(archive_path, "w", encoding="utf-8", newline="") as fh:
        fh.write(archived_text.replace("\n", newline))
    with open(doc, "w", encoding="utf-8", newline="") as fh:
        fh.write(remaining.replace("\n", newline))
    return {"retained": retain, "archived": len(moved)}
