"""Create the Pinecone serverless index once. Run from backend/: $PYDEV/bin/python scripts/create_pinecone_index.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pinecone import Pinecone, ServerlessSpec  # noqa: E402

from app import config  # noqa: E402


def main() -> None:
    client = Pinecone(api_key=config.require("PINECONE_API_KEY"))
    if client.has_index(config.PINECONE_INDEX):
        print(f"index {config.PINECONE_INDEX} already exists")
        return
    client.create_index(name=config.PINECONE_INDEX, dimension=config.EMBEDDING_DIMENSIONS, metric="cosine",
                        spec=ServerlessSpec(cloud=config.PINECONE_CLOUD, region=config.PINECONE_REGION))
    print(f"created {config.PINECONE_INDEX} ({config.EMBEDDING_DIMENSIONS} dims, cosine)")


if __name__ == "__main__":
    main()
