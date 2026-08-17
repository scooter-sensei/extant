"""Commits a document CITES, and which of them git actually has.

Two rules read the same tokens, which is the whole reason this is a module of
its own rather than part of either. `dead-sha` reads the backticked and bare
SHA-shaped tokens; `false-merge-claim` reads the commit each merge claim names.
Both then ask git the same question about overlapping sets, and asking it once
for the document's UNION is what keeps a document at one `cat-file
--batch-check` instead of one per rule - measured on this repository's own
document at 29 tokens in one batch, 2 in another, overlapping in 1.

That union is why neither rule can own this. `document_sha_tokens` needs the
SHA rule's candidate scanners AND the merge rule's claim scanner, so housed in
either one it would make the other rule import a rule -
`test_rules_are_leaves` forbids exactly that, and it forbids it because
`_rename_map` and `resolve_shas` both ended up living inside whichever rule
happened to need them first.

It is NOT refs.py, one file over, for the reason refs.py's own docstring gives:
everything there answers a question about a REPOSITORY, and everything here
answers one about a DOCUMENT. `document_shas` is the single crossing point, and
it crosses by handing refs.py a list of tokens rather than by scanning
anything itself.

`tests/test_spawn_budget.py::test_the_same_question_is_not_asked_twice` pins
the union directly, and its fixture is built so that a per-token memo alone
cannot satisfy it: the commit in `PR #1 merged into main at <sha>` sits inside
backticks as a whole phrase, so it is neither a backticked token nor a bare
one, and only the claim rule ever sees it.
"""
from __future__ import annotations

import re
from typing import Any

from extant.refs import SHA_SHAPE, resolve_shas
from extant.scope import Context

__all__ = [
    "BACKTICKED", "BARE_SHA_TOKEN", "_ASSET_PATH", "_BARE_SHAS", "_LINKED_SHA",
    "_PINNED_REF", "_URL", "_UUID", "_document_sha_tokens",
    "_find_bare_sha_candidates", "_is_digest_length", "document_shas",
    "find_bare_sha_candidates", "find_sha_candidates", "load_sha_map",
    "looks_like_bare_sha", "looks_like_sha", "merge_claims", "spans_overlap",
    "translate_shas",
]

BACKTICKED = re.compile(r"`([^`]+)`")
# I-1: SHA-shaped tokens written WITHOUT backticks. Anchored both sides with
# \b so a hex-looking run embedded inside a longer word (an identifier, a
# version tag) never matches - \w includes both hex letters and non-hex
# letters/digits/underscore, so there is no \b between e.g. "deadbeef" and a
# following "zz", and the whole run correctly fails to match at all rather
# than matching a truncated prefix of it.
# `(?<![#\w])` so a CSS colour is not read as a commit. `#646cffaa` is an
# eight-digit hex with alpha, and vitejs/vite carries it inside a drop-shadow
# in prose that no code fence covers. A `#` prefix means colour far more often
# than it means anything git would recognise, and a real SHA reference is never
# written that way.
BARE_SHA_TOKEN = re.compile(r"(?<![#\w])[0-9a-f]{7,40}\b")


def looks_like_sha(token: str) -> bool:
    """Shape test for a BACKTICKED token.

    A letter is required as well as a digit, matching the bare test. An
    all-digit run is a number: nlohmann/json documents the limits of its
    integer types and `9223372036854775807` is INT64_MAX, not a commit, but
    every character in it is valid hex.

    The cost is stated rather than hidden. A real seven-character SHA is
    all-digits about 4% of the time, and those go unchecked now. That is the
    better side of the trade - a missed check is silent, while flagging every
    large number in a document is the noise that gets a validator ignored.
    """
    return (bool(SHA_SHAPE.match(token))
            and not _is_digest_length(token)
            and any(ch.isdigit() for ch in token)
            and any(ch.isalpha() for ch in token))


def _is_digest_length(token: str) -> bool:
    """Exactly 32 hex characters, which is a digest and not a commit.

    MD5 and a UUID with its dashes removed are both 32. Git abbreviations run
    7 to 12 in practice and a full object name is 40, so nothing legitimate
    sits at exactly 32 - and anything that did would RESOLVE, which produces
    no finding either way. Only unresolvable tokens are reported, and an
    unresolvable 32-character hex run is an API key, a content hash or an id.

    Measured on the held-out corpus: 45 findings, every one a documented
    example value. lobe-chat writes `Example: c55168be3874490ef0565d9779ecd5a6`
    beside an API key setting.
    """
    return len(token) == 32


