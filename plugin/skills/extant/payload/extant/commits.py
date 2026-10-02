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
from collections.abc import Callable
from extant.config import Config
from extant.rewrites import bucket_index, translated_value
from extant.refs import SHA_SHAPE, normalise_remote, own_remote, resolve_shas
from extant.scope import Context
from extant.text import could_match, line_breaks, line_number_at

__all__ = [
    "BACKTICKED", "BARE_SHA_TOKEN", "_ASSET_PATH", "_BARE_SHAS",
    "_LINKED_BARE_SHA", "_LINKED_SHA",
    "_MERGE_CLAIMS", "_PINNED_REF", "_SHA_CANDIDATES", "_SHA_RANGE", "_URL",
    "_UUID", "_range_ends",
    "_document_sha_tokens", "_find_bare_sha_candidates",
    "_find_sha_candidates", "_is_digest_length", "_merge_claims",
    "document_shas",
    "find_bare_sha_candidates", "find_sha_candidates",
    "looks_like_bare_sha", "looks_like_sha", "merge_claims",
    "spans_overlap",
    "translate_shas",
]

BACKTICKED = re.compile(r"`([^`]+)`")
# Two commits joined by git's range operator inside ONE backtick pair:
# `` `7d6ec08..7499537` `` or `` `a...b` ``. The whole token has to be the
# range - a command holding one, `` `git log a..b` ``, is a command - and each
# end is then tested as a token of its own, so a range of numbers or of tags
# is refused the way a bare one would be.
#
# The authoring note in references/design.md used to ask writers to spell a
# range as two tokens because this shape escaped both checking and repair.
# Measured on 2026-09-12 over 132 repositories: three ranges in 77,401
# documents, one of them in an agent's session log recording a fast-forward
# whose both ends a later force-push rewrote away, which is the population
# this rule exists for. The arrow spelling `a -> b` occurs zero times and is
# left alone: it is also how a rewrite map is quoted, with the left side dead
# by design.
_SHA_RANGE = re.compile(r"^([0-9a-f]{7,40})(\.\.\.?)([0-9a-f]{7,40})$")
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


