import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.assistant.graph import LIST_CLEARED, model_view

LIST = json.dumps([{"document_id": "d1", "title": "Tremblay IMA"}])


def _call(name, call_id):
    return AIMessage(content="", tool_calls=[{"name": name, "args": {}, "id": call_id}])


def test_a_document_list_is_kept_for_the_call_right_after_the_lookup():
    messages = [HumanMessage("q"), _call("list_documents", "c1"), ToolMessage(LIST, tool_call_id="c1")]
    assert model_view(messages, "agent")[2].content == LIST


def test_a_document_list_is_cleared_once_a_later_call_has_used_it():
    messages = [HumanMessage("q"), _call("list_documents", "c1"), ToolMessage(LIST, tool_call_id="c1"),
                _call("compare_contract_to_billing", "c2"), ToolMessage("{}", tool_call_id="c2")]
    for call in ("agent", "answer"):
        view = model_view(messages, call)
        assert view[2].content == LIST_CLEARED and view[2].tool_call_id == "c1"  # the call keeps its result
        assert [type(m) for m in view] == [type(m) for m in messages] and view[4].content == "{}"
    assert messages[2].content == LIST  # the turn's state is untouched
