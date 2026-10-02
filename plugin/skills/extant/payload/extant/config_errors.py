"""What a person reading a TOML decode error is told caused it.

Out of extant/config.py on 2026-10-01, when the archive pointer's derivation
took that module past its 927-line ceiling in tests/test_module_quality.py;
moved byte for byte, with the one mutation anchor naming it following by path.
The cut is the one that block already drew: the loader decides THAT a file
cannot be read, and this decides what to SAY about it, from the decoder's
message alone. Imports nothing from the package, so config.py - which every
module reaches - gains a dependency that cannot be half of a cycle.
"""
from __future__ import annotations

from pathlib import Path

__all__ = ["explain"]


_ESCAPE_HINT = """Most likely cause: a regex written in a TOML *basic* string
(double quotes). TOML processes escapes there, and `\\d` / `\\s` / `\\(` are not
valid ones, so the whole file fails to parse.

Put regex values in LITERAL strings (single quotes), which perform no escape
processing at all:

    branch_token = '`((?:feature|fix)/[^`]+)`'      correct
    branch_token = "`((?:feature|fix)/[^`]+)`"      fails if it contains a backslash

Use ''' triple quotes ''' if the pattern itself contains a single quote."""


_DUPLICATE_HINT = """Cause: the same key is set twice, and TOML refuses to let a
later line overwrite an earlier one.

Check for a key that appears both in the generated block near the top and again
lower down, which is what appending to this file rather than editing it in place
produces."""


_GENERIC_HINT = """The file is not valid TOML. The position above is where the
parser gave up, which is usually at or just after the offending line.

See references/config.md for the shape of every key."""


# EVERY hint here must fit the error it is attached to. This dispatch exists
# because the escape hint used to be unconditional: a duplicate key produced
# "Cannot overwrite a value" followed by a confident paragraph about regex
# quoting, which is not merely unhelpful but actively misleading. Someone would
# check their quotes, find them correct, and have no next move.
#
# A wrong cause is worse than no cause: it gets believed, acted on, and repeated.
_HINTS = (
    ("cannot overwrite", _DUPLICATE_HINT),
    ("escape", _ESCAPE_HINT),
    ("invalid literal", _ESCAPE_HINT),
    ("unterminated", _ESCAPE_HINT),
)


def explain(path: Path, exc: Exception) -> str:
    """Attach the hint that actually matches this decoder error."""
    text = str(exc).lower()
    hint = next((h for needle, h in _HINTS if needle in text), _GENERIC_HINT)
    return f"{path}: {exc}\n\n{hint}"