def looks_like_bare_sha(token: str) -> bool:
    """Shape test for a token found OUTSIDE backticks (I-1).

    Requires a letter as well as a digit - unlike `looks_like_sha` (applied
    only to backticked tokens), which requires just a digit. Backticks are
    themselves a signal the author meant a SHA; bare text has no such signal,
    so the extra letter requirement is needed to exclude a plain number (a
    year, a test count) that `looks_like_sha` alone would wrongly accept.
    The digit requirement excludes a hex-looking English word the same way it
    already does for `looks_like_sha`. Measured against ~2600 lines of the
    real status documents with zero false positives.
    """
    return (not _is_digest_length(token)
            and any(ch.isdigit() for ch in token)
            and any(ch.isalpha() for ch in token))


# Hex inside a URL belongs to somebody else's repository.
#
# `https://github.com/pyca/service-identity/blob/fa91bf55.../AI_POLICY.md` and
# `https://gist.github.com/user/d56764d7...` are a cross-repo permalink and a
# gist id. Neither is a commit THIS repository has any opinion about, and the
# core guarantee is that a rule only asks questions git can settle - which
# means git in this repo, about this repo.
#
# Measured, not supposed: of 301 bare-SHA findings across rust-lang/rfcs,
# requests and httpx, 287 sat inside a URL. Left in, the rule reported a wall
# of findings on every project that links to another project's source, which
# is most of them.
_URL = re.compile(r"(?:https?://|ftp://|git@)\S+", re.I)
# A UUID is not a commit, and it is made of pieces that look like one.
#
# `ContentId: dd7207b0-cf8b-4ed6-8c75-941834179dca` sits in the YAML
# frontmatter of every page in microsoft/vscode-docs. Split on the hyphens, the
# 8- and 12-character groups are valid hex with both a letter and a digit, so
# each was read as a short SHA that does not resolve.
#
# 750 of the 789 bare-SHA findings across 40 repositories were fragments of
# one, every one in that repository. Matched whole and skipped whole, because
# skipping the groups individually would also silence a genuine SHA that
# happened to sit beside a hyphen.
# The left edge is a negative lookbehind for HEX, not a word boundary.
#
# `\b` fails between an underscore and a hex digit, because both are word
# characters, so a UUID embedded in an identifier was not recognised as one:
# `conversation_f43eb21b-84cb-49e7-90fb-56595df594e6` slipped past and its
# trailing 12-character field was read as a short SHA. Four findings in one
# agent's debug log. A real abbreviated SHA is not preceded by another hex
# character, so this costs nothing it used to catch.
_UUID = re.compile(
    r"(?<![0-9a-fA-F])[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}"
    r"-[0-9a-f]{12}\b", re.I)
# A hex run inside a FILENAME is part of the filename.
#
# Documentation platforms mint asset names by prefixing a content hash:
# `<ClickableImage src="/img/83f686b-Pipeline_Illustrations_1_1.png" />`. The
# hash is seven valid hex characters with a word boundary on each side, so it
# read as an abbreviated commit that does not resolve. Measured on the
# held-out corpus: 144 findings, all of them in one documentation site, none
# of them a commit.
#
# Matches the whole path-like run so the span covers any hex inside it, which
# is why this is a skip SPAN rather than a token test.
# The lookbehind and the length bound are both load-bearing, not tidiness.
# Written first as `[\w./~-]*\.(ext)`, this took 322 SECONDS on one
# 120,000-character line: the unbounded run restarts at every position, and a
# long path or a base64 data URI is quadratic. The longest markdown line in
# the earlier corpus was 123,427 characters, so that was a hang waiting for a
# document rather than a theoretical concern. Anchoring to the START of a
# path-like run and bounding its length brings the same line under 20 ms.
_ASSET_PATH = re.compile(
    r"(?<![\w./~-])[\w./~-]{0,200}\.(?:png|jpe?g|gif|svg|webp|avif|ico|bmp|"
    r"pdf|mp4|webm|mov|woff2?|ttf|eot|css|js|mjs|map|zip|tar|gz|whl)\b", re.I)
