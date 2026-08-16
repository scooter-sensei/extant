"""manifest-floor-mismatch: does the floor this document states match the
manifest that declares it?
"""
from __future__ import annotations

import re

from extant.contract import Rule
from extant.finding import Finding
from extant.scope import Context
from extant.text import HEADING, current_document, prose

__all__ = ["RULE", "check", "examined", "probe"]


# Every pattern below was derived from a 39-repository corpus measured
# 2026-08-04, never from what the wording "should" be. Keyed on shape alone
# the rule disagreed at 169 of 192 sites; 97 of those disagreements sat in
# changelogs and release notes, which are historical records and were true
# when written. Keyed as below it examined 7 sites and found 2 real
# contradictions with no false positives.

# The document a reader consults to learn what must be INSTALLED. A floor
# stated here is a promise to that reader.
_ENTRY_DOC = re.compile(
    r"(^|/)(readme|install|installation|installing|getting[-_ ]?started"
    r"|requirements|prerequisites|quickstart|quick[-_ ]?start)\.[a-z]+$", re.I)

# Redundant with `_ENTRY_DOC` today, since no entry-point name is also
# historical. Both are cheap, and the pair survives someone widening the
# entry-point list without re-reading this comment.
_HISTORICAL_DOC = re.compile(
    r"(changelog|changes|history|news|release[-_ ]?notes?|releases"
    r"|release[-_ ][0-9]|announce|breaking|migration|upgrad|whatsnew"
    r"|what-s-new|_posts|/blog/|deprecat)", re.I)

# The sentence must assert a requirement OF THIS PROJECT. Without this, a
# linter's documentation of what Python itself does in 3.9 reads as the
# linter's own floor - ruff alone produced 50 such sites.
_FLOOR_VERB = re.compile(
    r"\b(requires?|required|requiring|needs?|must have|depends? on"
    r"|compatible with|supports?|supported)\b", re.I)

# A bare `Requirements:` line introducing a list. caddy states its Go floor
# that way, with no verb in the sentence and no matching heading, and keying
# on the verb alone misses it.
_FLOOR_LABEL = re.compile(
    r"^(requirement|prerequisite|dependenc|require|you.ll need|needed)", re.I)

# Something else is the subject: another package, another tool, or the
# language's own behaviour. Structural phrases ONLY. The corpus harness also
# listed package names, which is a memory of one measurement rather than a
# rule; dropping them was verified to leave the result unchanged.
_FLOOR_THIRD_PARTY = re.compile(
    r"\b(upstream|if you|when using|available in|added in|introduced in"
    r"|valid in|works? (?:on|in))\b", re.I)

# WORD BOUNDARIES ARE LOAD-BEARING. Without them, and with re.I, `Go` matches
# inside "Django 4.2", "Mongo 6.0", "cargo 1.75.0", "logo 2.0" and the
# substring `LGO9` of a base64 access key; `Rust` inside "trust 1.0"; `Node`
# inside "anode 5.0"; `PHP` inside "xphp 8.1". Measured on the corpus: 57 of
# 116 harvested `go` sites, 49%, were exactly that. Only `Ruby` was
# accidentally safe.
_FLOOR_LANGS = {
    "Python": r"\bPython\b",
    "Node": r"\bNode(?:\.?js)?\b",
    "Go": r"\bGo(?:lang)?\b",
    "PHP": r"\bPHP\b",
    "Ruby": r"\bRuby\b",
    "Rust": r"\bRust\b",
}

# A floor, not a mention. A bare "Python 3.9" says nothing about a minimum,
# so an operator or a suffix is required.
_FLOOR_CLAIM = {
    name: re.compile(
        rf"{pattern}\s*(?:version\s*)?"
        rf"(>=|>|\^|~)?\s*"
        rf"([0-9]+(?:\.[0-9]+){{0,2}})"
        rf"\s*(\+|or (?:later|newer|above|higher)|and (?:above|later))?",
        re.I)
    for name, pattern in _FLOOR_LANGS.items()
}
_FLOOR_SUFFIXES = {"+", "or later", "or newer", "or above", "or higher",
                   "and above", "and later"}
_FLOOR_OPERATORS = {">=", ">", "^", "~"}

