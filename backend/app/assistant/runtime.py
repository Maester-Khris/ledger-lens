from functools import lru_cache

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app import config
from app.assistant.service import AssistantRuntime
from app.assistant.tools import default_tools
from app.assistant.contract_tools import contract_tools
from app.retrieval.vector_index import PineconeVectorIndex

CHAT_TIMEOUT_SECONDS = 30
EMBEDDING_TIMEOUT_SECONDS = 15
MAX_RETRIES = 3


@lru_cache(maxsize=1)
def get_runtime() -> AssistantRuntime:
    """Composition root for real clients. Tests replace it via FastAPI dependency overrides."""
    return AssistantRuntime(
        chat_model=ChatOpenAI(model=config.CHAT_MODEL, temperature=0, timeout=CHAT_TIMEOUT_SECONDS, max_retries=MAX_RETRIES),
        embeddings=OpenAIEmbeddings(model=config.EMBEDDING_MODEL, timeout=EMBEDDING_TIMEOUT_SECONDS, max_retries=MAX_RETRIES),
        vector_index=PineconeVectorIndex(config.require("PINECONE_API_KEY"), config.PINECONE_INDEX),
        tools=default_tools() + contract_tools(),
    )
