from typing import Any

from langchain_core.embeddings import DeterministicFakeEmbedding
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel, Field


def _render(messages: list[BaseMessage]) -> str:
    return "\n".join(f"{m.type}: {m.content}" for m in messages)


class ScriptedChatModel(BaseChatModel):
    """Plays back scripted replies in order and records every prompt (the privacy test's spy)."""

    replies: list[Any] = Field(default_factory=list)
    prompts: list[str] = Field(default_factory=list)
    tool_choices: list[Any] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _next(self, kind: type) -> Any:
        assert self.replies, "ScriptedChatModel ran out of replies"
        reply = self.replies.pop(0)
        assert isinstance(reply, kind), f"expected {kind.__name__}, script has {type(reply).__name__}"
        return reply

    def _generate(self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        self.prompts.append(_render(messages))
        return ChatResult(generations=[ChatGeneration(message=self._next(AIMessage))])

    def bind_tools(self, tools: Any, tool_choice: Any = None, **kwargs: Any) -> "ScriptedChatModel":
        self.tool_choices.append(tool_choice)
        return self

    def with_structured_output(self, schema: Any, include_raw: bool = False, **kwargs: Any):
        def run(messages: list[BaseMessage]) -> Any:
            self.prompts.append(_render(messages))
            parsed = self._next(BaseModel)
            return {"raw": AIMessage(content=""), "parsed": parsed, "parsing_error": None} if include_raw else parsed

        return RunnableLambda(run)


class RecordingEmbeddings(DeterministicFakeEmbedding):
    seen: list[str] = Field(default_factory=list)

    def __init__(self, size: int = 8, **kwargs: Any) -> None:
        super().__init__(size=size, **kwargs)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.seen.extend(texts)
        return super().embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        self.seen.append(text)
        return super().embed_query(text)
