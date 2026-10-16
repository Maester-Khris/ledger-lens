import asyncio
import time
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
    structured_kwargs: list[dict] = Field(default_factory=list)

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
        self.structured_kwargs.append(kwargs)

        def run(messages: list[BaseMessage]) -> Any:
            self.prompts.append(_render(messages))
            parsed = self._next(BaseModel)
            return {"raw": AIMessage(content=""), "parsed": parsed, "parsing_error": None} if include_raw else parsed

        return RunnableLambda(run)


class SlowScriptedChatModel(ScriptedChatModel):
    """ScriptedChatModel taking `delay` seconds per call: blocking on the sync path, awaiting on the async one."""

    delay: float = 0.5

    def _generate(self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        time.sleep(self.delay)
        return super()._generate(messages, stop, run_manager, **kwargs)

    async def _agenerate(self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        await asyncio.sleep(self.delay)
        return super()._generate(messages, stop, run_manager, **kwargs)

    def with_structured_output(self, schema: Any, include_raw: bool = False, **kwargs: Any):
        scripted = super().with_structured_output(schema, include_raw, **kwargs)

        def run(messages: list[BaseMessage]) -> Any:
            time.sleep(self.delay)
            return scripted.invoke(messages)

        async def arun(messages: list[BaseMessage]) -> Any:
            await asyncio.sleep(self.delay)
            return scripted.invoke(messages)

        return RunnableLambda(run, afunc=arun)


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