# Where each ecosystem declares its own floor, and what that declaration
# actually DOES. The enforcement column is not decoration: it decides the
# wording of the finding. A contradiction is a contradiction either way, but
# the text must not say an install will fail where the ecosystem says it will
# not.
_FLOOR_MANIFESTS: tuple[tuple[str, str, str, str], ...] = (
    ("Python", "pyproject.toml",
     r"^\s*requires-python\s*=\s*[\"']([^\"']+)[\"']",
     "pip refuses to install"),
    ("Python", "setup.cfg", r"^\s*python_requires\s*=\s*(.+)$",
     "pip refuses to install"),
    ("Node", "package.json", r"[\"']node[\"']\s*:\s*[\"']([^\"']+)[\"']",
     "npm warns unless engine-strict is set"),
    ("Rust", "Cargo.toml",
     r"^\s*rust-version\s*=\s*[\"']([^\"']+)[\"']",
     "cargo errors at build"),
    ("Go", "go.mod", r"^go\s+([0-9.]+)\s*$",
     "the go toolchain downloads a newer version by default"),
    ("PHP", "composer.json", r"[\"']php[\"']\s*:\s*[\"']([^\"']+)[\"']",
     "composer refuses to install"),
    ("Ruby", "*.gemspec",
     r"required_ruby_version\s*=\s*[\"']([^\"']+)[\"']",
     "the gem refuses to install"),
)

_FLOOR_LOWER = re.compile(r"(?:>=|\^|~>?|>)?\s*([0-9]+(?:\.[0-9]+){0,2})")

# A short line ending in a colon, which introduces the list beneath it.
_LABEL_LINE = re.compile(r"^\*{0,2}([A-Za-z][A-Za-z0-9 /_-]{2,40})\*{0,2}:$")


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split(".") if part.isdigit())


def _declared_floor(spec: str) -> tuple[int, ...] | None:
    """The lowest version a manifest specifier admits.

    Only the FIRST bound is read: `>=3.9,<4.0` has floor 3.9, and folding the
    upper bound in would report every capped manifest as disagreeing with
    every document.

    A DISJUNCTION returns None, which makes the site not-examined rather than
    guessed. vite declares `^20.19.0 || >=22.12.0`; taking the first branch
    would report a document saying "Node 22+" as wrong when the manifest
    admits it. No corpus repository exercised this, so it is unmeasured rather
    than safe, and a rule that stays silent where it cannot decide is the
    whole point of this tool.
    """
    if not spec or "||" in spec:
        return None
    match = _FLOOR_LOWER.search(spec.split(",")[0].strip())
    return _version(match.group(1)) if match else None


def _manifest_floors(ctx: Context) -> dict[str, tuple[str, str, str]]:
    """Each ecosystem's declared floor: language -> (spec, file, enforcement).

    Memoised per repository for the lifetime of a validate() call, like every
    other repository fact here. A sweep asks this once per document otherwise,
    and the answer cannot change between them.
    """
    key = str(ctx.repo)
    if key in ctx.run.manifest_floors:
        return ctx.run.manifest_floors[key]
    found: dict[str, tuple[str, str, str]] = {}
    for language, filename, pattern, enforcement in _FLOOR_MANIFESTS:
        if language in found:
            continue
        candidates = sorted(ctx.repo.glob(filename)) + sorted(
            ctx.repo.glob(f"*/{filename}"))
        for path in candidates:
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError, ValueError):
                continue
            match = re.search(pattern, content, re.M)
            if match:
                relative = str(path.relative_to(ctx.repo)).replace("\\", "/")
                found[language] = (match.group(1).strip(), relative,
                                   enforcement)
                break
    ctx.run.manifest_floors[key] = found
    return found


def _floor_claims(ctx: Context, text: str
                  ) -> list[tuple[int, str, tuple[int, ...], tuple[int, ...]]]:
    """Floor statements this rule would actually inspect in this document.

    The DENOMINATOR, and it is counted after the keying rather than before, so
    a README stating no floor reports 0 examined rather than a quiet pass. The
    rule speaks about roughly 13% of repositories, which makes silence its
    normal output and the denominator the only way to tell a working rule from
    a broken one.

    Returns (line number, language, stated floor, declared floor) per claim,
    with both versions already parsed and known comparable.
    """
    document = current_document(ctx.doc)
    if document is None or not _ENTRY_DOC.search(document):
        return []
    if _HISTORICAL_DOC.search(document):
        return []
    floors = _manifest_floors(ctx)
    if not floors:
        return []
    claims: list[tuple[int, str, tuple[int, ...], tuple[int, ...]]] = []
    label = ""
    for number, raw in enumerate(prose(ctx.doc, text).splitlines(), start=1):
        line = raw.strip()
        if HEADING.match(line):
            # A new section RETIRES the previous label. Without this, every
            # later floor in the document reads as though it were introduced
            # by a "Requirements:" line several sections above it.
            label = ""
            continue
        if _LABEL_LINE.match(line):
            label = line.rstrip(":")
            continue
        operative = bool(_FLOOR_VERB.search(line)) or bool(
            _FLOOR_LABEL.match(label))
        if not operative or _FLOOR_THIRD_PARTY.search(line):
            continue
        seen: set[tuple[str, str]] = set()
        for language, pattern in _FLOOR_CLAIM.items():
            if language not in floors:
                continue
            for match in pattern.finditer(line):
                operator, version, suffix = match.groups()
                stated = (suffix or "").strip().lower()
                if operator not in _FLOOR_OPERATORS and (
                        stated not in _FLOOR_SUFFIXES):
                    continue
                if (language, version) in seen:
                    continue
                spec = floors[language][0]
                declared = _declared_floor(spec)
                stated = _version(version)
                # A site the rule CANNOT DECIDE is not examined. Both sides
                # must state the same precision - "Node 18" against `>= 18`
                # is two coarse statements with nothing to compare - and a
                # disjunction is undecidable by construction. Counting these
                # would report coverage that does not exist, which this file
                # already argues is worse than no denominator at all.
                if declared is None or len(stated) < 2 or len(declared) < 2:
                    continue
                seen.add((language, version))
                claims.append((number, language, stated, declared))
    return claims


