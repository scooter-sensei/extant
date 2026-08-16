"""What a rule returns, and where it was found."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

__all__ = ["Finding", "Located", "rel"]


def rel(repo: Path, path: Path) -> str:
    """Repo-relative POSIX path.

    Both machine formats locate a result by path, and both want it relative to
    the repository root with forward slashes. A Windows absolute path in a
    SARIF upload resolves to nothing on the server, so this is not cosmetic.

    Here rather than beside the formatters, because `dead-md-anchor` names the
    OTHER document in its finding detail and so needs the same spelling the
    formatters use. Detail strings are a shipped wire format - the baseline
    fingerprint hashes (path, kind, detail) - so the two must not be allowed to
    drift into two spellings of one path.
    """
    try:
        return path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


@dataclass(frozen=True)
class Finding:
    line: int
    kind: str
    detail: str
    # The bare token this claim is about, unquoted: `abc1234`, `v2.1`,
    # `docs/plan.md`. Consumers that need to ask "is this claim still written
    # down anywhere" would otherwise have to scrape backticks out of `detail`,
    # which is prose and rots.
    #
    # Optional because it is populated rule by rule. `--deleted-since` skips
    # findings without one and REPORTS how many it skipped, so partial coverage
    # is visible in the denominator rather than silently narrowing what that
    # mode can see.
    #
    # Deliberately outside the baseline fingerprint, which keys on
    # (path, kind, detail). Folding it in would invalidate every baseline
    # already recorded in every project that has one.
    subject: str | None = None

    def render(self) -> str:
        return f"line {self.line}: [{self.kind}] {self.detail}"


@dataclass(frozen=True)
class Located:
    """A finding plus the document it came from.

    The file used to live only in the print statement that rendered a finding,
    which was enough for a human reading a terminal and not enough for anything
    else. A machine format has to say WHICH file every result belongs to, so
    the pairing is now carried in the data rather than reconstructed at the
    moment of printing.
    """

    path: str          # repo-relative, forward slashes, for machine consumers
    finding: Finding
    primary: bool      # the document asked for, as opposed to archive/extra
    # Whether this finding DECIDES the exit code. Not derivable from `primary`:
    # in `--verify` an archive finding gates while not being primary, and in a
    # sweep an unreviewed one is primary-adjacent and does not gate.
    #
    # It exists for SARIF, which published every finding at `level: error`
    # while a sweep exited 0 - so a survey the README promises "cannot fail
    # your build" arrived in code scanning as a wall of errors. The exit code
    # was right and the machine format contradicted it.
    #
    # Defaults True so every caller that gates on everything is unchanged.
    gating: bool = True
