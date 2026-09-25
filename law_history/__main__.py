"""Command-line interface for immutable observations and exact source retrieval."""
import argparse
import json
from pathlib import Path
import sys
import sqlite3
import tarfile

from .ledger import ingest, list_observations, raw_member, show_document
from .materialize import materialize, materialize_all, materializations


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
    project = commands.add_parser("materialize", help="Generate qualified observed-body products from accepted evidence")
    project.add_argument("--observation", help="Accepted observation ID; omitted means catch up all accepted observations")
    project.add_argument("--refid", action="append", help="Explicit bounded document selection; repeat up to 20 times")
    project.add_argument("--expected-parent", default="auto", help="Expected prior materialization ID, or none for the first")
    commands.add_parser("materializations", help="Read and verify the append-only derived-product chain")
    publish = commands.add_parser("publish", help="Publish new ledger/products and separate Git receipts with checked parents")
    publish.add_argument("--remote", default="origin")
    publish.add_argument("--branch", default="main")
    publish.add_argument("--github-repository", default="sondreskarsten/norwegian-laws-history")
    publish.add_argument("--report", type=Path, help="Write the publication/readback report outside the accepted products")
    args = parser.parse_args(argv)
    try:
        if args.command == "ingest":
            result = ingest(args.receipt, args.repository, args.bundle)
        elif args.command == "list":
            result = list_observations(args.repository)
        elif args.command == "show":
            result = show_document(args.repository, args.refid)
        elif args.command == "materialize":
            if args.observation:
                result = materialize(args.repository, args.observation, args.refid, args.expected_parent)
            else:
                if args.refid or args.expected_parent != "auto":
                    raise ValueError("An explicit selection or parent requires --observation")
                result = materialize_all(args.repository)
        elif args.command == "materializations":
            result = materializations(args.repository)
        elif args.command == "publish":
            from .publication import publish as publish_products
            result = publish_products(args.repository, args.remote, args.branch, args.github_repository)
            if args.report:
                args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
