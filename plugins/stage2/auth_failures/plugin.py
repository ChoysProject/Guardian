from __future__ import annotations

import re
from collections import defaultdict

FAILED_RE = re.compile(
    r"Failed password for (invalid user )?(?P<user>\S+) from (?P<ip>\S+)",
    re.IGNORECASE,
)
INVALID_RE = re.compile(r"Invalid user (?P<user>\S+) from (?P<ip>\S+)", re.IGNORECASE)
AUTH_FAIL_RE = re.compile(r"authentication failure|auth fail", re.IGNORECASE)


def analyze(ctx) -> list[dict]:
    min_count = int((ctx.config or {}).get("min_count", 3))
    by_sig: dict[str, dict] = defaultdict(
        lambda: {"count": 0, "sample_lines": [], "host": ctx.host, "occurred_at": None}
    )
    for event in ctx.events:
        signature = _signature(event)
        if not signature:
            continue
        bucket = by_sig[signature]
        bucket["count"] += 1
        if len(bucket["sample_lines"]) < 5:
            bucket["sample_lines"].append(event.raw)
        bucket["host"] = event.host or ctx.host
        if event.occurred_at and (
            bucket["occurred_at"] is None or event.occurred_at < bucket["occurred_at"]
        ):
            bucket["occurred_at"] = event.occurred_at

    findings = []
    total = sum(item["count"] for item in by_sig.values())
    if total >= min_count:
        samples = []
        host = ctx.host
        occurred = None
        for data in by_sig.values():
            host = data["host"] or host
            for line in data["sample_lines"]:
                if line not in samples and len(samples) < 5:
                    samples.append(line)
            if data["occurred_at"] and (occurred is None or data["occurred_at"] < occurred):
                occurred = data["occurred_at"]
        findings.append(
            {
                "severity": "error",
                "signature": "auth.failures",
                "count": total,
                "sample_lines": samples,
                "host": host,
                "occurred_at": occurred,
                "plugin": "stage2.auth_failures",
            }
        )

    for signature, data in by_sig.items():
        if data["count"] < min_count:
            continue
        findings.append(
            {
                "severity": "error",
                "signature": signature,
                "count": data["count"],
                "sample_lines": data["sample_lines"],
                "host": data["host"],
                "occurred_at": data["occurred_at"],
                "plugin": "stage2.auth_failures",
            }
        )
    return findings


def _signature(event) -> str | None:
    text = event.message or event.raw
    failed = FAILED_RE.search(text)
    if failed:
        user = failed.group("user")
        kind = "invalid_user" if failed.group(1) else "failed_password"
        return f"auth.{kind}:{user}"
    invalid = INVALID_RE.search(text)
    if invalid:
        return f"auth.invalid_user:{invalid.group('user')}"
    if AUTH_FAIL_RE.search(text):
        return "auth.generic_failure"
    return None
