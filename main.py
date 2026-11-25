#!/usr/bin/env python3
"""Worst Fix Ever — publish the funniest commit message.

This is the entry program for the make.fun bounty "Worst Fix
Ever: Funniest Commit Message". The joke itself lives in
``entry.txt`` beside this file, one line long:

    Fix login bug by removing login — users can no longer log
    in, so technically zero login errors

That is 94 characters, inside the bounty gate of 1 to 100
characters. The fix it describes made everything worse: the
login bug was "fixed" by deleting login altogether, so nobody
can log in any more and there are, technically, zero login
errors. The repair broke more than it mended, which is exactly
what the judge is looking for.

What this program does, in order:

1. Reads ``entry.txt`` as raw bytes — never as text first,
   so no decoding step can silently change anything.
2. Decodes those bytes as UTF-8 and checks the line against
   the gate: one line, 1 to 100 characters (counted as Unicode
   code points, the way the gate counts them), no leading or
   trailing white space, no control characters, not empty.
3. Writes the *same bytes* — untouched, untrimmed, never
   re-encoded — to ``entry.txt`` inside the output directory.
4. Reads the published file back and compares it byte for
   byte with the source. If a single byte differs, the run
   fails instead of reporting success.

Nothing here touches the network, the clock, or a random
number generator, and only the Python standard library is
used, so every run behaves the same way.

Where the output goes: ``--output-dir`` wins when given,
otherwise the ``MAKEFUN_OUTPUT_DIR`` environment variable,
otherwise ``/output``.

Usage:

    python3 main.py
    python3 main.py --output-dir /tmp/out
    python3 main.py --verify-only
    python3 main.py --show
    python3 main.py --quiet --output-dir /tmp/out

Exit codes: 0 means the entry passed the gate and was
published (or, with ``--verify-only``, passed the gate);
1 means the entry failed the gate or the output could not
be written; 2 means a command-line argument was unusable.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# The bounty gate: a commit message of 1 to 100 characters.
GATE_MIN_CHARS = 1
GATE_MAX_CHARS = 100

# How close to the limit counts as "nearly full" for the warning.
NEAR_LIMIT_MARGIN = 10

# Fallback output directory when neither the flag nor the
# environment variable names one.
FALLBACK_OUTPUT_DIR = "/output"


class GateFailure(Exception):
    """Raised when the entry, or the output step, fails the gate."""


class CheckedEntry:
    """The entry line plus the measurements the gate made.

    ``raw`` is the exact bytes read from ``entry.txt``,
    trailing newline included. ``line`` is that text with
    the single trailing newline removed. Keeping both around
    is what makes the verbatim publish possible: the program
    writes ``raw`` and only ever *reads* ``line``.
    """

    def __init__(self, raw: bytes, line: str) -> None:
        self.raw = raw
        self.line = line

    @property
    def characters(self) -> int:
        """Length in Unicode code points, as the gate counts it."""
        return len(self.line)

    @property
    def words(self) -> int:
        """Whitespace-separated words in the line."""
        return len(self.line.split())

    @property
    def ends_with_newline(self) -> bool:
        """True when the source file ends with a newline."""
        return self.raw.endswith(b"\n")

    @property
    def non_ascii(self) -> int:
        """Characters outside plain ASCII (the em dash here)."""
        return sum(1 for char in self.line if ord(char) > 127)

    def describe(self) -> str:
        """One human-readable line summarising the checked entry."""
        ending = "with" if self.ends_with_newline else "without"
        extra = ""
        if self.non_ascii:
            noun = "character" if self.non_ascii == 1 else "characters"
            extra = f", {self.non_ascii} non-ASCII {noun}"
        return (
            f"{self.characters} characters, {self.words} words, "
            f"{len(self.raw)} bytes{extra}, {ending} trailing newline"
        )

    def headroom(self, limit: int) -> int:
        """Characters still spare under ``limit`` (never negative)."""
        return max(0, limit - self.characters)


def source_file() -> Path:
    """Path of ``entry.txt`` sitting next to this program."""
    return Path(__file__).resolve().parent / "entry.txt"


def read_source_bytes() -> bytes:
    """Read ``entry.txt`` as raw bytes, or raise ``GateFailure``."""
    try:
        return source_file().read_bytes()
    except FileNotFoundError as exc:
        raise GateFailure("entry.txt not found next to main.py") from exc
    except IsADirectoryError as exc:
        raise GateFailure("entry.txt is a directory, not a file") from exc
    except OSError as exc:
        raise GateFailure(f"cannot read entry.txt: {exc}") from exc


def check_line(line: str, limit: int) -> None:
    """Apply every gate rule to the decoded line, in order.

    Each rule raises ``GateFailure`` with a message naming the
    rule that failed, so a bad entry says *why* it is bad
    instead of just failing silently.
    """
    if not line:
        raise GateFailure("entry is empty")
    if line.isspace():
        raise GateFailure("entry is only white space")
    if line != line.strip():
        raise GateFailure("entry has leading or trailing white space")
    if "\n" in line or "\r" in line:
        raise GateFailure("entry must be a single line")
    if "\t" in line:
        raise GateFailure("entry contains a tab character")
    for position, char in enumerate(line):
        if ord(char) < 32 or ord(char) == 127:
            raise GateFailure(
                f"entry contains a control character at position {position}"
            )
    if len(line) < GATE_MIN_CHARS:
        raise GateFailure(
            f"entry is {len(line)} characters, below the minimum "
            f"of {GATE_MIN_CHARS}"
        )
    if len(line) > limit:
        raise GateFailure(
            f"entry is {len(line)} characters, over the {limit} limit"
        )


def decode_and_check(raw: bytes, limit: int) -> CheckedEntry:
    """Decode ``raw`` as UTF-8 and run the gate over the line.

    A file without a trailing newline is accepted — the gate
    counts characters, not newlines — but the published bytes
    are still exactly ``raw``, newline or no newline.
    """
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GateFailure(f"entry.txt is not valid UTF-8: {exc}") from exc
    line = text[:-1] if text.endswith("\n") else text
    check_line(line, limit)
    return CheckedEntry(raw=raw, line=line)


def build_parser() -> argparse.ArgumentParser:
    """Command-line parser for the publisher's flags."""
    parser = argparse.ArgumentParser(
        description=(
            "Validate the one-line commit-message entry in entry.txt "
            "and publish it byte-for-byte to the output directory."
        ),
        epilog=(
            "Exit codes: 0 success, 1 the entry fails the gate or "
            "the output cannot be written, 2 a bad argument."
        ),
    )
    parser.add_argument(
        "--output-dir",
        metavar="DIR",
        default=None,
        help="write entry.txt into DIR (default: $MAKEFUN_OUTPUT_DIR or /output)",
    )
    parser.add_argument(
        "--max-chars",
        metavar="N",
        type=int,
        default=GATE_MAX_CHARS,
        help="character limit to check against (default: 100)",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="check the entry against the gate without writing anything",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="print the entry line itself as well as the summary",
    )
    parser.add_argument(
        "--no-clobber",
        action="store_true",
        help="refuse to overwrite an existing entry.txt with different bytes",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="print nothing on success (errors still print)",
    )
    return parser


