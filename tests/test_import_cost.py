"""What a `--verify` from a git hook pays to START, before it validates anything.

Every commit runs this tool, and about half of what a commit pays it is
scaffolding rather than validation - measured on the development machine with
the current hook, 57 per cent on a clean document and 49 on one with findings.
Imports are the largest single term inside the part that is not scaffolding,
and nothing measured them.

`--sweep` runs a process pool when a repository holds enough documents to be
worth one. `--verify` never does, and it never can: it reads the primary
document and the configured extras, in one process, by construction. It was
paying for the pool's machinery anyway, because `sweep.py` imported
`concurrent.futures` at module scope and `cli.py` imports `sweep`.

Whole-interpreter wall time, median of 9 on that machine: a bare interpreter is
36.3 ms, importing `extant.cli` takes it to 159.2, and adding
`concurrent.futures` on top of that costs 20.7 ms more. Standalone the same
import reports 82.3 ms over the bare floor - but that includes `logging` and
`traceback`, which this package loads regardless, so only the marginal figure
is real and only it is claimed.

Asserted in a FRESH INTERPRETER. The suite itself imports `concurrent.futures`
(tests/test_consistency_timeout.py does, and so does pytest's own parallel
runner), so a check of `sys.modules` inside the test process would report the
module present no matter what this package does, and pass or fail for reasons
that have nothing to do with the code under test.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PAYLOAD = (Path(__file__).resolve().parent.parent / "plugin" / "skills"
           / "extant" / "payload")


def loaded_after(statement: str) -> set[str]:
    """Which of the modules we care about a fresh interpreter ends up holding."""
    probe = (
        "import sys\n"
        f"{statement}\n"
        "print('\\n'.join(sorted(m for m in sys.modules "
        "if m.startswith('concurrent'))))\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", probe], cwd=PAYLOAD, capture_output=True,
        text=True, encoding="utf-8", check=True,
    )
    return {line for line in done.stdout.splitlines() if line}


def test_the_verify_path_does_not_import_the_worker_pool() -> None:
    """`cli.py` imports `sweep`, and `sweep` imported a pool it may never start."""
    held = loaded_after("import extant.cli")
    print(f"a fresh interpreter importing extant.cli holds: {sorted(held)}")
    assert "concurrent.futures" not in held, (
        "importing the CLI still loads concurrent.futures, which only the "
        "parallel survey uses and which no --verify can reach")


def test_the_probe_would_notice_the_import_it_is_looking_for() -> None:
    """The denominator. A probe that can never see the module always passes.

    This is not a formality: the assertion above is an ABSENCE, so a typo in
    the statement, a wrong working directory, or a `check=True` that never
    fires would all read as a clean result.
    """
    held = loaded_after("import concurrent.futures")
    assert "concurrent.futures" in held, held
