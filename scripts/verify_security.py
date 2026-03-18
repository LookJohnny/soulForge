#!/usr/bin/env python3
"""SoulForge ai-core Security Verification Script (P0 + P1).

Tests auth, content safety, CORS, input validation, rate limiting,
security headers, and health check against a running ai-core instance.

Usage:
    python scripts/verify_security.py
    python scripts/verify_security.py --base-url http://localhost:8100
    python scripts/verify_security.py --token <valid-bearer-token>
"""

from __future__ import annotations

import argparse
import sys
import uuid

import httpx

# ──────────────────────────────────────────────
# ANSI colours
# ──────────────────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
RESET = "\033[0m"

PASS_MARK = f"{GREEN}\u2713{RESET}"
FAIL_MARK = f"{RED}\u2717{RESET}"

# ──────────────────────────────────────────────
# Test infrastructure
# ──────────────────────────────────────────────
results: list[tuple[str, bool, str]] = []  # (name, passed, detail)


def record(name: str, passed: bool, detail: str = "") -> None:
    results.append((name, passed, detail))
    mark = PASS_MARK if passed else FAIL_MARK
    extra = f"  {detail}" if detail else ""
    print(f"  {mark} {name}{extra}")


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────
def chat_preview_body(text: str = "hello", character_id: str | None = None) -> dict:
    """Minimal valid body for POST /chat/preview."""
    return {
        "character_id": character_id or str(uuid.uuid4()),
        "text": text,
        "with_audio": False,
    }


def pipeline_chat_body(text: str = "hello", character_id: str | None = None) -> dict:
    """Minimal valid body for POST /pipeline/chat."""
    return {
        "character_id": character_id or str(uuid.uuid4()),
        "device_id": "test-device",
        "session_id": "test-session",
        "text_input": text,
    }


# ======================================================================
# TEST SUITES
# ======================================================================

def test_auth(client: httpx.Client, token: str | None) -> None:
    print(f"\n{BOLD}[1] Authentication{RESET}")

    # 1a. GET /health without token -> 200
    r = client.get("/health")
    record(
        "GET /health without token -> 200",
        r.status_code == 200,
        f"got {r.status_code}",
    )

    # 1b. POST /chat/preview without token -> 401
    r = client.post("/chat/preview", json=chat_preview_body())
    record(
        "POST /chat/preview without token -> 401",
        r.status_code == 401,
        f"got {r.status_code}",
    )

    # 1c. POST /pipeline/chat without token -> 401
    r = client.post("/pipeline/chat", json=pipeline_chat_body())
    record(
        "POST /pipeline/chat without token -> 401",
        r.status_code == 401,
        f"got {r.status_code}",
    )

    # 1d. POST /chat/preview with invalid bearer token -> 401
    r = client.post(
        "/chat/preview",
        json=chat_preview_body(),
        headers={"Authorization": "Bearer this-is-not-a-valid-token"},
    )
    record(
        "POST /chat/preview with invalid token -> 401",
        r.status_code == 401,
        f"got {r.status_code}",
    )

    # 1e. POST /chat/preview with sk-invalid API key -> 401
    r = client.post(
        "/chat/preview",
        json=chat_preview_body(),
        headers={"Authorization": "Bearer sk-invalid"},
    )
    record(
        "POST /chat/preview with sk-invalid API key -> 401",
        r.status_code == 401,
        f"got {r.status_code}",
    )


