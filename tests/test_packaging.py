"""Checks on the package itself, rather than on what it validates.

These exist because the failure mode this project cares about is an unfinished
thing that looks finished. A placeholder in a legal notice and a non-ASCII
character in printed output are both invisible until they are expensive.
"""
from __future__ import annotations

import io
import tokenize
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def test_license_names_a_real_copyright_holder() -> None:
    """Fails while LICENSE carries the shipped placeholder.

    A copyright line reading `<GITHUB-USERNAME>` is not a legal notice, and it
    is exactly the sort of thing that survives to a public repository because
    nothing complains. See PUBLISHING.md.
    """
    text = PACKAGE_ROOT.joinpath("LICENSE").read_text(encoding="utf-8")

    assert "MIT License" in text, "LICENSE is not the file it is supposed to be"
    assert "<GITHUB-USERNAME>" not in text, (
        "LICENSE still has its placeholder copyright holder. Replace it with a "
        "real name or handle before publishing (see PUBLISHING.md)."
    )


def test_payload_string_literals_are_ascii() -> None:
    """Non-ASCII in printed output crashes a cp437 console.

    Printing U+2014 there raises UnicodeEncodeError and terminates the process.
    The installer died partway through, after it had already copied files into
    the target repository. A cp1252 console renders it as mojibake instead,
    which is why it went unnoticed during development.

    Scoped to string literals, since comments never reach a console.
    """
    string_types = {tokenize.STRING}
    for name in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END"):
        if hasattr(tokenize, name):
            string_types.add(getattr(tokenize, name))

    offenders: list[str] = []
    files = 0
    literals = 0
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        parts = path.relative_to(PACKAGE_ROOT).parts
        if "__pycache__" in parts or ".venv" in parts:
            continue
        files += 1
        source = path.read_text(encoding="utf-8")
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type not in string_types:
                continue
            literals += 1
            for char in tok.string:
                if ord(char) > 127:
                    offenders.append(
                        f"{path.relative_to(PACKAGE_ROOT)}:{tok.start[0]}: "
                        f"U+{ord(char):04X}"
                    )
                    break

    # Both denominators. Either one reaching zero would turn this into a test
    # that passes by examining nothing.
    assert files > 3, f"only {files} Python files scanned"
    assert literals > 50, f"only {literals} string literals examined"
    assert not offenders, (
        "non-ASCII in a string literal (use '-' for an em dash, '...' for an "
        "ellipsis, '->' for an arrow):\n" + "\n".join(offenders)
    )


def test_shipped_shell_hooks_are_ascii() -> None:
    """The hooks echo to a terminal too, and are not Python, so tokenize cannot
    see them. Whole-file check: they carry no diagrams to preserve."""
    hooks = sorted((PACKAGE_ROOT / "payload" / "hooks").iterdir())
    offenders = [
        f"{h.name}: U+{ord(c):04X}"
        for h in hooks if h.is_file()
        for c in h.read_text(encoding="utf-8") if ord(c) > 127
    ]

    assert len(hooks) >= 3, f"only {len(hooks)} hook files found"
    assert not offenders, "non-ASCII in a shell hook:\n" + "\n".join(offenders)


def test_installer_ships_every_hook_it_wires() -> None:
    """The pre-commit guard was wired by the hook installer while nothing
    shipped the file, so it never ran once and the installer reported success.
    """
    import re

    hooks = PACKAGE_ROOT / "payload" / "hooks"
    text = hooks.joinpath("install").read_text(encoding="utf-8")
    referenced = sorted(set(re.findall(r"tools/hooks/([A-Za-z0-9_-]+)", text)))

    assert referenced, "found no hook references in payload/hooks/install"
    missing = [n for n in referenced if not (hooks / n).is_file()]
    assert not missing, (
        f"payload/hooks/install wires {referenced}; missing from payload/hooks/: "
        f"{missing}"
    )


def test_command_template_placeholders_are_all_rendered() -> None:
    """Every placeholder in the template must be one the installer substitutes.

    A placeholder added to the template but not to the renderer's mapping would
    ship literally into an adopter's slash command, which is how the command
    file came to name another project in the first place.
    """
    import sys

    sys.path.insert(0, str(PACKAGE_ROOT))
    import install as installer  # noqa: E402

    template = PACKAGE_ROOT / "payload" / "commands" / "handoff.md.template"
    found = set(__import__("re").findall(r"\{\{[A-Z_]+\}\}", template.read_text(encoding="utf-8")))

    assert found, "template contains no placeholders; the renderer would be a no-op"

    from detect import DERIVED, Observation  # noqa: E402

    obs = [
        Observation("handoff_doc", "STATUS.md", DERIVED, "test"),
        Observation("archive_doc", "docs/archive.md", DERIVED, "test"),
        Observation("entry_prefix", "## Release ", DERIVED, "test"),
    ]
    rendered, notes = installer.render_command(obs, "example-project")

    assert "{{" not in rendered, f"unsubstituted placeholder survived: {notes}"
    assert "example-project" in rendered
    assert "STATUS.md" in rendered
