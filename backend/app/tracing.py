import logging
from typing import Optional
from langfuse.langchain import CallbackHandler
from langfuse import Langfuse
from app.config import TRACING_ENABLED, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST, LANGFUSE_TRACING_ENVIRONMENT

logger = logging.getLogger(__name__)

_client = None
if TRACING_ENABLED:
    _client = Langfuse(
        public_key=LANGFUSE_PUBLIC_KEY,
        secret_key=LANGFUSE_SECRET_KEY,
        host=LANGFUSE_HOST,
        environment=LANGFUSE_TRACING_ENVIRONMENT,
    )

def get_tracing_handler() -> Optional[CallbackHandler]:
    if not TRACING_ENABLED:
        return None
    # LangChain CallbackHandler in Langfuse 3.x uses the global client by default,
    # or we could just instantiate it without kwargs.
    return CallbackHandler()

def flush_tracing() -> None:
    if TRACING_ENABLED and _client is not None:
        try:
            _client.flush()
        except Exception as e:
            logger.warning("Failed to flush Langfuse tracing: %s", str(e), exc_info=True)
