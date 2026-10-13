import json
import os
import urllib.error
import urllib.request

from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / "apps" / "api" / ".env")
load_dotenv(ROOT / ".env", override=True)
load_dotenv()

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


class LLMError(Exception):
    pass


def complete_json(system: str, user: str) -> dict:
    api_key = (os.environ.get("GROQ_API_KEY") or "").strip()
    if not api_key:
        raise LLMError("GROQ_API_KEY is not set")
    model = os.environ.get("GROQ_MODEL_B") or "openai/gpt-oss-120b"
    payload = json.dumps(
        {
            "model": model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
    ).encode()
    req = urllib.request.Request(
        GROQ_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raise LLMError(exc.read().decode() or str(exc)) from exc
    except urllib.error.URLError as exc:
        raise LLMError(str(exc.reason)) from exc
    content = body.get("choices", [{}])[0].get("message", {}).get("content") or "{}"
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise LLMError("model did not return JSON") from exc
