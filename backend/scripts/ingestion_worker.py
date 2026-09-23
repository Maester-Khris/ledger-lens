"""Ingestion worker: the only process that loads Docling and spaCy.
Run from backend/:  $PYDEV/bin/python scripts/ingestion_worker.py   (add --once for a single pass)"""
import argparse
import logging
import sys
import time
from functools import partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config  # noqa: E402
from app.documents.ingest import parse_and_redact  # noqa: E402
from app.documents.parse import parse_pdf  # noqa: E402
from app.documents.redact import PiiDetector  # noqa: E402
from app.ingestion_pipeline import PIPELINE, StageRunner, run_pending  # noqa: E402
from app.ledger.db import SessionLocal  # noqa: E402
from langchain_openai import OpenAIEmbeddings  # noqa: E402
from app.retrieval.index import index_version  # noqa: E402
from app.retrieval.vector_index import PineconeVectorIndex  # noqa: E402

EMBEDDING_TIMEOUT_SECONDS = 15
MAX_RETRIES = 3

POLL_SECONDS = 2.0


def build_runners() -> dict[str, StageRunner]:
    return {
        "parse_redact": partial(
            parse_and_redact, parser=parse_pdf, detector=PiiDetector(), store_root=config.DOCUMENT_STORE_DIR,
            hmac_key=config.require("PII_HMAC_KEY"), vault_key=config.require("PII_VAULT_KEY"),
        ),
        "index": partial(
            index_version,
            embeddings=OpenAIEmbeddings(model=config.EMBEDDING_MODEL, timeout=EMBEDDING_TIMEOUT_SECONDS, max_retries=MAX_RETRIES),
            vector_index=PineconeVectorIndex(config.require("PINECONE_API_KEY"), config.PINECONE_INDEX),
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="process pending stages once, then exit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    runners = build_runners()
    # ponytail: one worker, one stage at a time (RAM budget); the advisory lock makes more workers safe when needed
    while True:
        ran = run_pending(SessionLocal, runners, PIPELINE)
        if args.once:
            logging.info("ran %d stage(s)", ran)
            return
        if ran == 0:
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
