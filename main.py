#!/usr/bin/env python3
"""Publish the one-line entry for the make.fun bounty
"Worst Fix Ever: Funniest Commit Message".

The commit message lives in ``entry.txt`` next to this file: a
single line for a bug fix that made everything worse, written
as it would sit at the top of a real repository history. This
program reads that file as raw bytes, checks the decoded text
against the bounty gate (UTF-8 text, one line, 1 to 100
characters, not only white space), and writes the exact same
bytes to ``entry.txt`` in the output directory. Nothing is
stripped, trimmed, or re-encoded: the published bytes are
byte-identical to the source file, trailing newline included.
After writing, the program reads the published file back and
compares it byte for byte before reporting success, so a silent
truncation or rewrite can never pass unnoticed.

Characters are counted as Unicode code points, the same way the
gate counts them; bytes are reported beside them so the two can
never be confused. Standard library only, no network, no clock,
no randomness, so two runs always produce identical output.

The output directory is ``--output-dir`` when given, else
``$MAKEFUN_OUTPUT_DIR`` when set, else ``/output``.

Options:
  --output-dir <dir>  write entry.txt into <dir> instead
  --max-chars <n>     check against a limit other than 100
  --verify-only       check the entry without writing anything
  --quiet             print nothing on success (errors still show)

Exit codes: 0 success, 1 the entry fails the gate or the output
cannot be written, 2 a command-line argument is unusable.
"""

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MAX_CHARS = 100


class EntryError(Exception):
    """The entry file fails the bounty gate."""


@dataclass(frozen=True)
class EntryReport:
    """What the gate check found in ``entry.txt``."""

    sentence: str
    byte_length: int
    has_trailing_newline: bool

    @property
    def char_length(self) -> int:
        return len(self.sentence)

    @property
    def word_count(self) -> int:
        return len(self.sentence.split())

    def summary(self) -> str:
        newline = "with" if self.has_trailing_newline else "without"
        return (
            f"{self.char_length} characters, {self.word_count} words, "
            f"{self.byte_length} bytes, {newline} trailing newline"
        )


def entry_path() -> Path:
    return Path(__file__).resolve().parent / "entry.txt"


def load_entry_bytes() -> bytes:
    try:
        return entry_path().read_bytes()
    except FileNotFoundError as exc:
        raise EntryError("entry.txt not found next to main.py") from exc
    except OSError as exc:
        raise EntryError(f"cannot read entry.txt: {exc}") from exc


def inspect_entry(data: bytes, max_chars: int) -> EntryReport:
    """Decode ``data`` and check it against the bounty gate."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EntryError(f"entry.txt is not valid UTF-8: {exc}") from exc
    has_newline = text.endswith("\n")
    sentence = text[:-1] if has_newline else text
    if not sentence or sentence.isspace():
        raise EntryError("entry is empty or only white space")
    if "\n" in sentence or "\r" in sentence:
        raise EntryError("entry must be a single line")
    if sentence != sentence.strip():
        raise EntryError("entry has leading or trailing white space")
    if any(ord(ch) < 32 for ch in sentence):
        raise EntryError("entry contains a control character")
    if len(sentence) > max_chars:
        raise EntryError(
            f"entry is {len(sentence)} characters, "
            f"over the {max_chars} limit"
        )
    return EntryReport(
        sentence=sentence,
        byte_length=len(data),
        has_trailing_newline=has_newline,
    )


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default=None,
        help="directory to write entry.txt into",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=DEFAULT_MAX_CHARS,
        help="character limit to check against (default: 100)",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="validate the entry without writing it",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="print nothing on success",
    )
    return parser.parse_args(argv)


def resolve_output_dir(args) -> Path:
    raw = args.output_dir or os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    out_dir = Path(raw)
    if out_dir.exists() and not out_dir.is_dir():
        raise EntryError(f"output path is not a directory: {out_dir}")
    if out_dir.resolve() == Path(__file__).resolve().parent:
        raise EntryError("output directory must not be the repository root")
    return out_dir


def publish(data: bytes, out_dir: Path) -> Path:
    """Write ``data`` verbatim and prove the copy matches."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "entry.txt"
    out_path.write_bytes(data)
    if out_path.read_bytes() != data:
        raise EntryError("published entry does not match entry.txt")
    return out_path


def fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.max_chars < 1:
        print("--max-chars must be at least 1", file=sys.stderr)
        return 2
    try:
        data = load_entry_bytes()
        report = inspect_entry(data, args.max_chars)
    except EntryError as exc:
        return fail(f"Invalid: {exc}")
    if report.char_length > args.max_chars - 10:
        print(
            f"Note: entry is {report.char_length} characters, "
            f"within 10 of the {args.max_chars} limit",
            file=sys.stderr,
        )
    if args.verify_only:
        if not args.quiet:
            print(f"Valid: {report.summary()}")
        return 0
    try:
        out_dir = resolve_output_dir(args)
        out_path = publish(data, out_dir)
    except EntryError as exc:
        return fail(f"Invalid: {exc}")
    except OSError as exc:
        return fail(f"Cannot write output: {exc}")
    if not args.quiet:
        print(f"Wrote {report.summary()} to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