def check(ctx: Context, text: str) -> list[Finding]:
    """A documented version floor against the manifest that declares it.

    Both operands live in this repository and both are declarative, so this
    asks whether two files CONTRADICT EACH OTHER - the question
    `validate_consistency` already established as legal - rather than whether
    a number is correct, which is the question no rule here may ask.

    Only entry-point documents are read. The same statement in a changelog is
    a historical record: "Aider now requires Python >= 3.9" was true the day
    it was written, and the manifest moving on does not make it false.
    """
    findings: list[Finding] = []
    floors = _manifest_floors(ctx)
    # Comparability was settled in `_floor_claims`, so every claim reaching
    # here is one the rule can decide. That is deliberate: the denominator and
    # this loop must agree on what "examined" means, or the two numbers
    # describe different populations.
    for number, language, stated, declared in _floor_claims(ctx, text):
        if stated == declared:
            continue
        spec, filename, enforcement = floors[language]
        version = ".".join(str(part) for part in stated)
        findings.append(Finding(
            number, "manifest-floor-mismatch",
            f"states {language} {version}, but `{filename}` declares "
            f"`{spec}`; the two contradict each other, and {enforcement}",
            subject=f"{language} {version}"))
    return findings


def examined(ctx: Context, text: str) -> int:
    """Counted AFTER the keying, not before: a README stating no floor reports
    0 examined. This rule speaks about roughly 13% of repositories, so silence
    is its normal output and the denominator is the only thing separating a
    working rule from a broken one."""
    return len(_floor_claims(ctx, text))


def probe(ctx: Context, text: str) -> str | None:
    """Repoint a real floor statement at a version no manifest can declare.

    Located BY LINE rather than by pattern. `_sub_group` corrupts the first
    match anywhere in the document, and the first "Python 3.9" in a file is
    usually a mention rather than the operative claim the rule reads - so a
    pattern-located probe would corrupt something the rule never looks at and
    then report that the rule did not fire.

    Returns None when this document states no floor the rule would read, which
    is the ordinary case: a status document names no version floor. `--selftest`
    reports that as NO PROBE rather than as a pass. This rule is proven instead
    by its unit tests and by an acceptance run over the measurement corpus.
    """
    claims = _floor_claims(ctx, text)
    if not claims:
        return None
    number, language, _stated, _declared = claims[0]
    lines = text.splitlines(keepends=True)
    index = number - 1
    if index >= len(lines):
        return None
    match = _FLOOR_CLAIM[language].search(lines[index])
    if match is None:
        return None
    start, end = match.span(2)
    # 0.0 disagrees with every real floor and still states two components, so
    # it survives the precision guard rather than being skipped as coarse.
    lines[index] = lines[index][:start] + "0.0" + lines[index][end:]
    return "".join(lines)


RULE = Rule(
    kind="manifest-floor-mismatch",
    check=check,
    scope="whole-file",
    # Whole-file, so never archive-exempt: the exemption tracks scope
    # exactly and `test_only_non_whole_file_rules_are_archive_exempt`
    # pins that. The flag is moot in practice anyway - what limits this
    # rule is `_ENTRY_DOC`, and an archive is never an entry-point
    # document. A floor offered to a reader is a promise at any age.
    in_archive=True,
    falsifiable="does the manifest for this ecosystem declare a different "
                "floor than this document states?",
    probe=probe,
    examined=examined,
)
