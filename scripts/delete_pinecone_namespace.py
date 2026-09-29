"""Delete every vector in one Pinecone namespace.
Run from the repo root:  python scripts/delete_pinecone_namespace.py --namespace <namespace>"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import config  # noqa: E402
from pinecone import Pinecone  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", required=True, help="Pinecone namespace to clear, e.g. a tenant id")
    args = parser.parse_args()

    index = Pinecone(api_key=config.require("PINECONE_API_KEY")).Index(config.PINECONE_INDEX)
    before = index.describe_index_stats().namespaces.get(args.namespace)
    count = before.vector_count if before else 0
    print(f"namespace {args.namespace!r}: {count} vector(s) before delete")

    if count == 0:
        print("nothing to delete")
        return

    index.delete(delete_all=True, namespace=args.namespace)

    after = index.describe_index_stats().namespaces.get(args.namespace)
    print(f"namespace {args.namespace!r}: {after.vector_count if after else 0} vector(s) after delete")


if __name__ == "__main__":
    main()
