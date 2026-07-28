"""Documents written in languages other than English.

The project enforces ASCII in its OWN files, because printing U+2014 on a cp437
console raises UnicodeEncodeError and kills the process. That rule protects the
strings this project writes. It says nothing about the strings it READS.

A finding quotes user content: a path, a heading, a line of prose. So a German
CONTRIBUTING file or a Japanese architecture note carries non-ASCII straight
into the output, through exactly the code path the ASCII rule exists to keep
safe. Nothing tested that until this file - every fixture in the suite was
written in English, which is the narrowest possible corpus for a tool whose
whole subject is other people's documentation.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = PACKAGE_ROOT / "plugin" / "skills" / "extant"
INSTALLER = SKILL_ROOT / "install.py"

# Spread across planes on purpose: Latin-1 accents, CJK, Cyrillic, and an emoji,
# which is astral and therefore two UTF-16 code units. A tool counting in bytes
# or UTF-16 units reports the wrong position for it.
#
# Written as ESCAPES so this file is itself pure ASCII. That is not a dodge: the
# project's rule is that its own source must survive a cp437 console, and this
# test is about the strings the tool READS rather than the ones it writes. The
# escape is what lets both hold at once - the file prints anywhere, and the
# runtime strings are as non-English as any real user's document.
JAPANESE = "\u30c9\u30ad\u30e5\u30e1\u30f3\u30c8"         # dokyumento
GERMAN = "\u00dcbersicht"                                 # Ubersicht
CYRILLIC = "\u041f\u0440\u043e\u0435\u043a\u0442"         # proekt
EMOJI = "\U0001f680"                                  # rocket


def _repo(tmp_path: Path, body: str, *, extra: dict[str, str] | None = None) -> Path:
    repo = tmp_path / "uni"
    repo.mkdir()
    for cmd in (["init", "-b", "main"], ["config", "user.email", "t@t"],
                ["config", "user.name", "T"]):
        subprocess.run(["git", *cmd], cwd=repo, capture_output=True, check=True)
    with open(repo / "README.md", "w", encoding="utf-8", newline="") as fh:
        fh.write(body)
    for name, text in (extra or {}).items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
    subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo,
                   capture_output=True, check=True)
    subprocess.run([sys.executable, str(INSTALLER), "--repo", str(repo),
                    "--doc", "README.md"], cwd=repo, capture_output=True, check=True)
    return repo


def verify(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(repo / "tools" / "extant_collect.py"),
         "--repo", str(repo), "--verify", *args],
        cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def test_a_non_english_document_is_validated_not_refused(tmp_path) -> None:
    """The base case, and it was never covered.

    A wrong implementation that opens documents as ASCII, or as the platform's
    default encoding, raises UnicodeDecodeError here. On Windows that default
    is cp1252, so this is the ordinary case for a European team rather than an
    exotic one.
    """
    repo = _repo(tmp_path, f"# {JAPANESE}\n\n{GERMAN}: `deadbeef1234567`\n")

    result = verify(repo)

    assert "Traceback" not in result.stderr, result.stderr
    assert result.returncode == 1
    assert "deadbeef1234567" in result.stdout


def test_line_numbers_survive_multi_byte_text_above_them(tmp_path) -> None:
    """Catches counting in bytes rather than characters.

    Each CJK character is three bytes in UTF-8 and the emoji is four, so a
    byte-based counter drifts further from the truth with every line of
    non-English prose above the finding. The finding is on line 6.
    """
    body = (
        f"# {JAPANESE}\n"                       # 1
        f"\n"                                    # 2
        f"{CYRILLIC} {EMOJI} {GERMAN}\n"        # 3
        f"{JAPANESE}{JAPANESE}{JAPANESE}\n"     # 4
        f"\n"                                    # 5
        f"See [{GERMAN}](docs/fehlt.md).\n"     # 6
    )
    repo = _repo(tmp_path, body)

    result = verify(repo)

    assert "line 6:" in result.stdout, result.stdout


def test_a_finding_quoting_non_ascii_does_not_crash_the_printer(tmp_path) -> None:
    """The failure the project's own ASCII rule exists to prevent, arriving
    through user data rather than through our own strings.

    The detail of this finding contains the path, and the path is Japanese. If
    the output stream cannot encode it the process dies AFTER doing the work,
    which is the worst possible moment. Forced to cp437 here, the encoding that
    motivated the rule in the first place.
    """
    repo = _repo(tmp_path, f"See [x](docs/{JAPANESE}.md).\n")

    result = subprocess.run(
        [sys.executable, str(repo / "tools" / "extant_collect.py"),
         "--repo", str(repo), "--verify"],
        cwd=repo, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        env={**__import__("os").environ, "PYTHONIOENCODING": "cp437:replace"},
    )

    assert "UnicodeEncodeError" not in result.stderr, result.stderr
    assert "Traceback" not in result.stderr, result.stderr
    assert result.returncode == 1, result.stdout + result.stderr


def test_sarif_stays_valid_json_with_non_ascii_findings(tmp_path) -> None:
    """A machine format must not be corrupted by the language of the document.

    SARIF is consumed by GitHub's code scanning, which rejects the whole upload
    if the JSON is malformed - so one accent would silently cost a team every
    result in the file, not just the one it appeared in.

    The non-ASCII has to be in the PATH, not the link text. A finding quotes
    what it looked for, and this rule looked for a file: the first version of
    this test put Japanese in the link label, and nothing non-ASCII reached the
    output at all. It passed the json.loads and proved nothing, which is why
    the second assertion is here.
    """
    repo = _repo(tmp_path, f"# {GERMAN}\n\nSee [link](docs/{JAPANESE}.md).\n")

    result = verify(repo, "--format=sarif")

    document = json.loads(result.stdout)          # raises if corrupted
    results = document["runs"][0]["results"]
    assert results, "no results emitted at all; this proves nothing"
    blob = json.dumps(document, ensure_ascii=False)
    assert JAPANESE in blob, "no non-ASCII reached SARIF, so nothing was exercised"


def test_a_non_ascii_heading_resolves_its_own_anchor(tmp_path) -> None:
    """Anchors are slugged from headings, so the slug function meets every
    script a reader writes in. A wrong implementation that strips non-ASCII
    while slugging reports a working link as dead."""
    repo = _repo(tmp_path, f"## {CYRILLIC}\n\nJump to [it](#{CYRILLIC.lower()}).\n")

    result = verify(repo)

    # Asserted as exit code plus denominator, never by searching stdout for the
    # rule's name: the denominator line names every rule on every run, so a
    # substring check there can only ever be a false alarm.
    assert result.returncode == 0, result.stdout
    assert "dead-md-anchor 1" in result.stdout, (
        f"the anchor was never examined, so this proves nothing:\n{result.stdout}"
    )


def test_a_document_of_only_non_ascii_still_reports_a_denominator(tmp_path) -> None:
    """The denominator is the one line that must always appear.

    A run that examined nothing and a run that found nothing print the same
    otherwise, and that must hold in every language.
    """
    repo = _repo(tmp_path, f"# {JAPANESE}\n\n{CYRILLIC} {EMOJI}\n")

    result = verify(repo)

    assert result.returncode == 0, result.stdout
    assert "checked README.md:" in result.stdout
    # The denominator names every rule; the secret scan was removed in
    # 0.14.0, so its line-count is no longer part of it.
    assert "raw-lfs-blob" in result.stdout
