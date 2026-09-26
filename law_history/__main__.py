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
    coverage = commands.add_parser("source-coverage", help="Inventory retained source availability; not qualified legal coverage")
    coverage.add_argument("refid", nargs="?", help="Omit to inventory every retained document")
    coverage.add_argument("--known-at", help="Include accepted source observations up to this timezone-aware timestamp")
    show = commands.add_parser("show", help="Show a document's source observations, including observed absence")
    show.add_argument("refid")
    show.add_argument("--role", choices=("laws", "forskrifter", "amendment_acts"),
                      help="Restrict presence/absence to one archive role, e.g. current regulations")
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
    bodies = commands.add_parser("qualify-bodies", help="Qualify every selected body in an accepted v5 observation")
    bodies.add_argument("--observation", help="Accepted observation; omit to catch up only missing v5 products")
    bodies.add_argument("--expected-parent", default="auto")
    bodies.add_argument("--snapshot", type=Path)
    bodies.add_argument("--github-repository", default="sondreskarsten/norwegian-laws-history")
    inventory = commands.add_parser("body-products", help="List source-body receipts, optionally requalifying complete products")
    inventory.add_argument("--verify", action="store_true", help="Requalify every product against its complete raw source")
    body = commands.add_parser("body", help="Retrieve one document from a pinned qualified source-body product")
    body.add_argument("refid")
    body.add_argument("--product", required=True)
    body.add_argument("--output", type=Path, help="Save qualified standalone HTML to a new file")
    operations = commands.add_parser("extract-operations", help="Preserve every parsed act/operation with unresolved temporal evidence")
    operations.add_argument("--observation", help="Accepted observation ID; omitted means catch up all accepted observations")
    operations.add_argument("--expected-parent", default="auto")
    operations.add_argument("--snapshot", type=Path, help="Reuse an unpacked snapshot after complete identity validation")
    operations.add_argument("--github-repository", default="sondreskarsten/norwegian-laws-history")
    commands.add_parser("operation-products", help="Verify and list published operation evidence products")
    act = commands.add_parser("operations", help="Retrieve original operations and unresolved claims for an amendment act")
    act.add_argument("refid")
    act.add_argument("--product", help="Pinned operation-product ID; defaults to the latest product")
    propose = commands.add_parser("propose-claim", help="Append a source-bound proposal without assigning legal eligibility")
    propose.add_argument("request", type=Path, help="JSON proposal with exact subject, evidence and superseded claim")
    claims = commands.add_parser("claim-history", help="Read every proposed interpretation for an exact pinned subject")
    claims.add_argument("target", type=Path, help="JSON target with exact product, source occurrence and subject revision")
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
        elif args.command == "source-coverage":
            from .source_coverage import source_coverage
            result = source_coverage(args.repository, args.refid, args.known_at)
        elif args.command == "show":
            result = show_document(args.repository, args.refid, args.role)
        elif args.command == "materialize":
            if args.observation:
                result = materialize(args.repository, args.observation, args.refid, args.expected_parent)
            else:
                if args.refid or args.expected_parent != "auto":
                    raise ValueError("An explicit selection or parent requires --observation")
                result = materialize_all(args.repository)
        elif args.command == "materializations":
            result = materializations(args.repository)
        elif args.command == "qualify-bodies":
            from .source_body_products import qualify_all, qualify_bodies
            if args.observation:
                result = qualify_bodies(args.repository, args.observation, args.expected_parent, args.snapshot, args.github_repository)
            else:
                if args.snapshot or args.expected_parent != "auto":
                    raise ValueError("A snapshot or parent requires --observation")
                result = qualify_all(args.repository, args.github_repository)
        elif args.command == "body-products":
            from .source_body_products import body_products
            result = body_products(args.repository, verify=args.verify)
        elif args.command == "body":
            from .source_body_reader import read_body
            result = read_body(args.repository, args.refid, args.product)
            if args.output:
                if result["status"] != "qualified":
                    raise ValueError("This document has no qualified body in the selected product")
                with args.output.open("xb") as stream:
                    stream.write(result["document"]["html"].encode("utf-8"))
                result = {**result, "document": None, "output": str(args.output)}
        elif args.command == "extract-operations":
            from .operation_products import extract_all, extract_operations
            if args.observation:
                result = extract_operations(args.repository, args.observation, args.expected_parent, args.snapshot, args.github_repository)
            else:
                if args.snapshot or args.expected_parent != "auto":
                    raise ValueError("A snapshot or parent requires --observation")
                result = extract_all(args.repository, args.github_repository)
        elif args.command == "operation-products":
            from .operation_products import operation_products
            result = operation_products(args.repository)
        elif args.command == "operations":
            from .operation_products import show_operations
            result = show_operations(args.repository, args.refid, args.product)
        elif args.command in ("propose-claim", "claim-history"):
            from .later_claims import claim_history, propose_claim
            from .validation import read_json
            result = (propose_claim(args.repository, read_json(args.request)) if args.command == "propose-claim"
                      else claim_history(args.repository, read_json(args.target)))
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