def pick_output_dir(output_dir: str | None) -> Path:
    """Resolve the output directory from flag, env, or fallback.

    Refuses to publish into the repository root itself, where
    the output would overwrite the source ``entry.txt``.
    """
    chosen = output_dir or os.environ.get("MAKEFUN_OUTPUT_DIR") or FALLBACK_OUTPUT_DIR
    directory = Path(chosen)
    if directory.exists() and not directory.is_dir():
        raise GateFailure(f"output path is not a directory: {directory}")
    if directory.resolve() == source_file().parent:
        raise GateFailure("output directory must not be the repository root")
    return directory


def publish_verbatim(raw: bytes, directory: Path, no_clobber: bool = False) -> Path:
    """Write ``raw`` unchanged, then prove the copy matches.

    The directory is created when needed. After writing, the
    published file is read back and compared byte for byte:
    any mismatch raises instead of reporting a success that
    did not happen. With ``no_clobber``, an existing output
    file holding different bytes is refused rather than
    overwritten; an identical one is left alone and counts
    as already published.
    """
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise GateFailure(f"cannot create output directory: {exc}") from exc
    destination = directory / "entry.txt"
    if no_clobber and destination.exists():
        try:
            existing = destination.read_bytes()
        except OSError as exc:
            raise GateFailure(f"cannot read existing output: {exc}") from exc
        if existing != raw:
            raise GateFailure(
                f"refusing to overwrite {destination} with different bytes"
            )
        return destination
    try:
        destination.write_bytes(raw)
    except OSError as exc:
        raise GateFailure(f"cannot write output: {exc}") from exc
    try:
        written = destination.read_bytes()
    except OSError as exc:
        raise GateFailure(f"cannot read back the published entry: {exc}") from exc
    if written != raw:
        raise GateFailure("published entry does not match entry.txt")
    return destination


def warn_when_near_limit(entry: CheckedEntry, limit: int) -> None:
    """Warn on stderr when the entry is close to the limit."""
    if entry.headroom(limit) <= NEAR_LIMIT_MARGIN:
        print(
            f"Note: entry is {entry.characters} characters, "
            f"within {NEAR_LIMIT_MARGIN} of the {limit} limit",
            file=sys.stderr,
        )


def report_checked(entry: CheckedEntry, show: bool, quiet: bool) -> None:
    """Print the verify-only line, unless ``--quiet`` was given."""
    if quiet:
        return
    print(f"Valid: {entry.describe()} (not written)")
    if show:
        print(entry.line)


def report_published(entry: CheckedEntry, show: bool, quiet: bool, destination: Path) -> None:
    """Print the publish line, unless ``--quiet`` was given."""
    if quiet:
        return
    print(f"Wrote {entry.describe()} to {destination}")
    if show:
        print(entry.line)


def run(argv: list[str] | None = None) -> int:
    """Parse arguments, check the entry, publish it, report."""
    args = build_parser().parse_args(argv)
    if args.max_chars < GATE_MIN_CHARS:
        print("--max-chars must be at least 1", file=sys.stderr)
        return 2
    try:
        raw = read_source_bytes()
        entry = decode_and_check(raw, args.max_chars)
    except GateFailure as exc:
        print(f"Invalid: {exc}", file=sys.stderr)
        return 1
    warn_when_near_limit(entry, args.max_chars)
    if args.verify_only:
        report_checked(entry, args.show, args.quiet)
        return 0
    try:
        directory = pick_output_dir(args.output_dir)
        destination = publish_verbatim(raw, directory, args.no_clobber)
    except GateFailure as exc:
        print(f"Invalid: {exc}", file=sys.stderr)
        return 1
    report_published(entry, args.show, args.quiet, destination)
    return 0


def main() -> int:
    """Entry point: run with the real command-line arguments."""
    return run(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