# A ref pinned to a repository that is not this one.
#
# `uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd` pins a
# workflow to a commit in `actions/checkout`. The `owner/repo@` prefix names
# whose commit it is, and it is not this repository's, so this repository
# cannot answer for it - the same reasoning `_URL` already applies to a
# cross-repo permalink. 14 findings on the held-out corpus, every one an
# action pinned by SHA, which is the practice security guidance asks for.
_PINNED_REF = re.compile(r"(?<![\w./-])[\w.-]+/[\w.-]+@[0-9a-f]{7,40}\b", re.I)


def spans_overlap(span: tuple[int, int], others: list[tuple[int, int]]) -> bool:
    start, end = span
    return any(s < end and start < e for s, e in others)


# A backticked SHA that is the VISIBLE TEXT of a link to somebody's commit.
#
# The changesets tool writes release notes this way, and a monorepo that
# absorbed another project keeps citing the original:
#
#     - [#159](https://github.com/withastro/adapters/pull/159)
#       [`adb8bf2a4caeead9a1a255740c7abe8666a6f852`](https://github.com/withastro/adapters/commit/adb8bf2a...)
#
# The URL states whose commit it is. `_URL` already drops a bare hex run
# inside a link target for exactly this reason - "hex inside a URL belongs to
# somebody else's repository" - but the backticked path never had the
# equivalent, so the same SHA was checked against the wrong repository purely
# because it was also written as link text. 192 findings on the held-out
# corpus, 162 of them in one changelog tree.
#
# Deliberately does NOT compare owners. Neither does the `_URL` rule it
# mirrors, and it cannot: a document does not reliably state which repository
# it is in. A link to this repository's own commit is unaffected in practice,
# because a SHA that resolves produces no finding to suppress.
_LINKED_SHA = re.compile(
    r"\[\s*`([0-9a-fA-F]{6,40})`\s*\]\(\s*[^)\s]*?"
    r"/(?:commit|commits|blob|tree|pull|compare)/[^)\s]*\)", re.I)


def find_sha_candidates(text: str) -> list[tuple[int, str]]:
    """(line number, token) for every backticked SHA-shaped token."""
    out: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        qualified = [m.span(1) for m in _LINKED_SHA.finditer(line)]
        for match in BACKTICKED.finditer(line):
            if spans_overlap(match.span(1), qualified):
                continue
            token = match.group(1)
            if looks_like_sha(token):
                out.append((number, token))
    return out


# Same idiom as `_STRIPPED` in text.py: keyed on object IDENTITY, so a
# different string simply misses and no lifecycle is needed. Unqualified here
# - `find_bare_sha_candidates` takes only `text`, so unlike `_STRIPPED`, which
# also reads `doc.doc_format` without keying on it (a known latent bug
# recorded in extant/text.py), this cache has nothing else it could miss.
# Added when the sweep began reporting a per-rule denominator, which made
# `count_examined` (session.py's wrapper over extant.registry.count_examined)
# a second caller for the same document - this function and `_line_pointer_sites`
# in extant/rules/line_pointer.py were then the two most expensive things in a
# sweep, each computed twice over identical bytes. Measured on pytest's 308
# documents: 617 calls, 1.20s.
_BARE_SHAS: tuple[str, list[tuple[int, str]]] | None = None


def find_bare_sha_candidates(text: str) -> list[tuple[int, str]]:
    """(line number, token) for every SHA-shaped token OUTSIDE backticks.

    I-1: a SHA written without backticks previously escaped both
    `validate_references` and `translate_shas` entirely. Scanned per line,
    consistent with `find_sha_candidates` and the rest of the module - see
    the EX-8 note in docs/superpowers/plans/2026-07-20-status-system.md for
    why a whole-text scan drifts out of phase with backtick pairing.

    "Outside backticks" is computed per line: the spans `BACKTICKED` covers
    on that line are found first, and any bare candidate whose span overlaps
    one of them is skipped, so a token already inside backticks is never
    double-counted here.
    """
    global _BARE_SHAS
    if _BARE_SHAS is not None and _BARE_SHAS[0] is text:
        return _BARE_SHAS[1]
    result = _find_bare_sha_candidates(text)
    _BARE_SHAS = (text, result)
    return result


