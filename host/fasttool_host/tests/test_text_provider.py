import pytest

from fasttool_host.text_provider import TextProviderError, ToolTextResults


def test_text_results_parse_correlated_resolved_text() -> None:
    results = ToolTextResults.from_dict(
        {
            "tool_id": "fasttextsuggester",
            "provider_id": "suggestions",
            "session_id": "session-1",
            "request_id": "request-2",
            "results": [
                {"title": "email", "subtitle": "replacement", "text": "a@example.com"}
            ],
        }
    )

    assert results.request_id == "request-2"
    assert results.results[0].title == "email"
    assert results.results[0].text == "a@example.com"


def test_text_results_reject_non_list_results() -> None:
    with pytest.raises(TextProviderError):
        ToolTextResults.from_dict(
            {
                "tool_id": "x",
                "provider_id": "p",
                "session_id": "s",
                "request_id": "r",
                "results": "invalid",
            }
        )
