"""Create the Pinecone serverless index once. Run from backend/:
$PYDEV/bin/python scripts/create_pinecone_index.py [name]   (name defaults to PINECONE_INDEX)
Demo: ENV_FILE=.env.demo $PYDEV/bin/python scripts/create_pinecone_index.py contract-demo"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pinecone import Pinecone, ServerlessSpec  # noqa: E402

from app import config  # noqa: E402
from app.ledger.types import DEMO_TENANT_ID  # noqa: E402


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else config.PINECONE_INDEX
    client = Pinecone(api_key=config.require("PINECONE_API_KEY"))
    if client.has_index(name):
        print(f"index {name} already exists")
        return
    client.create_index(name=name, dimension=config.EMBEDDING_DIMENSIONS, metric="cosine",
                        spec=ServerlessSpec(cloud=config.PINECONE_CLOUD, region=config.PINECONE_REGION))
    print(f"created {name} ({config.EMBEDDING_DIMENSIONS} dims, cosine); namespace (tenant id): {DEMO_TENANT_ID}")


if __name__ == "__main__":
    main()
