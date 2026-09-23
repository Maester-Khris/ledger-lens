from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel

from tests.fakes import RecordingEmbeddings, ScriptedChatModel


class Reply(BaseModel):
    text: str


def test_scripted_model_plays_back_and_records():
    model = ScriptedChatModel(replies=[AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "c1"}]), Reply(text="hi")])
    bound = model.bind_tools([], tool_choice="t")
    first = bound.invoke([HumanMessage(content="question one")])
    assert first.tool_calls[0]["name"] == "t"
    structured = model.with_structured_output(Reply, include_raw=True).invoke([HumanMessage(content="question two")])
    assert structured["parsed"].text == "hi"
    assert model.tool_choices == ["t"]
    assert "question one" in model.prompts[0] and "question two" in model.prompts[1]


def test_recording_embeddings_are_deterministic():
    embeddings = RecordingEmbeddings()
    assert embeddings.embed_query("a") == embeddings.embed_query("a")
    embeddings.embed_documents(["b", "c"])
    assert embeddings.seen == ["a", "a", "b", "c"]
