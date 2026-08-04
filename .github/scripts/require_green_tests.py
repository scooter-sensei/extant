"""Refuse to publish unless the test suite passed on THIS commit.

Pushing a tag publishes to PyPI, and `publish.yml` never consulted `tests.yml`,
so a red suite did not stop an upload. 0.19.0 shipped that way: the push
succeeded, the tag went up ninety seconds later, and nobody opened the Actions
tab in between. The artifact happened to be fine. That was luck, and PyPI does
not allow replacing a released version, so luck is the wrong mechanism.

Matched by COMMIT, not by ref. `tests.yml` runs on pushes to `main` and on pull
requests, never on tags, so there is no run attached to the tag itself - the run
to find is the one for the commit the tag points at.

Three outcomes, kept distinct on purpose:

  no run at all   -> FAIL. This is the one that matters. A gate that treats
                     "nothing found" as "nothing wrong" passes hardest exactly
                     when the thing it guards was never checked - which happens
                     for real, whenever a tag is pushed before its branch.
  not finished    -> keep waiting, then FAIL on timeout.
  finished        -> the conclusion decides.

The count of runs examined is always printed, because "0 examined" and
"0 failures" are the same sentence otherwise.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://api.github.com"

PASS, FAIL, PENDING = "pass", "fail", "pending"


def decide(runs: list[dict]) -> tuple[str, str]:
    """(verdict, human sentence) for the runs matching one commit.

    Newest first, which is how the API returns them. The NEWEST decides,
    because a re-run is a deliberate retry and its answer supersedes the
    attempt it replaced; requiring every historical attempt to be green would
    make a failed-then-fixed run unpublishable forever.
    """
    if not runs:
        return FAIL, (
            "no tests run exists for this commit. Push the branch and let it "
            "finish before tagging - the tag itself never triggers tests."
        )

    newest = runs[0]
    status = newest.get("status")
    conclusion = newest.get("conclusion")
    where = newest.get("html_url", "(no url)")

    if status != "completed":
        return PENDING, f"newest run is {status}: {where}"
    if conclusion == "success":
        return PASS, f"newest run succeeded: {where}"
    return FAIL, f"newest run concluded {conclusion}: {where}"


def fetch(repo: str, workflow: str, sha: str, token: str) -> list[dict]:
    url = f"{API}/repos/{repo}/actions/workflows/{workflow}/runs?head_sha={sha}"
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    return payload.get("workflow_runs", [])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--sha", default=os.environ.get("GITHUB_SHA"))
    parser.add_argument("--workflow", default="tests.yml")
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--poll-seconds", type=int, default=30)
    args = parser.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN", "")
    missing = [name for name, value in
               (("--repo", args.repo), ("--sha", args.sha),
                ("GITHUB_TOKEN", token)) if not value]
    if missing:
        # Never treated as "cannot check, so allow". An unconfigured gate that
        # passes is indistinguishable from a working one.
        print(f"::error::cannot check the test run, missing: {', '.join(missing)}")
        return 1

    deadline = time.monotonic() + args.timeout_seconds
    while True:
        try:
            runs = fetch(args.repo, args.workflow, args.sha, token)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            print(f"::error::could not read workflow runs: {exc}")
            return 1

        verdict, sentence = decide(runs)
        # The denominator, printed on every pass through the loop.
        print(f"checked {args.workflow} for {args.sha[:12]}: "
              f"{len(runs)} run(s) found -> {verdict}")
        for run in runs:
            print(f"    {run.get('status')}/{run.get('conclusion')} "
                  f"{run.get('html_url', '')}")

        if verdict == PASS:
            print(sentence)
            return 0
        if verdict == FAIL:
            print(f"::error::{sentence}")
            return 1
        if time.monotonic() >= deadline:
            print(f"::error::timed out waiting for the tests run. {sentence}")
            return 1
        print(f"{sentence} - waiting {args.poll_seconds}s")
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
