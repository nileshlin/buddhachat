"""
SES email sanity test:
- Validates AWS + SES env config
- Sends a test OTP email (same shape as app/services/email_service.py)

Usage (PowerShell):
  python scripts/test_email_service.py --recipient you@example.com
  python scripts/test_email_service.py --recipient you@example.com --code 123456
  python scripts/test_email_service.py --dry-run

Environment (.env):
  AWS_ACCESS_KEY_ID=...
  AWS_SECRET_ACCESS_KEY=...
  AWS_REGION=us-east-2
  SES_SENDER_EMAIL=noreply@yourdomain.com
  # Optional:
  SES_TEST_RECIPIENT=you@example.com
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import time
from typing import Any, Dict, Optional, Tuple

try:
    from dotenv import load_dotenv  # type: ignore
except Exception:  # pragma: no cover
    load_dotenv = None  # type: ignore

try:
    import aioboto3  # type: ignore
    from botocore.exceptions import ClientError  # type: ignore
except Exception as e:  # pragma: no cover
    aioboto3 = None  # type: ignore
    ClientError = Exception  # type: ignore
    _BOTO_IMPORT_ERROR = e
else:
    _BOTO_IMPORT_ERROR = None


def _now_ms() -> int:
    return int(time.perf_counter() * 1000)


def _env(name: str) -> Optional[str]:
    value = os.getenv(name)
    return value if value and value.strip() else None


def _try_load_dotenv() -> None:
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
        return


def _safe_str(value: Any, limit: int = 240) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _build_body_html(code: str, otp_expiration_minutes: int) -> str:
    return f"""
    <html>
    <head></head>
    <body>
      <h2>Your Login Code</h2>
      <p>Your one-time login code is: <strong>{code}</strong></p>
      <p>This code will expire in {otp_expiration_minutes} minutes.</p>
    </body>
    </html>
    """


def _build_body_text(code: str, otp_expiration_minutes: int) -> str:
    return (
        f"Your one-time login code is: {code}\n"
        f"This code will expire in {otp_expiration_minutes} minutes."
    )


async def send_test_email(
    *,
    aws_access_key_id: str,
    aws_secret_access_key: str,
    region: str,
    sender: str,
    recipient: str,
    subject: str,
    code: str,
    otp_expiration_minutes: int,
) -> Tuple[bool, str, Dict[str, Any]]:
    session = aioboto3.Session(
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
        region_name=region,
    )

    body_text = _build_body_text(code, otp_expiration_minutes)
    body_html = _build_body_html(code, otp_expiration_minutes)

    try:
        async with session.client("ses") as ses_client:
            resp = await ses_client.send_email(
                Source=sender,
                Destination={"ToAddresses": [recipient]},
                Message={
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {
                        "Text": {"Data": body_text, "Charset": "UTF-8"},
                        "Html": {"Data": body_html, "Charset": "UTF-8"},
                    },
                },
            )
        message_id = str(resp.get("MessageId") or "")
        return True, message_id, {"response": resp}
    except ClientError as e:
        msg = ""
        try:
            msg = str(e.response["Error"]["Message"])
        except Exception:
            msg = _safe_str(e)
        return False, msg, {"error": msg, "type": e.__class__.__name__}


def _default_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a test email via AWS SES.")
    parser.add_argument("--recipient", default=None, help="Recipient email address (or set SES_TEST_RECIPIENT)")
    parser.add_argument("--code", default=None, help="OTP code to send (default: random 6 digits)")
    parser.add_argument("--subject", default="Your Login Code", help="Email subject")
    parser.add_argument(
        "--otp-expiration-minutes",
        type=int,
        default=int(_env("OTP_EXPIRATION_MINUTES") or "10"),
        help="Minutes until OTP expiry (default: OTP_EXPIRATION_MINUTES or 10)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Only validate configuration; do not send")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    args = parser.parse_args()

    if aioboto3 is None:
        print(f"Missing dependency: aioboto3 ({_safe_str(_BOTO_IMPORT_ERROR)})", file=sys.stderr)
        print("Run: pip install -r requirements.txt", file=sys.stderr)
        return 1

    _try_load_dotenv()

    aws_access_key_id = _env("AWS_ACCESS_KEY_ID")
    aws_secret_access_key = _env("AWS_SECRET_ACCESS_KEY")
    region = _env("AWS_REGION") or "us-east-2"
    sender = _env("SES_SENDER_EMAIL")

    recipient = args.recipient or _env("SES_TEST_RECIPIENT") or _env("TEST_EMAIL_RECIPIENT")
    code = (args.code or _default_code()).strip()

    errors = []
    if not aws_access_key_id:
        errors.append("Missing AWS_ACCESS_KEY_ID")
    if not aws_secret_access_key:
        errors.append("Missing AWS_SECRET_ACCESS_KEY")
    if not sender:
        errors.append("Missing SES_SENDER_EMAIL")
    if not recipient:
        errors.append("Missing recipient (pass --recipient or set SES_TEST_RECIPIENT)")

    if errors:
        if args.json:
            print(json.dumps({"ok": False, "errors": errors}, indent=2))
        else:
            print("Configuration errors:", file=sys.stderr)
            for e in errors:
                print(f"- {e}", file=sys.stderr)
        return 1

    payload: Dict[str, Any] = {
        "ok": True,
        "dry_run": bool(args.dry_run),
        "region": region,
        "sender": sender,
        "recipient": recipient,
        "subject": args.subject,
        "code": code,
        "otp_expiration_minutes": args.otp_expiration_minutes,
    }

    if args.dry_run:
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print("DRY RUN OK")
            print(f"Region:    {region}")
            print(f"Sender:    {sender}")
            print(f"Recipient: {recipient}")
        return 0

    import asyncio

    start_ms = _now_ms()
    ok, detail, extra = asyncio.run(
        send_test_email(
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            region=region,
            sender=sender,
            recipient=recipient,
            subject=args.subject,
            code=code,
            otp_expiration_minutes=args.otp_expiration_minutes,
        )
    )
    latency_ms = _now_ms() - start_ms

    payload.update({"ok": ok, "latency_ms": latency_ms, "detail": detail})
    payload.update(extra)

    if args.json:
        print(json.dumps(payload, indent=2, default=str))
        return 0 if ok else 1

    if ok:
        print(f"PASS  send_email  {latency_ms}ms  MessageId={detail}")
        return 0
    print(f"FAIL  send_email  {latency_ms}ms  {detail}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

