"""The rules, one module each.

Deliberately empty of code. Importing a rule from here would make this package
root a route into `extant.rules.*`, and `test_rules_are_leaves` allows exactly
one importer - `extant/registry.py` - because the three dependencies this split
removed were all a rule reaching into another rule for machinery that happened
to be housed there first.

Each module owns four names and states all four: `check(ctx, text)` finds the
findings, `examined(ctx, text)` reports the denominator over the same
population, `probe(ctx, text)` corrupts a real claim so `--selftest` can prove
the rule fires, and `RULE` declares where the rule applies. The denominator
lives beside the check on purpose: while it lived in one central table the two
could describe different populations, and a denominator that overstates is
worse than none because it is the reassuring number.
"""
from __future__ import annotations