# A WORD spelled entirely in hex digits, which the two shape tests below would
# otherwise admit: seven characters, a letter and a digit among them.
#
# `ed25519` names a signature scheme and is written bare in prose about keys
# - "each node has one ed25519 keypair". Measured 2026-09-22 against the
# recorded sweep of the 152 visible corpus clones: reported as a bare dead SHA
# in 7 of them (goose, deno, kubernetes, node, unraid, PX4-Autopilot, pdns),
# and it is the ONLY such word the corpus holds - every other repeated dead
# token was hex that named something. A list rather than a rule, because the
# shape cannot be told from a commit's and a second word will be measured in,
# not inferred. What the skip costs: a commit whose abbreviation is exactly
# this word, one in 268 million objects.
_HEX_WORDS = frozenset({"ed25519"})


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

    A word from `_HEX_WORDS` is refused in either spelling: `` `ed25519` `` is
    how a key type is written in prose, not a citation.
    """
    return (bool(SHA_SHAPE.match(token))
            and not _is_digest_length(token)
            and token.lower() not in _HEX_WORDS
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
    real status documents with zero false positives - and against 152 corpus
    clones on 2026-09-22, where one word carrying BOTH a letter and a digit
    slipped it, so `_HEX_WORDS` names that word beside the shape.
    """
    return (not _is_digest_length(token)
            and token.lower() not in _HEX_WORDS
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
# THE URL'S OWNER IS COMPARED WITH `origin`, since 2026-09-22. Until then the
# skip was unconditional, on the reasoning that a document does not reliably
# state which repository it is in - true, and beside the point: the
# repository states it, through its origin, which is how `dead-pinned-ref`
# has told a pin aimed at us from one aimed elsewhere all along. A link
# naming THIS repository's commit is this repository's claim, and it is the
# changelog entry whose commit a squash or a force-push takes away - the one
# rotting citation this tool exists to report. Measured over the 152 visible
# corpus clones for the bare spelling below: 15,257 such links resolve today
# and 31 do not, and the unconditional skip stopped examining every one.
# Foreign is skipped; unsettled (no origin) is skipped, the caution the
# unconditional version took; own is examined. `<head>` is what is compared,
# reduced by `normalise_remote` so `www.github.com`, `api.github.com/repos`
# and an SSH origin all read as one `owner/name`; GitLab's `/-/commit/`
# spelling is allowed for.
#
# A RANGE as link text is the same shape with a compare URL behind it:
# `` [`6728344..4080341`](.../compare/6728344..4080341) `` in helix's
# changelog, where the first commit is one a rebase left unreachable while
# the compare page still serves it. The span covers both ends.
_LINKED_TAIL = (r"\s*\]\(\s*(?P<head>[^)\s]*?)(?:/-)?"
                r"/(?:commit|commits|blob|tree|pull|compare)/[^)\s]*\)")
_LINKED_SHA = re.compile(
    r"\[\s*`([0-9a-fA-F]{6,40}(?:\.\.\.?[0-9a-fA-F]{6,40})?)`" + _LINKED_TAIL, re.I)
# The same shape WITHOUT backticks, which is how release-please,
# standard-version and every changelog they generate write an entry:
#
#     * update gyp-next ([#3316](.../issues/3316)) ([8ea71e5](https://github.com/nodejs/node-gyp/commit/8ea71e5a...))
#
# `_URL` skips the hex inside the parentheses; nothing skipped the copy
# before `](`, so it was read as this repository's claim whoever the URL
# named. Re-derived on 2026-09-22 from the recorded sweep of the 152
# visible corpus clones (m15_linktext.py in the measurement apparatus):
# 2,835 bare dead-SHA findings link to a repository other than the clone's
# origin - moby's vendored google-cloud-go changelogs, node's node-gyp and
# corepack, angular's absorbed zone.js, kubernetes' dependency pins at
# `/tree/<sha>` - and 31 link to its own, which stay reported.
#
# Read by the bare scanner only: a line without a hex run never reaches it,
# and a line with one pays for six scans instead of five.
_LINKED_BARE_SHA = re.compile(
    r"\[\s*([0-9a-fA-F]{6,40}(?:\.\.\.?[0-9a-fA-F]{6,40})?)" + _LINKED_TAIL, re.I)
# What a scan records when no line held a linked commit: `origin` was never
# asked for, the same economy `_pinned_refs` keeps on a document without a
# `rev:` line, and the result holds for every origin.
_UNASKED = object()


def _linked_spans(pattern: "re.Pattern[str]", line: str,
                  own: Callable[[], str | None], asked: list[object],
                  whole: bool) -> list[tuple[int, int]]:
    """Spans of linked SHAs on this line that are NOT this repository's.
    `asked` records what `own()` answered, filled on the first shape met, so
    the memo above each scanner can key on the value the scan used."""
    spans: list[tuple[int, int]] = []
    for match in pattern.finditer(line):
        if match.group("head").startswith(".") or not match.group("head"):
            # `../../commit/<sha>` is this repository's, and its URL half is
            # read as a bare token already; the text alone is set aside.
            spans.append(match.span(1))
            continue
        if not asked:
            asked.append(own())
        ours = asked[0]
        if ours is not None and normalise_remote(match.group("head")) == ours:
            continue
        spans.append(match.span() if whole else match.span(1))
    return spans


# The same memo `_BARE_SHAS` below carries, for the same reason and with the
# same key, and it was missing here purely because the bare scanner was the
# expensive one when the sweep grew a denominator. Three callers ask this
# question about one document: `extant.rules.sha.check`, its `examined`, and
# `_document_sha_tokens` below, which builds the batched SHA resolution. Each
# is right alone - the rule contract keeps `check` and `examined` apart so the
# findings and the denominator describe one population, and `document_shas`
# collapses two `cat-file` batches into one - but together they scanned every
# document three times over identical bytes. Measured on a 29-document sweep of
# a real repository: 89 calls, 0.18s of self time, of which two thirds bought
# nothing.
# The key carries the ORIGIN the scan compared linked commits with (since
# 2026-09-22), or `_UNASKED` when none was needed and any origin hits:
# everything the scan reads is in the key, as `_MERGE_CLAIMS` keeps it.
_SHA_CANDIDATES: tuple[str, object, list[tuple[int, str]]] | None = None


def find_sha_candidates(text: str,
                        own: Callable[[], str | None]) -> list[tuple[int, str]]:
    """(line number, token) for every backticked SHA-shaped token. `own`
    answers `owner/name` for this repository, called only when a line holds
    a linked commit - see `_linked_spans`."""
    global _SHA_CANDIDATES
    if _SHA_CANDIDATES is not None and _SHA_CANDIDATES[0] is text:
        _text, compared, hit = _SHA_CANDIDATES
        if compared is _UNASKED or compared == own():
            return hit
    result, compared = _find_sha_candidates(text, own)
    _SHA_CANDIDATES = (text, compared, result)
    return result


def _find_sha_candidates(
        text: str, own: Callable[[], str | None]) -> tuple[list[tuple[int, str]], object]:
    """The scan itself, and the origin it compared with (or `_UNASKED`).
    Separate only so the cache above stays readable."""
    out: list[tuple[int, str]] = []
    asked: list[object] = []
    for number, line in enumerate(text.splitlines(), start=1):
        # Both patterns below carry a literal backtick - `BACKTICKED` opens
        # with one and `_LINKED_SHA` needs `` [` `` - so a line without one
        # cannot match either, and neither is run on it. Checkable by reading
        # the two patterns, which is the argument the line-pointer rule makes
        # for its colon gate; the bare scanner next door already gates the
        # same way on its own token shape. Ungated, the two ran on every line
        # of every document: 0.32 s of a 5.9 s sequential sweep of ruff.
        if "`" not in line:
            continue
        qualified = _linked_spans(_LINKED_SHA, line, own, asked, whole=False)
        for match in BACKTICKED.finditer(line):
            if spans_overlap(match.span(1), qualified):
                continue
            for token in _range_ends(match.group(1)):
                if looks_like_sha(token):
                    out.append((number, token))
    return out, (asked[0] if asked else _UNASKED)


def _range_ends(token: str) -> tuple[str, ...]:
    """The commits a backticked token names: itself, or both ends of a range.

    ONE splitter for the scanner above and for `translate_shas` below, so
    what is reported and what is repaired stay the same tokens - the same
    argument that keeps the rewriter beside the scanners at all.
    """
    found = _SHA_RANGE.match(token)
    return (found.group(1), found.group(3)) if found else (token,)


# Same idiom as `_STRIPPED` in text.py: keyed on object IDENTITY, so a
# different string simply misses and no lifecycle is needed. Unqualified here
# - `find_bare_sha_candidates` takes only `text`, so this cache has nothing
# else it could miss; `_STRIPPED` reads `doc.doc_format` too and carries it
# in its key since 2026-09-16.
# Added when the sweep began reporting a per-rule denominator, which made
# `count_examined` (session.py's wrapper over extant.registry.count_examined)
# a second caller for the same document - this function and `_line_pointer_sites`
# in extant/rules/line_pointer.py were then the two most expensive things in a
# sweep, each computed twice over identical bytes. Measured on pytest's 308
# documents: 617 calls, 1.20s.
_BARE_SHAS: tuple[str, object, list[tuple[int, str]]] | None = None


def find_bare_sha_candidates(text: str,
                             own: Callable[[], str | None]) -> list[tuple[int, str]]:
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
        _text, compared, hit = _BARE_SHAS
        if compared is _UNASKED or compared == own():
            return hit
    result, compared = _find_bare_sha_candidates(text, own)
    _BARE_SHAS = (text, compared, result)
    return result


def _find_bare_sha_candidates(
        text: str, own: Callable[[], str | None]) -> tuple[list[tuple[int, str]], object]:
    """The scan itself, and the origin it compared with (or `_UNASKED`).
    Separate only so the cache above stays readable."""
    out: list[tuple[int, str]] = []
    asked: list[object] = []
    for number, line in enumerate(text.splitlines(), start=1):
        # Does this line contain a hex-shaped run at ALL? Almost none do, and
        # the five exclusion scans below are the expensive half of this
        # function. Measured over 39 documents and 58,067 lines from two
        # repositories: 80 lines - one in a thousand - carry a run this
        # pattern matches, and 9 tokens survive in total. Every other line was
        # paying for a URL scan, a UUID scan, an asset-path scan and a
        # pinned-ref scan to produce nothing. 20.6 ms per document before this
        # line, 2.2 ms after.
        #
        # NOT the fix the cost first looked like it wanted. 22,544
        # `spans_overlap` calls across a 29-document sweep read as exclusion
        # spans being re-derived per candidate; profiled by CALLER, 7,333 of
        # the remaining 7,366 come from `_find_sha_candidates` above, which
        # tests every backticked span against the linked-SHA spans, and 33
        # from here. The exclusions were already computed once per line.
        #
        # Safe by construction rather than by measurement, which is what a
        # function tuned against a 40-repository corpus needs: `skip_spans` is
        # read only by `spans_overlap` INSIDE the loop below, and that loop
        # body runs only for a match `search` would have found. A line skipped
        # here is a line whose loop body never executed, so no token this
        # returns can move.
        if BARE_SHA_TOKEN.search(line) is None:
            continue
        skip_spans = [m.span() for m in BACKTICKED.finditer(line)]
        skip_spans += [m.span() for m in _URL.finditer(line)]
        skip_spans += [m.span() for m in _UUID.finditer(line)]
        skip_spans += [m.span() for m in _ASSET_PATH.finditer(line)]
        skip_spans += [m.span() for m in _PINNED_REF.finditer(line)]
        skip_spans += _linked_spans(_LINKED_BARE_SHA, line, own, asked, whole=True)
        for match in BARE_SHA_TOKEN.finditer(line):
            if spans_overlap(match.span(), skip_spans):
                continue
            token = match.group(0)
            if looks_like_bare_sha(token):
                out.append((number, token))
    return out, (asked[0] if asked else _UNASKED)


# The third scan of the same document, memoised like the two above and read by
# the same three callers: `extant.rules.merge.check`, its `examined`, and
# `_document_sha_tokens`. Measured beside them on the same 29-document sweep:
# 89 calls, 0.21s of self time.
#
# The key carries the PATTERN and the TRUNK as well as the text: everything
# the scan reads is in it, the way `_STRIPPED` in extant/text.py now carries
# the document format beside the text - a key without one of its inputs was
# that memo's recorded latent bug until 2026-09-16. This function reads
# exactly two configured values and both are in the key, so there is no second
# input a hit could be wrong about. `reload_config` and the `reconfigure`
# fixture both build a fresh Config, so a changed `merge_claim` arrives as a
# different pattern object and simply misses.
_MERGE_CLAIMS: "tuple[str, re.Pattern[str], str, list[tuple[int, str, str]]] | None" = None


def merge_claims(config: Config, prose: str) -> list[tuple[int, str, str]]:
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
    global _MERGE_CLAIMS
    if (_MERGE_CLAIMS is not None and _MERGE_CLAIMS[0] is prose
            and _MERGE_CLAIMS[1] is config.merge_claim
            and _MERGE_CLAIMS[2] == config.trunk):
        return _MERGE_CLAIMS[3]
    result = _merge_claims(config, prose)
    _MERGE_CLAIMS = (prose, config.merge_claim, config.trunk, result)
    return result


def _merge_claims(config: Config, prose: str) -> list[tuple[int, str, str]]:
    """The scan itself. Separate only so the cache above stays readable."""
    pattern = config.merge_claim
    named = pattern.groups >= 2
    claims: list[tuple[int, str, str]] = []
    # Skipped outright when no match is possible, for the reason
    # `_release_claims` in extant/rules/release_tag.py gives: 12 of ruff's
    # 650 documents hold `merged` or `shipped`, and this scan cost 0.29 s of
    # a 7.1 s sweep on the 638 that do not.
    if not could_match(pattern, prose):
        return claims
    for match in pattern.finditer(prose):
        # ONE line break, no more. `merge_claim` separates its parts with
        # `\s+`, so scanning the whole document - which is what lets a claim
        # wrapped at the margin be seen at all - also lets that `\s+` cross
        # anything whitespace-shaped. Two shapes were measured and both are
        # refused here: a sentence ending in a branch name adopting a SHA from
        # the paragraph AFTER it, and a claim reaching through the run of
        # spaces `prose()` leaves where a fenced block used to be, to a SHA the
        # fence existed to mark as an example. Neither is a claim anybody
        # wrote, and inventing one is worse than missing one.
        #
        # A blank line needs two newlines and a blanked fence needs more, so
        # this single count refuses both. Line-based scanning could not join
        # anything and needed no such guard, which is why the tests for it are
        # written against the widened scan rather than kept from before it.
        # Counted in every spelling a line ending has. `\r\n` contains `\n` so
        # counting newlines was right for CRLF and was never the question; a
        # bare `\r` contains none, so the bound never tripped and the guard
        # below was not one. The offset-to-line count has the same blind spot
        # and reported every claim in such a document as line 1.
        if line_breaks(match.group(0)) > 1:
            continue
        number = line_number_at(prose, match.start())
        if named:
            # The pattern keeps any backticks so the rule can tell a
            # deliberate ref from a word of prose. See `_claimed_ref` in
            # extant/rules/merge.py.
            claims.append((number, match.group(1), match.group(2)))
        else:
            claims.append((number, config.trunk, match.group(1)))
    return claims


def _document_sha_tokens(config: Config, prose: str,
                         own: Callable[[], str | None]) -> list[str]:
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
    tokens = [token for _number, token in find_sha_candidates(prose, own)]
    tokens += [token for _number, token in find_bare_sha_candidates(prose, own)]
    tokens += [sha for _number, _ref, sha in merge_claims(config, prose)]
    return tokens


def document_shas(ctx: Context, prose: str) -> set[str]:
    """Which of this document's SHA-shaped tokens resolve to commits."""
    return resolve_shas(ctx, _document_sha_tokens(
        ctx.config, prose, lambda: own_remote(ctx)))


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


# The repository a commit-shaped URL names: everything before the segment
# that says what it points at, which is how `_LINKED_TAIL` reads a link.
_URL_REPOSITORY = re.compile(
    r"^(?P<head>\S*?)(?:/-)?/(?:commit|commits|blob|tree|pull|compare)/")


def _elsewhere(line: str, own: str | None) -> list[tuple[int, int, str]]:
    """(start, end, repository) for every span of `line` naming a repository
    other than this one's origin: a URL, an `owner/repo@` pin, the text of a
    commit link. A URL whose repository cannot be read off it is one too -
    nothing here can tie it to origin. Read by `translate_shas` alone, to name
    the rewrites git cannot vouch for."""
    spans: list[tuple[int, int, str]] = []
    for match in _URL.finditer(line):
        named = _URL_REPOSITORY.match(match.group(0))
        repository = normalise_remote(named.group("head")) if named else None
        if repository is None or repository != own:
            spans.append((*match.span(), repository or match.group(0)[:60]))
    for match in _PINNED_REF.finditer(line):
        repository = normalise_remote(match.group(0).split("@", 1)[0])
        if repository is None or repository != own:
            spans.append((*match.span(), repository or match.group(0)))
    for pattern in (_LINKED_SHA, _LINKED_BARE_SHA):
        for match in pattern.finditer(line):
            head = match.group("head")
            if not head or head.startswith("."):
                continue        # relative: this repository's own
            repository = normalise_remote(head)
            if repository is None or repository != own:
                spans.append((*match.span(1), repository or head))
    return spans


def translate_shas(text: str, mapping: dict[str, str], *,
                   noted: list[tuple[int, str, str]] | None = None,
                   own: Callable[[], str | None] | None = None,
                   ) -> tuple[str, int]:
    """Rewrite dead SHAs - backticked AND bare (I-1c) - to their post-rewrite
    values, matched by prefix.

    Ambiguous prefixes are left alone; see `translated_value`. Ambiguous or
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
    is the repair for what `dead-sha` reports: the two read the same tokens
    through the same scanners, and separating them is how a class of finding
    ends up unfixable.

    WIDER THAN WHAT IS REPORTED, and on purpose; measured on 2026-10-01 over
    82,802 corpus documents under a full-history map of each clone. 87,585
    tokens in URLs to this repository's own commits translate - the URL
    behind a changelog link whose text the scanner reads, which a repair has
    to move with it - and so do 5,363 in code blocks and 528 astro changeset
    ids, which are commit ids. Two shapes are different:

    * A UUID is never a commit reference, and its groups are skipped here as
      the scanner skips them. 1,282 in the corpus, none translated - closed
      by construction, not by a count.
    * A link, URL or pin naming ANOTHER repository is rewritten and NAMED:
      `noted`, when given, receives (line, token, repository) for each. git
      cannot tell a renamed repository's own commits (node's io.js, about
      513 tokens) from an absorbed upstream's (moveit, rust-clippy, acorn,
      about 169), where the old id is still valid and the rewrite breaks a
      working link. The person applying the map can. `own` answers this
      repository's `owner/name`, asked once and only when a rewrite needs it.
    """
    count = 0
    # The line being translated, and what `_elsewhere` said about it - asked
    # only when a rewrite lands on it and `noted` was given.
    here: list[tuple[int, str]] = [(0, "")]
    spans: dict[int, list[tuple[int, int, str]]] = {}
    origin: list[str | None] = []

    def note(start: int, end: int, token: str) -> None:
        if noted is None:
            return
        number, line = here[0]
        if number not in spans:
            if not origin:
                origin.append(own() if own is not None else None)
            spans[number] = _elsewhere(line, origin[0])
        for first, last, repository in spans[number]:
            if first < end and start < last:
                noted.append((number, token, repository))
                return

    # Once for the document, not once per token. Both replacers below run
    # per match, and a prefix lookup that walked the whole mapping made
    # this O(tokens x map) - the same defect the hint path had.
    index = bucket_index(mapping)

    def replace_backticked(match: "re.Match[str]") -> str:
        nonlocal count
        token = match.group(1)
        # Each end of a range is translated on its own, under the same shape
        # test and the same ambiguity rule the scanner applies, so what is
        # repaired is exactly what was reported: `7d6ec08..7499537` has one
        # end the scanner reads and one it refuses as all digits, and the
        # first is rewritten while the second stays as written.
        ends = _range_ends(token)
        if not any(looks_like_sha(end) for end in ends):
            return match.group(0)
        pieces: list[str] = []
        for end, at in zip(ends, (0, len(token) - len(ends[-1]))):
            new = (translated_value(end, mapping, index)
                   if looks_like_sha(end) else None)
            if new is not None:
                count += 1
                note(match.start(1) + at, match.start(1) + at + len(end), end)
            pieces.append(end if new is None else new)
        if pieces == list(ends):
            return match.group(0)
        separator = token[len(ends[0]):len(token) - len(ends[-1])]
        return f"`{separator.join(pieces)}`"

    def replace_bare(line: str) -> str:
        nonlocal count
        backticked_spans = [m.span() for m in BACKTICKED.finditer(line)]
        # A UUID is never a commit reference; the scanner skips it whole.
        uuid_spans = [m.span() for m in _UUID.finditer(line)]
        pieces: list[str] = []
        cursor = 0
        for match in BARE_SHA_TOKEN.finditer(line):
            if spans_overlap(match.span(), backticked_spans + uuid_spans):
                continue
            token = match.group(0)
            if not looks_like_bare_sha(token):
                continue
            new = translated_value(token, mapping, index)
            if new is None:
                continue
            pieces.append(line[cursor: match.start()])
            pieces.append(new)
            cursor = match.end()
            count += 1
            note(match.start(), match.end(), token)
        pieces.append(line[cursor:])
        return "".join(pieces)

    lines = []
    for number, line in enumerate(text.splitlines(keepends=True), start=1):
        here[0] = (number, line)
        line = BACKTICKED.sub(replace_backticked, line)
        line = replace_bare(line)
        lines.append(line)
    return "".join(lines), count
