"""The one place this pipeline calls Claude.

Everything deterministic — schedule, final scores/status, season
differentials, moneylines from ESPN — is handled in plain code elsewhere.
This module is just the mechanism: it takes a fully-built system/user prompt
from a sport's model module (lib/nfl_model.py, lib/mlb_model.py, etc.) and
returns the parsed JSON Claude's web-search research produced. All scoring
math, tiering, and thresholds live in the model modules, applied afterwards
in plain code — Claude supplies facts and per-category leanings, not picks
or confidence labels.
"""
import json
import re

import anthropic

MODEL = "claude-opus-5"


def _extract_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        text = re.sub(r"\n```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object found in Claude's response:\n" + text[:2000])
    return json.loads(text[start:end + 1])


def research_slate(system_prompt, user_prompt, max_uses=40):
    """Call Claude once (with the web_search server tool) to research a
    slate. Returns the parsed JSON dict the caller's prompt asked for."""
    client = anthropic.Anthropic()

    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=32000,
        system=system_prompt,
        thinking={"type": "adaptive"},
        output_config={"effort": "high"},
        tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": max_uses}],
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": user_prompt}],
    ) as stream:
        response = stream.get_final_message()

    if getattr(response, "stop_reason", None) == "refusal":
        raise RuntimeError(f"Claude refused the research request: {response.stop_details}")

    text_parts = [block.text for block in response.content if getattr(block, "type", None) == "text"]
    return _extract_json("\n".join(text_parts))