def _find_bare_sha_candidates(text: str) -> list[tuple[int, str]]:
    """The scan itself. Separate only so the cache above stays readable."""
    out: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        skip_spans = [m.span() for m in BACKTICKED.finditer(line)]
        skip_spans += [m.span() for m in _URL.finditer(line)]
        skip_spans += [m.span() for m in _UUID.finditer(line)]
        skip_spans += [m.span() for m in _ASSET_PATH.finditer(line)]
        skip_spans += [m.span() for m in _PINNED_REF.finditer(line)]
        for match in BARE_SHA_TOKEN.finditer(line):
            if spans_overlap(match.span(), skip_spans):
                continue
            token = match.group(0)
            if looks_like_bare_sha(token):
                out.append((number, token))
    return out


def merge_claims(config: Any, prose: str) -> list[tuple[int, str, str]]:
    """(line, ref, sha) for every merge claim, ref as written.

    Split out of what is now `extant.rules.merge.check` so `_document_sha_tokens`
    can see the commits a claim names without reimplementing how a claim is
    found. One reader of `merge_claim`, so a project that customises the
    pattern cannot end up with the batch and the rule disagreeing about what a
    claim is.

    A two-group pattern means (ref, sha). A one-group pattern is the older
    contract and still means (sha), checked against trunk exactly as before.

    Takes the CONFIG rather than a Context, following `entries.split_entries`:
    it reads two configured values and nothing about the repository, and a
    Context here would advertise a git seam and a checkout it never touches.
    """
    pattern = config.merge_claim
    named = pattern.groups >= 2
    claims: list[tuple[int, str, str]] = []
    for number, line in enumerate(prose.splitlines(), start=1):
        for match in pattern.finditer(line):
            if named:
                # The pattern keeps any backticks so the rule can tell a
                # deliberate ref from a word of prose. See `_claimed_ref` in
                # extant/rules/merge.py.
                claims.append((number, match.group(1), match.group(2)))
            else:
                claims.append((number, config.trunk, match.group(1)))
    return claims


def _document_sha_tokens(config: Any, prose: str) -> list[str]:
    """Every SHA-shaped token in this document that a rule will ask git about.

    The UNION, gathered once so a document costs ONE `cat-file --batch-check`
    rather than one per rule that reads SHAs. Two rules read them:
    `rules/sha`, for its backticked and bare candidates, and `rules/merge`,
    for the commit each claim names.

    GATHERING THE TOKENS IS NOT GATHERING THE CANDIDATES, and that distinction
    is the whole safety argument. Each rule still finds its own candidates and
    decides its own findings from them; what is shared is only the question put
    to git, which is per token and gives the same answer whoever asks. A larger
    batch cannot change any token's answer, so nothing here can move a finding.

    Measured on this repository's own document before it existed: 29 tokens in
    one batch and 2 in another, overlapping in 1. A per-token memo alone would
    therefore have left two subprocesses, because the odd token out is real
    rather than an artefact - `PR #499 merged into main at 6ff1f4ac` backticks
    the whole phrase, so the commit inside it is neither a backticked TOKEN nor
    a bare one, and only the claim rule ever sees it.

    Takes PROSE, because both callers blank code blocks before reading and
    passing raw text here would resolve tokens from fences that no rule reads.
    """
    tokens = [token for _number, token in find_sha_candidates(prose)]
    tokens += [token for _number, token in find_bare_sha_candidates(prose)]
    tokens += [sha for _number, _ref, sha in merge_claims(config, prose)]
    return tokens


def document_shas(ctx: Context, prose: str) -> set[str]:
    """Which of this document's SHA-shaped tokens resolve to commits."""
    return resolve_shas(ctx, _document_sha_tokens(ctx.config, prose))


# The `--sha-map` rewriter, which repairs the references the scanners above
# find. It lived in extant/rules/sha.py until Task 10, on the reasoning that it
# repairs exactly what `dead-sha` reports - true, and still the reason it must
# stay beside the scanners rather than move next to the CLI, but not a reason
# for a RULE to own it. A rule module declares one RULE and answers one
# falsifiable question; `--sha-map` is a command-line feature that rewrites
# documents, which is a different job with a different caller. Housed in the
# rule it made `extant/rules/sha.py` the only rule module the CLI imported
# directly, and the leaf gate exists to stop exactly that shape spreading.
#
# Here it sits with `BACKTICKED`, `BARE_SHA_TOKEN`, `looks_like_sha`,
# `looks_like_bare_sha` and `spans_overlap` - every scanner it has to agree
# with - so the "separating them is how a class of finding ends up unfixable"
# argument in `translate_shas` below is satisfied by proximity rather than by
# housing a CLI feature inside a rule.


