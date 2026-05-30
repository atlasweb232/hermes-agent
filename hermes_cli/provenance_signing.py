"""Provenance signing primitive (HMAC-SHA256; Key Vault / Secret Manager-backed key).

Shared by Phase 3 (per-tenant corroboration signatures on global lessons) and Phase 4
(the hash-chained approval ledger). A signature lets the curator verify that a
corroboration genuinely originated from the claimed tenant and was not tampered with in
transit on the bus — so a forged corroboration cannot inflate quorum.

Key handling (CLAUDE rule: never hardcode keys, never store in .env):
  * the signing key is resolved from a *secret reference* (Key Vault / Secret Manager)
    via a pluggable provider, or from an env var for dev/test only;
  * if no key is configured the signer is DISABLED — in advisory mode (default) unsigned
    corroborations are accepted (preserves the existing enforcement-off posture); in
    strict mode they are rejected. Verification is fail-closed.

HMAC (symmetric) is the default because it is dependency-free and matches the plan
("HMAC or asymmetric"). The ``ProvenanceSigner`` interface is the seam to swap in an
asymmetric / Key Vault signer without touching call sites.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional


SIGN_ALGO = "hmac-sha256"
# Fields excluded from the signed content: volatile / signature-carrying / derived.
_SIGNATURE_EXCLUDE = ("signature", "verified", "at")


def canonical_bytes(payload: Dict[str, Any], *, exclude=_SIGNATURE_EXCLUDE) -> bytes:
    data = {k: v for k, v in (payload or {}).items() if k not in exclude}
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def sign_payload(payload: Dict[str, Any], *, key: bytes) -> str:
    return hmac.new(key, canonical_bytes(payload), hashlib.sha256).hexdigest()


def verify_payload(payload: Dict[str, Any], signature: Optional[str], *, key: bytes) -> bool:
    if not signature:
        return False
    expected = sign_payload(payload, key=key)
    return hmac.compare_digest(expected, str(signature))


def _signing_config(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    supervisor = (config or {}).get("supervisor") if isinstance((config or {}).get("supervisor"), dict) else {}
    cfg = supervisor.get("provenance_signing") if isinstance(supervisor.get("provenance_signing"), dict) else {}
    return cfg


def default_key_provider(config: Optional[Dict[str, Any]]) -> Optional[bytes]:
    """Resolve the signing key. Env (dev/test) → secret reference (prod). Never inline."""
    raw = os.environ.get("HERMES_PROVENANCE_SIGNING_KEY")
    if raw:
        return raw.encode("utf-8")
    ref = str(_signing_config(config).get("key_ref") or "").strip()
    if ref:
        try:
            # Optional prod hook — resolves "keyvault:..."/"gcp-secret:..." references.
            from hermes_cli.secret_refs import resolve_secret_ref  # type: ignore

            value = resolve_secret_ref(ref)
            if value:
                return value.encode("utf-8") if isinstance(value, str) else bytes(value)
        except Exception:
            return None
    return None


@dataclass
class ProvenanceSigner:
    """Signs/verifies provenance payloads. Disabled (key=None) ⇒ advisory unless strict."""

    key: Optional[bytes] = None
    strict: bool = False

    @classmethod
    def from_config(
        cls,
        config: Optional[Dict[str, Any]] = None,
        *,
        key_provider: Callable[[Optional[Dict[str, Any]]], Optional[bytes]] = default_key_provider,
    ) -> "ProvenanceSigner":
        cfg = _signing_config(config)
        return cls(key=key_provider(config), strict=bool(cfg.get("strict", False)))

    @property
    def enabled(self) -> bool:
        return self.key is not None

    def sign(self, payload: Dict[str, Any]) -> Optional[str]:
        return sign_payload(payload, key=self.key) if self.key is not None else None

    def verify(self, payload: Dict[str, Any], signature: Optional[str]) -> bool:
        """Fail-closed when a key is configured. When disabled: advisory (True) unless
        strict (False) — i.e. strict mode refuses to trust anything it cannot verify."""
        if self.key is None:
            return not self.strict
        return verify_payload(payload, signature, key=self.key)
