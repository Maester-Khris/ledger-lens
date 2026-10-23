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


PAYLOAD = {"sections": {"S1": {"document": "Tremblay IMA", "section": "3. Fees", "text": "A long section text."}},
           "hits": [{"id": "e1", "section": "S1", "page": 1, "text": "Fees are billed quarterly."}]}


def _searched(content):
    return [HumanMessage("q"), _call("search_contracts", "c1"), ToolMessage(content, tool_call_id="c1")]


def test_agent_calls_see_hits_without_section_text():
    agent = json.loads(model_view(_searched(json.dumps(PAYLOAD)), "agent")[2].content)
    assert agent == {"hits": [{"id": "e1", "page": 1, "text": "Fees are billed quarterly.",
                               "document": "Tremblay IMA", "section": "3. Fees"}]}


def test_the_answer_call_sees_the_full_search_result():
    assert json.loads(model_view(_searched(json.dumps(PAYLOAD)), "answer")[2].content) == PAYLOAD


def test_tool_errors_reach_every_call_unchanged():
    # Review Focus 4
    for content in ('{"error": "invalid arguments (query: Field required)"}', "Unknown tool search_contract"):
        for call in ("agent", "answer"):
            assert model_view(_searched(content), call)[2].content == content
