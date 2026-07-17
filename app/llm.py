"""LLM-backed QA test-case generation with structured-output validation.

Provider is pluggable via env vars. Default provider is "mock", a deterministic
generator so the whole flow runs end-to-end with no API key. Set
CT200_LLM_PROVIDER=groq (OpenAI-compatible) plus CT200_LLM_API_KEY to hit a
real model.

The contract with the model is a strict JSON schema. We do NOT trust the model
to obey it: every response is parsed and validated with Pydantic, and on failure
we retry a bounded number of times with an error-repair instruction. If it still
fails, the generation is stored with status="failed" rather than silently
returning garbage.
"""
from __future__ import annotations

import json
import os
import re

from pydantic import BaseModel, Field, ValidationError, field_validator


class TestCase(BaseModel):
    title: str
    steps: list[str] = Field(min_length=1)
    expected_result: str
    source_logical_ids: list[str] = []

    @field_validator("title", "expected_result")
    @classmethod
    def _nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must be non-empty")
        return v.strip()


class TestCaseSet(BaseModel):
    test_cases: list[TestCase] = Field(min_length=3, max_length=5)


SYSTEM_PROMPT = (
    "You are a senior QA engineer writing test cases for a medical device. "
    "You will be given one or more numbered sections of a device manual. "
    "Produce between 3 and 5 concrete, executable QA test cases derived ONLY "
    "from the provided text. Each test case must be specific enough that another "
    "engineer could run it. Reply with ONLY a JSON object, no prose, matching:\n"
    '{"test_cases": [{"title": str, "steps": [str, ...], '
    '"expected_result": str, "source_logical_ids": [str, ...]}]}'
)


def build_user_prompt(sections: list[dict]) -> str:
    blocks = []
    for s in sections:
        blocks.append(
            f"[section logical_id={s['logical_id']}]\n"
            f"# {s['heading']}\n{s['body']}"
        )
    return "Sections:\n\n" + "\n\n".join(blocks)


def _extract_json(text: str) -> dict:
    """Real models wrap JSON in prose or ```json fences. Pull out the first
    balanced object. Raises ValueError if none is found."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else text
    start = candidate.find("{")
    if start == -1:
        raise ValueError("no JSON object found in model output")
    depth = 0
    for i in range(start, len(candidate)):
        if candidate[i] == "{":
            depth += 1
        elif candidate[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(candidate[start : i + 1])
    raise ValueError("unbalanced JSON object in model output")


# --- providers -------------------------------------------------------------

def _mock_complete(system: str, user: str) -> str:
    """Deterministic stand-in. Emits valid, section-derived test cases so the
    end-to-end flow (including staleness) is demonstrable without a key."""
    ids = re.findall(r"logical_id=(\S+)\]", user)
    ids = ids or ["unknown"]
    numbers = re.findall(r"\b\d{2,3}\b", user)
    threshold = numbers[0] if numbers else "300"
    cases = [
        {
            "title": "Verify overpressure protection triggers error and auto-deflate",
            "steps": [
                f"Simulate cuff pressure exceeding {threshold} mmHg.",
                "Observe the device display and cuff behaviour.",
            ],
            "expected_result": (
                f"Device displays error E3 and auto-deflates within 2 seconds "
                f"once pressure exceeds {threshold} mmHg."
            ),
            "source_logical_ids": ids,
        },
        {
            "title": "Verify loose-cuff detection",
            "steps": [
                "Start a measurement with the cuff not attached to an arm.",
                "Observe the display.",
            ],
            "expected_result": "Device displays error E1 (loose cuff).",
            "source_logical_ids": ids,
        },
        {
            "title": "Verify measurement timeout",
            "steps": [
                "Start a measurement and prevent a valid reading for 120 seconds.",
            ],
            "expected_result": "Device displays error E5 after a 120-second timeout.",
            "source_logical_ids": ids,
        },
    ]
    return json.dumps({"test_cases": cases})


def _groq_complete(system: str, user: str) -> str:
    import httpx

    api_key = os.environ["CT200_LLM_API_KEY"]
    model = os.environ.get("CT200_LLM_MODEL", "llama-3.1-8b-instant")
    base = os.environ.get("CT200_LLM_BASE_URL", "https://api.groq.com/openai/v1")
    resp = httpx.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _complete(system: str, user: str) -> str:
    provider = os.environ.get("CT200_LLM_PROVIDER", "mock").lower()
    if provider == "mock":
        return _mock_complete(system, user)
    if provider == "groq":
        return _groq_complete(system, user)
    raise ValueError(f"unknown LLM provider: {provider}")


class GenerationError(Exception):
    def __init__(self, message: str, attempts: list[str]):
        super().__init__(message)
        self.attempts = attempts


def generate_test_cases(sections: list[dict], max_attempts: int = 3) -> TestCaseSet:
    """Call the LLM and return a validated TestCaseSet, retrying on malformed
    output. Raises GenerationError with the raw attempts on total failure."""
    user = build_user_prompt(sections)
    attempts: list[str] = []
    last_err = ""
    for attempt in range(1, max_attempts + 1):
        system = SYSTEM_PROMPT
        if attempt > 1:
            system += (
                f"\n\nYour previous reply failed validation: {last_err}. "
                "Return ONLY the corrected JSON object."
            )
        raw = _complete(system, user)
        attempts.append(raw)
        try:
            data = _extract_json(raw)
            return TestCaseSet.model_validate(data)
        except (ValueError, ValidationError, json.JSONDecodeError) as e:
            last_err = str(e)[:300]
    raise GenerationError(
        f"LLM output failed validation after {max_attempts} attempts: {last_err}",
        attempts,
    )
