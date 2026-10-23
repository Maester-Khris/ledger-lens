from functools import lru_cache

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app import config
from app.assistant.service import AssistantRuntime
from app.assistant.tools import default_tools
from app.assistant.contract_tools import contract_tools
from app.ledger.db import SessionLocal
from app.retrieval import dao as retrieval_dao
from app.retrieval.vector_index import PineconeVectorIndex, StubVectorIndex, VectorIndex


def _vector_index() -> VectorIndex:
    if config.LOADTEST_STUB_VECTORS:  # load tests against the provider mock (OPENAI_BASE_URL), never the demo
        with SessionLocal() as session:
            return StubVectorIndex(retrieval_dao.current_vectors(session))
    return PineconeVectorIndex(config.require("PINECONE_API_KEY"), config.PINECONE_INDEX)


def _chat_model() -> ChatOpenAI:
    # logprobs: the answer call's token logprobs become the turn's confidence (chat eval, measured only for now).
    return ChatOpenAI(model=config.CHAT_MODEL, temperature=0, timeout=config.CHAT_TIMEOUT_SECONDS,
                      max_retries=config.LLM_MAX_RETRIES, logprobs=True)


@lru_cache(maxsize=1)
def get_runtime() -> AssistantRuntime:
    """Composition root for real clients. Tests replace it via FastAPI dependency overrides."""
    return AssistantRuntime(
        chat_model=_chat_model(),
        embeddings=OpenAIEmbeddings(model=config.EMBEDDING_MODEL, timeout=config.EMBEDDING_TIMEOUT_SECONDS,
                                    max_retries=config.LLM_MAX_RETRIES),
        vector_index=_vector_index(),
        tools=default_tools() + contract_tools(),
    )
