"""How bytes get here, kept separate from what they mean.

Every source goes through this layer, so adding the hosts to the
account's network allowlist is a configuration change rather than a
rewrite. The order is deliberate:

    1. HTTP          — the real thing, when the host is reachable
    2. cache         — the last good payload, replayed and marked STALE
    3. unavailable   — nothing; the component scores 0 and SAYS SO

Point 3 is the one that matters. A pipeline that silently scores zero
when a feed breaks produces a neutral board that looks identical to a
genuinely neutral market. Every failure here is carried forward as a
SourceStamp and surfaced on the dashboard.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

from ..core.types import RawPayload, SourceStamp

CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"
USER_AGENT = "wagmacro/1.0 (research dashboard)"
TIMEOUT_SECONDS = 20


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _cache_path(name: str) -> Path:
    return CACHE_DIR / f"{name}.txt"


def _meta_path(name: str) -> Path:
    return CACHE_DIR / f"{name}.meta.json"


def write_cache(name: str, body: str, data_dated: date | None) -> None:
    """Persist a good payload so a later failure has something to replay."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(name).write_text(body, encoding="utf-8")
    _meta_path(name).write_text(
        json.dumps({
            "retrieved_at": _now().isoformat(),
            "data_dated": data_dated.isoformat() if data_dated else None,
        }),
        encoding="utf-8",
    )


def _read_cache(name: str, url: str, detail: str) -> RawPayload:
    path = _cache_path(name)
    if not path.exists():
        return RawPayload(
            stamp=SourceStamp(
                name=name, url=url, retrieved_at=None, data_dated=None,
                transport="unavailable", ok=False,
                detail=f"{detail}; no cached payload either",
            ),
            body="",
        )

    retrieved_at: datetime | None = None
    data_dated: date | None = None
    if _meta_path(name).exists():
        try:
            meta = json.loads(_meta_path(name).read_text(encoding="utf-8"))
            if meta.get("retrieved_at"):
                retrieved_at = datetime.fromisoformat(meta["retrieved_at"])
            if meta.get("data_dated"):
                data_dated = date.fromisoformat(meta["data_dated"])
        except (ValueError, KeyError):
            pass   # a corrupt sidecar must not lose the payload itself

    return RawPayload(
        stamp=SourceStamp(
            name=name, url=url, retrieved_at=retrieved_at,
            data_dated=data_dated, transport="cache", ok=True,
            detail=f"{detail}; replayed from cache",
        ),
        body=path.read_text(encoding="utf-8"),
    )


def fetch(name: str, url: str, *, allow_cache: bool = True) -> RawPayload:
    """Fetch `url`, falling back to the cached copy when the host is blocked.

    Never raises. A source that cannot be reached is a data condition,
    not an exception — the pipeline has to finish and report the gap.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8", errors="replace")
        if not body.strip():
            raise ValueError("empty response body")
        return RawPayload(
            stamp=SourceStamp(
                name=name, url=url, retrieved_at=_now(), data_dated=None,
                transport="http", ok=True,
            ),
            body=body,
        )
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError,
            TimeoutError, OSError) as exc:
        detail = f"live fetch failed: {type(exc).__name__}: {exc}"
        if allow_cache:
            return _read_cache(name, url, detail)
        return RawPayload(
            stamp=SourceStamp(
                name=name, url=url, retrieved_at=None, data_dated=None,
                transport="unavailable", ok=False, detail=detail,
            ),
            body="",
        )


def host_reachable(host: str) -> bool:
    """Cheap preflight so the dashboard can explain a blocked allowlist."""
    try:
        request = urllib.request.Request(
            f"https://{host}/", headers={"User-Agent": USER_AGENT})
        urllib.request.urlopen(request, timeout=8).close()
        return True
    except Exception:
        return False
