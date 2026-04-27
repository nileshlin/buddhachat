"""
Lightweight OpenAI sanity test:
- Validates OPENAI_API_KEY works
- Confirms OPENAI_MODEL is accessible
- Runs a few small "quality" probes (instruction following + JSON + meditation-structured output)

Usage (PowerShell):
  python scripts/test_openai.py
  python scripts/test_openai.py --model gpt-4o-mini
  python scripts/test_openai.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

try:
    from dotenv import load_dotenv  # type: ignore
except Exception:  # pragma: no cover
    load_dotenv = None  # type: ignore

try:
    from pydantic import BaseModel  # type: ignore
except Exception:  # pragma: no cover
    BaseModel = object  # type: ignore

try:
    from openai import OpenAI  # type: ignore
    from openai import APIError, AuthenticationError, NotFoundError, RateLimitError  # type: ignore
except Exception as e:  # pragma: no cover
    OpenAI = None  # type: ignore
    APIError = AuthenticationError = NotFoundError = RateLimitError = Exception  # type: ignore
    _OPENAI_IMPORT_ERROR = e
else:
    _OPENAI_IMPORT_ERROR = None


class ScriptGenerationOutput(BaseModel):
    name: str
    script: List[str]
    music_tags: List[str]


@dataclass
class CheckResult:
    name: str
    ok: bool
    latency_ms: Optional[int] = None
    detail: str = ""
    extra: Optional[Dict[str, Any]] = None


def _now_ms() -> int:
    return int(time.perf_counter() * 1000)


def _env(name: str) -> Optional[str]:
    value = os.getenv(name)
    return value if value and value.strip() else None


def _run_timed(fn) -> Tuple[Any, int]:
    start = _now_ms()
    out = fn()
    end = _now_ms()
    return out, end - start


def _safe_str(value: Any, limit: int = 240) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _print_human(results: List[CheckResult]) -> None:
    width = max(len(r.name) for r in results) if results else 10
    for r in results:
        status = "PASS" if r.ok else "FAIL"
        latency = f"{r.latency_ms}ms" if r.latency_ms is not None else "-"
        detail = f" - {r.detail}" if r.detail else ""
        print(f"{status:4}  {r.name:<{width}}  {latency:>7}{detail}")


def _exit_code(results: List[CheckResult]) -> int:
    return 0 if all(r.ok for r in results) else 1


def _build_client(api_key: str) -> OpenAI:
    base_url = _env("OPENAI_BASE_URL")
    if base_url:
        return OpenAI(api_key=api_key, base_url=base_url)
    return OpenAI(api_key=api_key)


def _try_load_dotenv() -> None:
    """
    Best-effort .env loader:
    - Prefer python-dotenv if installed
    - Fallback to a minimal parser for KEY=VALUE lines
    """
    if callable(load_dotenv):
        load_dotenv()
        return

    env_path = os.path.join(os.getcwd(), ".env")
    if not os.path.exists(env_path):
        return

    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip("'").strip('"')
                if key and key not in os.environ:
                    os.environ[key] = value
    except Exception:
        # If .env parsing fails, keep going; the user can export env vars directly.
        return


def check_auth_and_model(client: OpenAI, model: str) -> CheckResult:
    def _call():
        # Fast path: directly retrieve the model.
        return client.models.retrieve(model)

    try:
        _, latency_ms = _run_timed(_call)
        return CheckResult(
            name="auth_and_model",
            ok=True,
            latency_ms=latency_ms,
            detail=f"Model '{model}' is accessible",
        )
    except AuthenticationError as e:
        return CheckResult(
            name="auth_and_model",
            ok=False,
            detail=f"Authentication failed: {_safe_str(e)}",
        )
    except NotFoundError as e:
        return CheckResult(
            name="auth_and_model",
            ok=False,
            detail=f"Model not found / not permitted: '{model}'. {_safe_str(e)}",
        )
    except (RateLimitError, APIError) as e:
        return CheckResult(
            name="auth_and_model",
            ok=False,
            detail=f"API error: {_safe_str(e)}",
        )
    except Exception as e:
        return CheckResult(name="auth_and_model", ok=False, detail=f"Unexpected error: {_safe_str(e)}")


def check_exact_instruction(client: OpenAI, model: str) -> CheckResult:
    prompt = "Reply with exactly the two characters: OK"

    def _call():
        return client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=8,
        )

    try:
        resp, latency_ms = _run_timed(_call)
        text = (resp.choices[0].message.content or "").strip()
        ok = text == "OK"
        return CheckResult(
            name="probe_exact",
            ok=ok,
            latency_ms=latency_ms,
            detail=f"Got '{_safe_str(text, 40)}'",
            extra={"usage": getattr(resp, "usage", None)},
        )
    except Exception as e:
        return CheckResult(name="probe_exact", ok=False, detail=_safe_str(e))


def check_json_following(client: OpenAI, model: str) -> CheckResult:
    prompt = (
        "Return ONLY valid JSON with keys: ok (boolean), answer (string). "
        "Set ok=true and answer='pong'."
    )

    def _call():
        return client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=30,
        )

    try:
        resp, latency_ms = _run_timed(_call)
        raw = (resp.choices[0].message.content or "").strip()
        ok = False
        detail = ""
        try:
            parsed = json.loads(raw)
            ok = parsed.get("ok") is True and parsed.get("answer") == "pong"
            detail = f"Parsed ok={parsed.get('ok')} answer={_safe_str(parsed.get('answer'), 40)}"
        except Exception as je:
            detail = f"Invalid JSON: {_safe_str(je)}; raw={_safe_str(raw, 120)}"
        return CheckResult(
            name="probe_json",
            ok=ok,
            latency_ms=latency_ms,
            detail=detail,
            extra={"raw": raw, "usage": getattr(resp, "usage", None)},
        )
    except Exception as e:
        return CheckResult(name="probe_json", ok=False, detail=_safe_str(e))


def check_structured_meditation_parse(client: OpenAI, model: str) -> CheckResult:
    prompt = """
