from scripts import token_report

AGENT = {"messages": [{"role": "system", "content": "You answer questions."}, {"role": "user", "content": "What is the fee?"}],
         "tools": [{"type": "function", "function": {"name": "search_contracts"}}]}
ANSWER = AGENT | {"response_format": {"type": "json_schema"}}


def test_shared_prefix_counts_the_leading_equal_tokens():
    assert token_report.shared_prefix([1, 2, 3], [1, 2, 4, 5]) == 2
    assert token_report.shared_prefix([], [1]) == 0


def test_tool_definitions_count_toward_the_request():
    plain = {"messages": AGENT["messages"]}
    assert len(token_report.request_tokens(AGENT)) > len(token_report.request_tokens(plain))


def test_calls_are_named_in_turn_order_with_their_shared_prefix():
    record = token_report.turn_record([AGENT, AGENT, ANSWER, ANSWER])
    assert [c["kind"] for c in record["calls"]] == ["agent 1", "agent 2", "answer", "retry"]
    assert record["calls"][0]["shared_prefix"] == 0
    assert record["calls"][1]["shared_prefix"] == record["calls"][1]["tokens"]  # an identical request is all prefix
    assert record["tokens"] == sum(c["tokens"] for c in record["calls"])


def test_the_summary_gives_medians_per_turn_and_per_call_kind():
    turns = [token_report.turn_record([AGENT, ANSWER]), token_report.turn_record([AGENT, AGENT, ANSWER])]
    summary = token_report.summarise(turns)
    assert summary["turns"] == 2 and set(summary["median_by_call"]) == {"agent 1", "agent 2", "answer"}
    assert 0 < summary["shared_prefix_share"] <= 1


def test_the_row_prints_one_markdown_line_for_the_changelog():
    summary = token_report.summarise([token_report.turn_record([AGENT, ANSWER])])
    line = token_report.row("t0", summary)
    assert line.startswith("| t0 | 1 | ") and line.endswith(" |") and "\n" not in line
