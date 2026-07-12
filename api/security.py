"""Simple API-key authentication for FastAPI.

Header: ``X-API-Key: <key>``

Enable with ``STARSHIELD_API_KEY_REQUIRED=1`` and configure keys via
``STARSHIELD_API_KEYS`` (comma-separated) and/or ``data/api_keys.txt``.
"""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Optional, Set

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from config import API_KEY_REQUIRED, API_KEYS, API_KEYS_FILE, DATA_DIR

API_KEY_HEADER_NAME = "X-API-Key"

_api_key_header = APIKeyHeader(
    name=API_KEY_HEADER_NAME,
    auto_error=False,
    description="API key for protected endpoints (passes, watchlist scan, history)",
)


def reload_api_keys() -> Set[str]:
    """Re-read keys from env + file (for CLI generate without process restart)."""
    from config import _parse_api_keys  # type: ignore

    return set(_parse_api_keys())


def get_valid_keys() -> Set[str]:
    """Current valid API keys (env + file)."""
    keys = set(API_KEYS)
    # Always re-check file so newly written keys work without restart
    try:
        if API_KEYS_FILE.exists():
            for line in API_KEYS_FILE.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    keys.add(line)
    except OSError:
        pass
    return keys


def auth_enabled() -> bool:
    return bool(API_KEY_REQUIRED)


def verify_api_key(key: Optional[str]) -> bool:
    if not key:
        return False
    for valid in get_valid_keys():
        if secrets.compare_digest(key, valid):
            return True
    return False


async def require_api_key(
    api_key: Optional[str] = Security(_api_key_header),
) -> Optional[str]:
    """FastAPI dependency: require a valid X-API-Key when auth is enabled.

    When ``STARSHIELD_API_KEY_REQUIRED`` is false, always allows the request.
    """
    if not auth_enabled():
        return None

    keys = get_valid_keys()
    if not keys:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "API key authentication is enabled but no keys are configured. "
                "Set STARSHIELD_API_KEYS or run: python main.py apikey --cmd generate"
            ),
            headers={"WWW-Authenticate": "ApiKey"},
        )

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                f"Missing API key. Pass header '{API_KEY_HEADER_NAME}: <key>'. "
                "See docs/USAGE.md (API Authentication)."
            ),
            headers={"WWW-Authenticate": "ApiKey"},
        )

    # Constant-time compare against each configured key
    ok = False
    for valid in keys:
        if secrets.compare_digest(api_key, valid):
            ok = True
            break
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return api_key


def generate_api_key(*, persist: bool = True, label: str = "") -> str:
    """Create a new URL-safe API key; optionally append to ``api_keys.txt``."""
    key = secrets.token_urlsafe(32)
    if persist:
        path = Path(API_KEYS_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(
                "# StarShield Lite API keys (one per line)\n"
                "# Generated keys — keep this file private\n",
                encoding="utf-8",
            )
        with path.open("a", encoding="utf-8") as f:
            if label:
                f.write(f"# {label}\n")
            f.write(key + "\n")
    return key


def list_stored_keys_masked() -> list:
    """Return masked previews of configured keys (for CLI list)."""
    out = []
    for k in sorted(get_valid_keys()):
        if len(k) <= 8:
            masked = "****"
        else:
            masked = k[:4] + "…" + k[-4:]
        out.append({"preview": masked, "length": len(k)})
    return out


# Alias for Depends() style imports
RequireAPIKey = Depends(require_api_key)