def load_sha_map(path: str) -> dict[str, str]:
    """Parse a git-filter-repo commit-map (old SHA, whitespace, new SHA)."""
    mapping: dict[str, str] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            parts = line.split()
            if len(parts) == 2:
                mapping[parts[0]] = parts[1]
    return mapping


def _translated_value(token: str, mapping: dict[str, str]) -> str | None:
    """New value for `token` via prefix match, or None if it must stay put.

    GA-6: an AMBIGUOUS prefix - two old SHAs sharing it - is left untranslated
    rather than resolved by dict order. Picking a winner silently would rewrite
    a reference to point at the wrong commit, and a wrong SHA is worse than a
    dead one: the dead one is visibly broken, the wrong one reads as correct.
    Shared by both the backticked and bare translation paths below, so both
    apply the same ambiguity rule.
    """
    hits = [new for old, new in mapping.items() if old.startswith(token)]
    return hits[0][: len(token)] if len(hits) == 1 else None


def translate_shas(text: str, mapping: dict[str, str]) -> tuple[str, int]:
    """Rewrite dead SHAs - backticked AND bare (I-1c) - to their post-rewrite
    values, matched by prefix.

    Ambiguous prefixes are left alone; see `_translated_value`. Ambiguous or
    otherwise unresolved tokens stay dead and get reported by
    `extant.rules.sha.check`.

    Tokenizes per line, exactly like find_sha_candidates and
    find_bare_sha_candidates. `BACKTICKED`'s `[^`]+` matches newlines, so
    subbing over the whole text at once pairs backticks ACROSS line
    boundaries - an odd number of backticks on an earlier line shifts every
    pairing after it out of phase with the per-line scan find_sha_candidates
    (and the rule's `check`) rely on, making some backticked SHAs invisible
    here even though they are reported as findings elsewhere. Scanning line
    by line keeps the two in agreement by construction.
    `splitlines(keepends=True)` + `"".join(...)` preserves line endings
    byte-for-byte, so a no-op translation is a no-op on disk.

    I-1(c): a bare token is repaired in place, at its original length, and
    stays bare - this rewrites the SHA, it does not add styling the author
    never wrote. This half is not optional: adding `bare-dead-sha` findings
    (I-1b) without also extending translation to reach them would recreate
    EX-8 - a class of reference the validator reports that --sha-map is
    structurally unable to fix. The backtick substitution runs first on each
    line; it preserves length and leaves the backtick characters themselves
    untouched, so the backtick spans re-scanned afterwards for the bare pass
    land at the same offsets either way.

    Not a rule function, and it is here rather than beside the CLI because it
    is the repair for exactly what `dead-sha` reports: the two read the same
    tokens through the same scanners, and separating them is how a class of
    finding ends up unfixable.
    """
    count = 0

    def replace_backticked(match: "re.Match[str]") -> str:
        nonlocal count
        token = match.group(1)
        if not looks_like_sha(token):
            return match.group(0)
        new = _translated_value(token, mapping)
        if new is None:
            return match.group(0)
        count += 1
        return f"`{new}`"

    def replace_bare(line: str) -> str:
        nonlocal count
        backticked_spans = [m.span() for m in BACKTICKED.finditer(line)]
        pieces: list[str] = []
        cursor = 0
        for match in BARE_SHA_TOKEN.finditer(line):
            if spans_overlap(match.span(), backticked_spans):
                continue
            token = match.group(0)
            if not looks_like_bare_sha(token):
                continue
            new = _translated_value(token, mapping)
            if new is None:
                continue
            pieces.append(line[cursor: match.start()])
            pieces.append(new)
            cursor = match.end()
            count += 1
        pieces.append(line[cursor:])
        return "".join(pieces)

    lines = []
    for line in text.splitlines(keepends=True):
        line = BACKTICKED.sub(replace_backticked, line)
        line = replace_bare(line)
        lines.append(line)
    return "".join(lines), count