Generate a personalized meditation script for: "I feel stressed and want to relax".

You must output exactly 5 blocks of spoken text.
Block 1: Introduction and settling down.
Block 2: Deepening focus and breath work.
Block 3: Core theme exploration.
Block 4: Integration and silence prep.
Block 5: Gentle awakening and conclusion.

Also provide a short 'name' (title).
Finally, provide exactly 3-4 'music_tags' describing the sonic environment.
""".strip()

    def _call():
        # Prefer the project's structured output approach when available.
        return client.beta.chat.completions.parse(
            model=model,
            messages=[{"role": "system", "content": prompt}],
            response_format=ScriptGenerationOutput,
        )

    try:
        resp, latency_ms = _run_timed(_call)
        parsed = resp.choices[0].message.parsed
        script = list(parsed.script or [])
        tags = list(parsed.music_tags or [])

        # Normalize the exact-5 requirement (same as app/service behavior)
        if len(script) < 5:
            script.extend([""] * (5 - len(script)))
        elif len(script) > 5:
            script = script[:5]

        # Minimal "quality" heuristics (not a benchmark)
        nonempty_blocks = sum(1 for b in script if (b or "").strip())
        avg_len = int(sum(len((b or "").strip()) for b in script) / 5) if script else 0
        ok = (
            bool((parsed.name or "").strip())
            and nonempty_blocks >= 4
            and 3 <= len(tags) <= 4
            and avg_len >= 40
        )
        detail = f"title={_safe_str(parsed.name, 50)} blocks_nonempty={nonempty_blocks}/5 tags={len(tags)} avg_len={avg_len}"
        return CheckResult(
            name="probe_meditation_parse",
            ok=ok,
            latency_ms=latency_ms,
            detail=detail,
            extra={"title": parsed.name, "music_tags": tags, "usage": getattr(resp, "usage", None)},
        )
    except AttributeError:
        return CheckResult(
            name="probe_meditation_parse",
            ok=False,
            detail="openai SDK missing .beta.chat.completions.parse (upgrade openai package)",
        )
    except Exception as e:
        return CheckResult(name="probe_meditation_parse", ok=False, detail=_safe_str(e))


def main() -> int:
    parser = argparse.ArgumentParser(description="Test OPENAI_API_KEY and basic model quality probes.")
    parser.add_argument("--model", help="Override OPENAI_MODEL from .env", default=None)
    parser.add_argument("--skip-parse", action="store_true", help="Skip the structured parse probe")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON results")
    args = parser.parse_args()

    if OpenAI is None:
        print(f"Missing dependency: openai ({_safe_str(_OPENAI_IMPORT_ERROR)})", file=sys.stderr)
        print("Run: pip install -r requirements.txt", file=sys.stderr)
        return 1

    _try_load_dotenv()

    api_key = _env("OPENAI_API_KEY")
    model = args.model or _env("OPENAI_MODEL") or "gpt-4o-mini"

    if not api_key:
        print("Missing OPENAI_API_KEY in environment/.env", file=sys.stderr)
        return 1

    client = _build_client(api_key)

    results: List[CheckResult] = []
    results.append(check_auth_and_model(client, model))

    # Only run probes if auth/model passed (prevents noisy cascades).
    if results[-1].ok:
        results.append(check_exact_instruction(client, model))
        results.append(check_json_following(client, model))
        if not args.skip_parse and BaseModel is not object:
            results.append(check_structured_meditation_parse(client, model))
        elif not args.skip_parse and BaseModel is object:
            results.append(
                CheckResult(
                    name="probe_meditation_parse",
                    ok=False,
                    detail="Missing dependency: pydantic (install requirements to enable structured parse probe)",
                )
            )

    if args.json:
        payload = {
            "model": model,
            "base_url": _env("OPENAI_BASE_URL"),
            "results": [
                {
                    "name": r.name,
                    "ok": r.ok,
                    "latency_ms": r.latency_ms,
                    "detail": r.detail,
                    "extra": r.extra,
                }
                for r in results
            ],
        }
        print(json.dumps(payload, indent=2, default=str))
    else:
        _print_human(results)

    return _exit_code(results)


if __name__ == "__main__":
    raise SystemExit(main())
