"""Entry point for the extant validator.

    python tools/extant_collect.py --collect --out bundle.json
    python tools/extant_collect.py --archive
    python tools/extant_collect.py --validate NEXT_SESSION.md
    python tools/extant_collect.py --verify

A path, not a library. The shipped git hook, the README and the /extant command
all invoke this file BY PATH, so it stays where it is and keeps its name; the
code it used to hold is `tools/extant/`, module by module, and nothing outside
this repository ever imported it.
"""
from __future__ import annotations

# A shim older or newer than the package beside it is a half-finished upgrade.
# It has to fail here, loudly, because the alternative is running whichever
# version happened to survive and reporting nothing unusual.
#
# FIRST, before any other package import. See the note above: an import error
# from a stale package would otherwise mask this with a worse message.
_SHIM_VERSION = "0.23.0"
try:
    from extant import __version__ as _PACKAGE_VERSION
except ImportError:                                  # pragma: no cover
    from tools.extant import __version__ as _PACKAGE_VERSION
if _PACKAGE_VERSION != _SHIM_VERSION:
    raise SystemExit(
        f"extant: version mismatch - tools/extant_collect.py is {_SHIM_VERSION} "
        f"and tools/extant/ is {_PACKAGE_VERSION}. Re-run the installer with "
        f"--force to replace both.")

# This file is used two ways: run directly as a script (the hooks and the
# /extant command, where only tools/ is on sys.path) and imported as
# `tools.extant_collect` (where the repo root is). The second form is the one
# that needs a fallback, so it comes second.
#
# The BARE name is tried first, and the order is load-bearing rather than
# stylistic. `extant/cli.py` imports `extant.session` directly, with no
# fallback; if this line preferred `tools.extant.cli` the same files would be
# imported twice under two module names, and this process would then hold two
# configurations and two run scopes that no `reload_config` could keep in step.
#
# ModuleNotFoundError only, not the broader ImportError. `extant/cli.py` can
# EXIST and still fail this import - a syntax error, a bad import inside it -
# and ImportError catches that case too, silently falling back to
# tools.extant.cli instead of raising.
#
# ValueError is the malformed-.extant.toml case. Configuration is read at
# import by extant/session.py, so a bad file surfaces here rather than in
# main(). It is caught only when this file is being RUN, which is a thing only
# this file can know: burying the explanation under a stack that names tomllib
# internals just makes the reader work for it, and an IMPORTER has to see the
# exception itself rather than a dead interpreter.
try:
    from extant.cli import cli, main                 # noqa: F401  (entry point)
except ModuleNotFoundError:  # pragma: no cover - exercised by the CLI tests
    from tools.extant.cli import cli, main           # noqa: F401
except ValueError as _config_error:
    if __name__ == "__main__":
        import sys
        print("extant: cannot read configuration", file=sys.stderr)
        print("", file=sys.stderr)
        print(_config_error, file=sys.stderr)
        raise SystemExit(2) from None
    raise

if __name__ == "__main__":
    raise SystemExit(main())
