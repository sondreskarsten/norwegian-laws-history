"""Command-line interface for immutable observations and exact source retrieval."""
import argparse
import json
from pathlib import Path
import sys
import sqlite3
import tarfile

from .ledger import ingest, list_observations, raw_member, show_document


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path("."), help="History ledger directory")
    commands = parser.add_subparsers(dest="command", required=True)
    accept = commands.add_parser("ingest", help="Verify a local or public GitHub evidence.json and accept its observation")
    accept.add_argument("receipt")
    accept.add_argument("--bundle", type=Path, help="Explicit local snapshot.tar.gz; otherwise use sibling/public URL")
    commands.add_parser("list", help="List accepted observations")
    show = commands.add_parser("show", help="Show a document's source observations, including observed absence")
    show.add_argument("refid")
    raw = commands.add_parser("raw", help="Retrieve exact archived XML after digest verification")
    raw.add_argument("refid")
    raw.add_argument("--observation", required=True)
    raw.add_argument("--occurrence", help="Required when a refid has multiple source occurrences")
    raw.add_argument("--output", type=Path, help="Write exact bytes to a new file; default is stdout")
    args = parser.parse_args(argv)
    try:
        if args.command == "ingest":
            result = ingest(args.receipt, args.repository, args.bundle)
        elif args.command == "list":
            result = list_observations(args.repository)
        elif args.command == "show":
            result = show_document(args.repository, args.refid)
        else:
            content = raw_member(args.repository, args.observation, args.refid, args.occurrence)
            if args.output:
                with args.output.open("xb") as stream:
                    stream.write(content)
            else:
                sys.stdout.buffer.write(content)
            return 0
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError, AttributeError, sqlite3.Error, tarfile.TarError) as exc:
        print(f"Evidence rejected: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
