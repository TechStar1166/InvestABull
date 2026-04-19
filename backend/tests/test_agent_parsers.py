"""Unit tests for app.agents.parsers."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.agents.parsers import (
    AgentOutputError,
    _largest_json_block,
    _strip_fences,
    parse_agent_output,
)


class _Toy(BaseModel):
    ticker: str
    value: float


def test_strip_fences_unwraps_json_block():
    raw = "```json\n{\"ticker\": \"AAPL\", \"value\": 1.0}\n```"
    assert _strip_fences(raw).startswith("{")
    assert _strip_fences(raw).endswith("}")


def test_strip_fences_ignores_plain_json():
    raw = '{"ticker": "AAPL"}'
    assert _strip_fences(raw) == raw


def test_largest_json_block_picks_outer():
    raw = 'preamble {"a": 1} midamble {"ticker": "AAPL", "value": 2.5} trailing'
    block = _largest_json_block(raw)
    assert block == '{"ticker": "AAPL", "value": 2.5}'


def test_parse_agent_output_happy_path():
    raw = '{"ticker": "AAPL", "value": 1.5}'
    out = parse_agent_output(raw, _Toy)
    assert out.ticker == "AAPL"
    assert out.value == 1.5


def test_parse_agent_output_with_fences_and_preamble():
    raw = (
        "Here is your JSON:\n"
        "```json\n"
        '{"ticker": "MSFT", "value": 2.25}\n'
        "```\n"
        "Thanks!"
    )
    out = parse_agent_output(raw, _Toy)
    assert out.ticker == "MSFT"
    assert out.value == 2.25


def test_parse_agent_output_recovers_from_embedded_block():
    raw = 'Noise before {"ticker": "GOOG", "value": 3.14} noise after.'
    out = parse_agent_output(raw, _Toy)
    assert out.ticker == "GOOG"


def test_parse_agent_output_raises_on_invalid():
    with pytest.raises(AgentOutputError):
        parse_agent_output("", _Toy)
    with pytest.raises(AgentOutputError):
        parse_agent_output('{"ticker": "AAPL"}', _Toy)  # missing field
    with pytest.raises(AgentOutputError):
        parse_agent_output("not even close to json", _Toy)
