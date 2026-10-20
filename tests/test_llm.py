"""Tests for dbagent.core.llm (no real LLM needed)."""

import pytest

from dbagent.core.llm import LLMError, extract_json


def test_plain_json_is_parsed():
    assert extract_json('{"answer": 4}') == {"answer": 4}


def test_json_inside_markdown_fence_is_parsed():
    text = 'Here you go:\n```json\n{"answer": 4}\n```\nHope this helps!'

    assert extract_json(text) == {"answer": 4}


def test_nested_json_is_parsed():
    assert extract_json('{"fix": {"sql": "CREATE INDEX ..."}}') == {"fix": {"sql": "CREATE INDEX ..."}}


@pytest.mark.parametrize(
    "bad_text",
    [
        "Sorry, I cannot help with that.",   # no JSON at all
        '{"answer": 4',                      # cut off
        "{answer: 4}",                       # keys without quotes
    ],
)
def test_unusable_answers_raise_llm_error(bad_text):
    with pytest.raises(LLMError):
        extract_json(bad_text)