"""Verify, commit and push the working tree in one step.

Usage:

    python scripts/up.py [MESSAGE...] [--fast] [--no-push]

    git up                      # commit "wip" and push
    git up ajusta ranking       # commit with a message
    git up --fast               # skip pytest (ruff still runs)

Pipeline: ruff format -> ruff check --fix -> pytest (unit) -> add -A -> commit -> push.
Any failing step stops the run before anything is committed.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV_PYTHONS = (ROOT / ".venv/Scripts/python.exe", ROOT / ".venv/bin/python")
CHECKED_PATHS = ("src", "tests", "utils", "scripts")
DEFAULT_MESSAGE = "wip"


def run(*args: str, check: bool = True, **env: str) -> subprocess.CompletedProcess[str]:

    merged_env = {**os.environ, **env}

    return subprocess.run(
        args,
        cwd=ROOT,
        env=merged_env,
        text=True,
        check=check,
    )


def capture(*args: str) -> str:

    return subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def step(title: str) -> None:

    print(f"\n==> {title}", flush=True)


def reexec_in_venv() -> None:
    """Restart under the project's virtualenv when invoked with another interpreter."""

    current = Path(sys.executable).resolve()

    for candidate in VENV_PYTHONS:
        if not candidate.exists():
            continue

        if candidate.resolve() == current:
            return

        result = subprocess.run([str(candidate), *sys.argv], cwd=ROOT)
        sys.exit(result.returncode)

    print("warning: .venv not found, using", sys.executable, file=sys.stderr)


def parse_args(argv: list[str]) -> tuple[str, bool, bool]:

    fast = "--fast" in argv
    no_push = "--no-push" in argv
    words = [a for a in argv if a not in ("--fast", "--no-push")]
    message = " ".join(words) or DEFAULT_MESSAGE

    return message, fast, no_push


def has_local_changes() -> bool:

    return bool(capture("git", "status", "--porcelain"))


def has_unpushed_commits() -> bool:

    upstream = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "@{upstream}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    revs = "@{upstream}..HEAD" if upstream.returncode == 0 else "HEAD"
    count = subprocess.run(
        ["git", "rev-list", "--count", revs],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    return count.returncode == 0 and int(count.stdout) > 0


def verify(fast: bool) -> None:

    python = sys.executable

    step("ruff format")
    run(python, "-m", "ruff", "format", *CHECKED_PATHS)

    step("ruff check --fix")
    run(python, "-m", "ruff", "check", "--fix", *CHECKED_PATHS)

    if fast:
        print("\n(--fast) skipping pytest")
        return

    step("pytest (unit)")
    run(
        python,
        "-m",
        "pytest",
        "-q",
        "--tb=short",
        "-p",
        "no:warnings",
        PYTHONPATH="src",
    )


def commit_and_push(message: str, no_push: bool) -> None:

    if has_local_changes():
        step(f"git commit -m {message!r}")
        run("git", "add", "-A")
        run("git", "commit", "-q", "-m", message)
        print(capture("git", "log", "-1", "--oneline"))

    if no_push:
        print("\n(--no-push) skipping push")
        return

    if not has_unpushed_commits():
        print("\nnothing to push")
        return

    step("git push")
    run("git", "push")


def main(argv: list[str]) -> int:

    reexec_in_venv()
    message, fast, no_push = parse_args(argv)
    started = time.monotonic()

    if not has_local_changes() and not has_unpushed_commits():
        print("nothing to do: working tree clean and remote up to date")
        return 0

    try:
        verify(fast)
        commit_and_push(message, no_push)
    except subprocess.CalledProcessError as exc:
        print(
            f"\nstopped: `{' '.join(exc.cmd)}` exited with {exc.returncode}",
            file=sys.stderr,
        )
        return exc.returncode

    print(f"\ndone in {time.monotonic() - started:.1f}s")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