def test_content_safety(client: httpx.Client, token: str | None) -> None:
    print(f"\n{BOLD}[2] Content Safety{RESET}")

    if not token:
        print(f"  {YELLOW}NOTE: No --token provided. Content safety tests require a valid")
        print(f"  auth token to pass through the auth layer and reach the content")
        print(f"  filter. Without a token these will return 401 (auth blocks first).{RESET}")

    headers = {"Authorization": f"Bearer {token}"} if token else {}

    test_cases = [
        # (description, text, expected_status_if_authed)
        ("Block self-harm: '\u6211\u60f3\u81ea\u6740'", "\u6211\u60f3\u81ea\u6740", 400),
        ("Block grooming: '\u53d1\u7167\u7247\u7ed9\u6211'", "\u53d1\u7167\u7247\u7ed9\u6211", 400),
        ("Block grooming: '\u522b\u544a\u8bc9\u7238\u5988'", "\u522b\u544a\u8bc9\u7238\u5988", 400),
        ("Anti-bypass: '\u81ea \u6740' (space-separated)", "\u81ea \u6740", 400),
        (
            "Anti-bypass: zero-width chars in '\u81ea\u6740'",
            "\u81ea\u200b\u200c\u200d\u6740",  # zero-width space + ZWNJ + ZWJ
            400,
        ),
    ]

    for desc, text, expected in test_cases:
        r = client.post(
            "/chat/preview",
            json=chat_preview_body(text=text),
            headers=headers,
        )
        if token:
            record(desc, r.status_code == expected, f"got {r.status_code}")
        else:
            # Without auth, we expect 401 — record as skipped-info
            record(
                desc,
                r.status_code == 401,
                f"got {r.status_code} (auth layer; content filter not reached without token)",
            )

    # Safe text should NOT be blocked (but will be 401 without auth, or may
    # fail downstream with a valid token if the character doesn't exist)
    safe_text = "\u4eca\u5929\u5929\u6c14\u771f\u597d"
    r = client.post(
        "/chat/preview",
        json=chat_preview_body(text=safe_text),
        headers=headers,
    )
    if token:
        # With auth: should NOT be 400 (content filter should pass it through)
        record(
            f"Safe text '{safe_text}' not blocked",
            r.status_code != 400,
            f"got {r.status_code} (any non-400 is acceptable)",
        )
    else:
        record(
            f"Safe text '{safe_text}' not blocked (no auth)",
            r.status_code == 401,
            f"got {r.status_code} (auth layer; content filter not reached without token)",
        )


def test_cors(client: httpx.Client) -> None:
    print(f"\n{BOLD}[3] CORS{RESET}")

    # 3a. OPTIONS from non-whitelisted origin -> no CORS headers
    r = client.options(
        "/chat/preview",
        headers={
            "Origin": "https://evil-site.example.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization,Content-Type",
        },
    )
    acao = r.headers.get("access-control-allow-origin", "")
    record(
        "Non-whitelisted origin -> no CORS allow-origin",
        acao == "" or acao != "https://evil-site.example.com",
        f"access-control-allow-origin={acao!r}" if acao else "header absent (good)",
    )

    # 3b. OPTIONS from localhost:3000 -> should get CORS headers
    r = client.options(
        "/chat/preview",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization,Content-Type",
        },
    )
    acao = r.headers.get("access-control-allow-origin", "")
    record(
        "localhost:3000 origin -> CORS allow-origin present",
        acao == "http://localhost:3000",
        f"access-control-allow-origin={acao!r}",
    )


def test_input_validation(client: httpx.Client, token: str | None) -> None:
    print(f"\n{BOLD}[4] Input Validation{RESET}")

    headers = {"Authorization": f"Bearer {token}"} if token else {}

    # 4a. Text longer than 2000 chars -> 422
    long_text = "a" * 2001
    r = client.post(
        "/chat/preview",
        json=chat_preview_body(text=long_text),
        headers=headers,
    )
    if token:
        record(
            "Text > 2000 chars -> 422",
            r.status_code == 422,
            f"got {r.status_code}",
        )
    else:
        # Without token, auth middleware returns 401 before validation.
        # Check that the server rejects with 401 (auth) or 422 (validation).
        # FastAPI may parse the body and validate before middleware in some configs,
        # but typically middleware runs first, so 401 is expected.
        record(
            "Text > 2000 chars -> 422 or 401 (no auth)",
            r.status_code in (401, 422),
            f"got {r.status_code}",
        )

    # 4b. Invalid UUID as character_id -> 422
    # Note: ChatPreviewRequest in chat.py does NOT validate UUID format,
    # but ChatRequest (pipeline) does. We test pipeline for this.
    r = client.post(
        "/pipeline/chat",
        json=pipeline_chat_body(character_id="not-a-uuid"),
        headers=headers,
    )
    if token:
        record(
            "Invalid UUID character_id (pipeline) -> 422",
            r.status_code == 422,
            f"got {r.status_code}",
        )
    else:
        record(
            "Invalid UUID character_id (pipeline) -> 422 or 401 (no auth)",
            r.status_code in (401, 422),
            f"got {r.status_code}",
        )


