"""GitHub Releases update check."""
from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import re
from urllib.request import Request, urlopen

log = logging.getLogger(__name__)

DEFAULT_REPO = "shgeum/VRCLT"
GITHUB_API = "https://api.github.com/repos/{repo}/releases/latest"


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    latest_version: str
    release_url: str
    release_name: str = ""


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


def check_latest_release(current_version: str, *, repo: str = DEFAULT_REPO,
                         timeout: float = 5.0) -> UpdateInfo | None:
    """Return update info when GitHub has a newer non-draft release."""
    url = GITHUB_API.format(repo=repo)
    req = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"vrclt/{current_version or 'unknown'}",
        },
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception:
        log.debug("update check failed", exc_info=True)
        return None

    tag = str(data.get("tag_name") or "").strip()
    if not tag or not is_newer_version(tag, current_version):
        return None
    return UpdateInfo(
        current_version=current_version,
        latest_version=tag,
        release_url=str(data.get("html_url") or f"https://github.com/{repo}/releases/latest"),
        release_name=str(data.get("name") or tag),
    )
