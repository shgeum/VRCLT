"""GitHub Releases update check."""
from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
import re
import socket
import ssl
import time
import urllib.error
from urllib.request import Request, urlopen

log = logging.getLogger(__name__)

DEFAULT_REPO = "shgeum/VRCLT"
GITHUB_API_LATEST = "https://api.github.com/repos/{repo}/releases/latest"
GITHUB_API_LIST = "https://api.github.com/repos/{repo}/releases?per_page=10"

_RETRIABLE_KINDS = {"timeout", "network", "http_5xx"}

_ssl_context_cache: tuple[ssl.SSLContext | None] | None = None


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    latest_version: str
    release_url: str
    release_name: str = ""


@dataclass(frozen=True)
class UpdateCheckResult:
    status: str  # "update" | "up_to_date" | "error"
    info: UpdateInfo | None = None
    latest_version: str = ""
    error_kind: str = ""  # rate_limited | no_release | ssl | timeout | network | http | parse
    detail: str = ""


def _version_key(version: str) -> tuple[int, ...]:
    """Return a comparable key for tags like v1.2.3 or 1.2.3."""
    version = (version or "").strip().lstrip("vV")
    main = re.split(r"[-+]", version, maxsplit=1)[0]
    parts = []
    for part in re.split(r"[._]", main):
        if not part:
            continue
        match = re.match(r"\d+", part)
        parts.append(int(match.group(0)) if match else 0)
    return tuple(parts or [0])


def is_newer_version(latest: str, current: str) -> bool:
    latest_key = _version_key(latest)
    current_key = _version_key(current)
    width = max(len(latest_key), len(current_key))
    return latest_key + (0,) * (width - len(latest_key)) > \
        current_key + (0,) * (width - len(current_key))


def _ssl_context() -> ssl.SSLContext | None:
    """certifi-backed context when available (frozen builds bundle it);
    default context otherwise; None = let urlopen use its own default."""
    global _ssl_context_cache
    if _ssl_context_cache is not None:
        return _ssl_context_cache[0]
    ctx: ssl.SSLContext | None = None
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        log.debug("certifi unavailable, using default SSL context", exc_info=True)
        try:
            ctx = ssl.create_default_context()
        except Exception:
            ctx = None
    _ssl_context_cache = (ctx,)
    return ctx


def _classify(exc: Exception) -> tuple[str, str]:
    """Map an exception to (error_kind, detail). HTTP 404 is handled by the
    caller (release-list fallback) before classification."""
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code in (403, 429):
            return "rate_limited", f"HTTP {exc.code}"
        if exc.code >= 500:
            return "http_5xx", f"HTTP {exc.code}"
        return "http", f"HTTP {exc.code}"
    reason = getattr(exc, "reason", None)
    if isinstance(exc, ssl.SSLError) or isinstance(reason, ssl.SSLError):
        return "ssl", str(reason or exc)
    if isinstance(exc, (TimeoutError, socket.timeout)) or \
            isinstance(reason, (TimeoutError, socket.timeout)):
        return "timeout", str(reason or exc)
    if isinstance(exc, (urllib.error.URLError, OSError)):
        return "network", str(reason or exc)
    if isinstance(exc, (json.JSONDecodeError, UnicodeDecodeError, ValueError)):
        return "parse", str(exc)
    return "network", str(exc)


def _fetch_json(url: str, current_version: str, timeout: float):
    req = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": f"vrclt/{current_version or 'unknown'}",
        },
    )
    ctx = _ssl_context()
    kwargs = {"timeout": timeout}
    if ctx is not None:
        kwargs["context"] = ctx
    with urlopen(req, **kwargs) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _fetch_latest_release(repo: str, current_version: str,
                          timeout: float) -> dict | None:
    """Latest stable release dict, or None when the repo has none.
    /releases/latest 404s when only drafts/prereleases exist, so fall back
    to the release list and filter client-side."""
    try:
        return _fetch_json(GITHUB_API_LATEST.format(repo=repo),
                           current_version, timeout)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
    try:
        releases = _fetch_json(GITHUB_API_LIST.format(repo=repo),
                               current_version, timeout)
    except urllib.error.HTTPError as e:
        if e.code == 404:  # repo itself missing/renamed
            return None
        raise
    if not isinstance(releases, list):
        raise ValueError("unexpected /releases payload")
    for rel in releases:
        if isinstance(rel, dict) and not rel.get("draft") \
                and not rel.get("prerelease") and rel.get("tag_name"):
            return rel
    return None


def check_latest_release(current_version: str, *, repo: str = DEFAULT_REPO,
                         timeout: float = 5.0, retries: int = 1,
                         retry_delay: float = 2.0) -> UpdateCheckResult:
    """Check GitHub for a newer non-draft, non-prerelease release.

    Never silent: every outcome is logged and returned as an explicit
    UpdateCheckResult. Blocks (including the retry sleep) — call from a
    worker thread only.
    """
    repo = os.environ.get("VRCLT_UPDATE_REPO") or repo
    kind = detail = ""
    data = None
    for attempt in range(retries + 1):
        try:
            data = _fetch_latest_release(repo, current_version, timeout)
            break
        except Exception as e:
            kind, detail = _classify(e)
            if attempt < retries and kind in _RETRIABLE_KINDS:
                log.debug("update check attempt %d failed (%s): %s — retrying",
                          attempt + 1, kind, detail)
                time.sleep(retry_delay)
                continue
            if kind == "http_5xx":
                kind = "http"
            log.warning("update check failed (%s): %s", kind, detail)
            return UpdateCheckResult(status="error", error_kind=kind,
                                     detail=detail)

    if data is None:
        log.warning("update check: no eligible release found in %s", repo)
        return UpdateCheckResult(status="error", error_kind="no_release",
                                 detail=f"no release in {repo}")

    tag = str(data.get("tag_name") or "").strip()
    if not tag:
        log.warning("update check: release without tag_name in %s", repo)
        return UpdateCheckResult(status="error", error_kind="parse",
                                 detail="release missing tag_name")
    if not is_newer_version(tag, current_version):
        log.info("update check: current=%s latest=%s (up to date)",
                 current_version, tag)
        return UpdateCheckResult(status="up_to_date", latest_version=tag)
    log.info("update check: current=%s latest=%s (update available)",
             current_version, tag)
    return UpdateCheckResult(
        status="update",
        latest_version=tag,
        info=UpdateInfo(
            current_version=current_version,
            latest_version=tag,
            release_url=str(data.get("html_url")
                            or f"https://github.com/{repo}/releases/latest"),
            release_name=str(data.get("name") or tag),
        ),
    )