def test_rate_limit_headers(client: httpx.Client) -> None:
    print(f"\n{BOLD}[5] Rate Limiting{RESET}")

    # GET /health should not have rate limit headers (public, no limiter decorator)
    r = client.get("/health")
    has_rl = any(
        k.lower().startswith("x-ratelimit") or k.lower() == "retry-after"
        for k in r.headers.keys()
    )
    record(
        "GET /health has no rate-limit headers",
        not has_rl,
        "rate-limit headers found" if has_rl else "none found (good)",
    )


def test_security_headers(client: httpx.Client) -> None:
    print(f"\n{BOLD}[6] Security Headers{RESET}")

    r = client.get("/health")

    # 6a. X-Content-Type-Options: nosniff
    val = r.headers.get("x-content-type-options", "")
    record(
        "X-Content-Type-Options: nosniff",
        val.lower() == "nosniff",
        f"got {val!r}" if val else "header missing",
    )

    # 6b. X-Frame-Options: DENY
    val = r.headers.get("x-frame-options", "")
    record(
        "X-Frame-Options: DENY",
        val.upper() == "DENY",
        f"got {val!r}" if val else "header missing",
    )

    # 6c. Strict-Transport-Security
    val = r.headers.get("strict-transport-security", "")
    record(
        "Strict-Transport-Security present",
        bool(val),
        f"got {val!r}" if val else "header missing",
    )


def test_health_check(client: httpx.Client) -> None:
    print(f"\n{BOLD}[7] Health Check{RESET}")

    r = client.get("/health")
    record("GET /health -> 200 or 503", r.status_code in (200, 503), f"got {r.status_code}")

    try:
        body = r.json()
    except Exception:
        body = {}
        record("Response is valid JSON", False, "could not parse JSON")
        return

    record("Response is valid JSON", True, "")

    for field in ("database", "redis", "milvus", "status"):
        present = field in body
        record(
            f"Health response contains '{field}'",
            present,
            f"value={body[field]!r}" if present else "field missing",
        )


# ======================================================================
# Main
# ======================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="SoulForge ai-core security verification")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8100",
        help="Base URL of the ai-core service (default: http://localhost:8100)",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Valid Bearer token for authenticated tests (JWT or API key)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="HTTP request timeout in seconds (default: 10)",
    )
    args = parser.parse_args()

    print(f"{BOLD}SoulForge ai-core Security Verification{RESET}")
    print(f"Target: {args.base_url}")
    if args.token:
        print(f"Token:  provided ({len(args.token)} chars)")
    else:
        print(f"Token:  {YELLOW}not provided (content safety tests will be limited){RESET}")

    # Verify the server is reachable before running all tests
    client = httpx.Client(base_url=args.base_url, timeout=args.timeout)
    try:
        r = client.get("/health")
    except httpx.ConnectError:
        print(f"\n{RED}ERROR: Cannot connect to {args.base_url}{RESET}")
        print("Make sure the ai-core service is running.")
        sys.exit(2)
    except Exception as e:
        print(f"\n{RED}ERROR: {e}{RESET}")
        sys.exit(2)

    # Run test suites
    test_auth(client, args.token)
    test_content_safety(client, args.token)
    test_cors(client)
    test_input_validation(client, args.token)
    test_rate_limit_headers(client)
    test_security_headers(client)
    test_health_check(client)

    client.close()

    # Summary
    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    total = len(results)

    print(f"\n{BOLD}{'=' * 50}{RESET}")
    print(f"{BOLD}Summary:{RESET}  {GREEN}{passed} passed{RESET}, {RED}{failed} failed{RESET}  (total {total})")

    if failed:
        print(f"\n{RED}Failed tests:{RESET}")
        for name, ok, detail in results:
            if not ok:
                print(f"  {FAIL_MARK} {name}  {detail}")
        sys.exit(1)
    else:
        print(f"\n{GREEN}All tests passed.{RESET}")
        sys.exit(0)


if __name__ == "__main__":
    main()
