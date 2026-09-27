from typing import Optional
from langfuse.langchain import CallbackHandler
from app.config import TRACING_ENABLED, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST, LANGFUSE_TRACING_ENVIRONMENT

def get_tracing_handler() -> Optional[CallbackHandler]:
    if not TRACING_ENABLED:
        return None
    return CallbackHandler(
        public_key=LANGFUSE_PUBLIC_KEY
    )

def flush_tracing() -> None:
    if TRACING_ENABLED:
        try:
            from langfuse import Langfuse
            Langfuse(
                public_key=LANGFUSE_PUBLIC_KEY,
                secret_key=LANGFUSE_SECRET_KEY,
                host=LANGFUSE_HOST
            ).flush()
        except Exception:
            pass
