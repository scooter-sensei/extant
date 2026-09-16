"""Start coverage in every Python process that inherits COVERAGE_PROCESS_START.

Put this directory first on PYTHONPATH when measuring; see the coverage
section of tests/harnesses/README.md. `process_startup` is a no-op unless the
variable names a configuration file, so a process started without it measures
nothing and pays nothing. Under tests/, never shipped: nothing in the payload
imports it, and the hook reaches the tool only because a harness spawns it
with the environment it inherited.
"""
from __future__ import annotations

import coverage

coverage.process_startup()
