"""The package ships, and a half-finished upgrade fails loudly.

Both tests exist because the shim keeps `tools/extant_collect.py` working, and
a shim that silently runs an OLD payload is indistinguishable from one that
works.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PAYLOAD = REPO / "plugin" / "skills" / "extant" / "payload"


def test_package_version_matches_pyproject() -> None:
    """A shim that disagrees with its package is a half-finished upgrade."""
    sys.path.insert(0, str(PAYLOAD))
    import extant

    declared = re.search(r'^version = "([^"]+)"',
                         (REPO / "pyproject.toml").read_text(encoding="utf-8"),
                         re.M)
    assert declared, "pyproject has no version; this test would pass vacuously"
    assert extant.__version__ == declared.group(1), (
        f"package says {extant.__version__}, pyproject says {declared.group(1)}")


def test_shim_refuses_a_mismatched_package(tmp_path) -> None:
    """The failure mode this guards: a user has locally modified
    tools/extant_collect.py, install refuses to overwrite it, the new package
    lands beside it, and the OLD shim keeps running while everything looks
    fine. Version skew has to be an error, not a quiet downgrade.
    """
    staging = tmp_path / "tools"
    staging.mkdir()
    (staging / "extant_collect.py").write_bytes(
        (PAYLOAD / "extant_collect.py").read_bytes())
    package = staging / "extant"
    package.mkdir()
    (package / "__init__.py").write_text('__version__ = "0.0.0-wrong"\n',
                                         encoding="utf-8")

    result = subprocess.run([sys.executable, str(staging / "extant_collect.py"),
                             "--verify", "--repo", str(tmp_path)],
                            capture_output=True, text=True)
    assert result.returncode != 0, "a mismatched package ran anyway"
    assert "version" in (result.stderr + result.stdout).lower(), (
        "the failure did not say what was wrong")


def test_installer_copies_the_whole_package(tmp_path) -> None:
    """A directory copy that silently drops files leaves a package that
    imports until it reaches the missing module.
    """
    sys.path.insert(0, str(REPO / "plugin" / "skills" / "extant"))
    import install

    repo = tmp_path / "target"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, capture_output=True,
                   check=True)
    actions = install.copy_payload(repo, dry_run=False, force=False)

    shipped = {p.relative_to(PAYLOAD).as_posix()
               for p in PAYLOAD.rglob("*.py")
               if "__pycache__" not in p.parts and "egg-info" not in str(p)}
    landed = {p.relative_to(repo / "tools").as_posix()
              for p in (repo / "tools").rglob("*.py")}
    assert shipped, "nothing is shipped; this test would pass vacuously"
    assert shipped == landed, (
        f"copied {len(landed)} of {len(shipped)} shipped files; "
        f"missing {sorted(shipped - landed)}")
    assert actions, "copy_payload reported nothing it did"
