"""Strict redaction for persisted / curated memory.

This is deliberately *stronger* than log redaction (``agent.redact``). Log
redaction masks secrets but preserves head/tail characters so operators can
still debug (e.g. ``token=sk-abc...9XYZ``). Persisted learning memory has a
different threat model: a curated lesson may be promoted to ``global`` scope and
shared *cross-tenant*, outside the originating operator's control, so it must
contain **zero** secret fragments — no preserved prefixes, no missed shapes.

``redact_for_persistence`` therefore composes two passes:

1. The canonical ``agent.redact.redact_sensitive_text`` breadth pass (URL
   userinfo/query params, JWTs, PEM private keys, DB connection strings,
   telegram tokens, auth headers) with ``force=True`` so it never depends on the
   global logging-redaction preference.
2. A strict full-erase over the union of secret shapes that used to be
   re-implemented independently across ``runtime_lesson_capture``,
   ``runtime_features``, ``task_memory_profiles``, ``runtime_benchmark`` and
   ``runtime_e2e`` (each had its own ``_SECRET_PATTERNS``). Matches are replaced
   wholesale with ``[REDACTED]`` (no head/tail kept).

The strict pass runs *last* and is authoritative: it erases any high-risk
prefix (``sk-``, ``ghp_`` …) that the canonical pass would otherwise only mask
(``sk-abc...9XYZ``), so ``contains_secret`` is False on the result.
"""

from __future__ import annotations

import re
from typing import Any

REDACTION_PLACEHOLDER = "[REDACTED]"

# Union of the secret shapes previously duplicated across the runtime/learning
# modules, hardened for full-erase persistence redaction. Ordered cheapest-gate
# first is unnecessary here (memory redaction is not on the hot logging path).
_STRICT_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Provider key prefixes: sk-, ghp_/gho_, xoxb-/xoxp-/...  (full token erased)
    re.compile(r"\b(?:sk|ghp|gho|ghu|ghs|xox[baprs])[-_][A-Za-z0-9._\-]{8,}\b", re.IGNORECASE),
    # AWS access key ids
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    # key/secret/token/password assignments: api_key=..., password: '...'
    re.compile(
        r"(?i)\b(?:api[_-]?key|access[_-]?key|secret[_-]?key|client[_-]?secret"
        r"|token|secret|password|passwd|pwd)\s*[:=]\s*['\"]?[^'\"\s,;]+"
    ),
    # Authorization: Bearer <token>
    re.compile(r"(?i)\bauthorization\s*:\s*bearer\s+\S+"),
    # id:token style (telegram bot tokens and similar long opaque pairs)
    re.compile(r"\b[A-Za-z0-9_]{6,}:[A-Za-z0-9_\-]{20,}\b"),
)


def _strict_erase(text: str) -> str:
    for pattern in _STRICT_SECRET_PATTERNS:
        text = pattern.sub(REDACTION_PLACEHOLDER, text)
    return text


def contains_secret(value: Any) -> bool:
    """Return True if any strict secret shape is present in ``value``.

    Use for detection/gating (e.g. ``secret_safe`` assertions) rather than
    substitution. Does not run the canonical breadth pass — it is a fast,
    conservative pre-check.
    """
    text = str(value or "")
    return any(pattern.search(text) for pattern in _STRICT_SECRET_PATTERNS)


def redact_for_persistence(value: Any, *, max_chars: int | None = None) -> str:
    """Strict-redact ``value`` for memory persistence, optionally length-bounded.

    Redaction and length-bounding are intentionally separate concerns: pass
    ``max_chars`` only when the caller needs a bounded field. Truncation uses an
    ellipsis suffix and never splits inside a redaction placeholder boundary in
    a way that leaks (placeholders are short and erased before truncation).
    """
    text = str(value or "")
    try:  # canonical breadth pass first; never let a failure return raw text
        from agent.redact import redact_sensitive_text as _canonical_redact

        text = _canonical_redact(text, force=True)
    except Exception:
        pass
    # Strict full-erase runs last and is authoritative.
    text = _strict_erase(text).strip()
    if max_chars is not None and len(text) > max_chars:
        return text[: max(0, max_chars - 3)].rstrip() + "..."
    return text
