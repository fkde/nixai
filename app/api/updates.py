from __future__ import annotations

import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.__version__ import __version__
from app.config import data_dir


router = APIRouter(prefix="/api/updates", tags=["updates"])

GITHUB_REPO = "fkde/nixai"
RELEASE_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
ASSET_SUFFIX_MACOS = "-macos.zip"
CHECK_CACHE_SECONDS = 3600


_cache: dict[str, object] = {"at": 0.0, "value": None}
_cache_lock = threading.Lock()
_install_state: dict[str, object] = {"status": "idle", "message": "", "progress": 0.0}
_install_lock = threading.Lock()


class UpdateInfo(BaseModel):
    current: str
    latest: Optional[str] = None
    available: bool = False
    notes: Optional[str] = None
    asset_url: Optional[str] = None
    asset_name: Optional[str] = None
    asset_size: Optional[int] = None
    platform_supported: bool = True
    error: Optional[str] = None


class InstallStatus(BaseModel):
    status: str
    message: str = ""
    progress: float = 0.0


def _parse_version(tag: str) -> tuple[int, ...]:
    cleaned = tag.lstrip("vV").split("-", 1)[0].split("+", 1)[0]
    parts: list[int] = []
    for chunk in cleaned.split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            return tuple(parts)
    return tuple(parts) or (0,)


def _is_newer(latest: str, current: str) -> bool:
    return _parse_version(latest) > _parse_version(current)


def _pick_asset(assets: list[dict], suffix: str) -> Optional[dict]:
    for asset in assets:
        name = asset.get("name", "")
        if name.endswith(suffix):
            return asset
    return None


def _platform_asset_suffix() -> Optional[str]:
    if sys.platform == "darwin":
        return ASSET_SUFFIX_MACOS
    return None


def _set_install_state(status: str, message: str = "", progress: float = 0.0) -> None:
    with _install_lock:
        _install_state["status"] = status
        _install_state["message"] = message
        _install_state["progress"] = progress


def _macos_app_path() -> Optional[Path]:
    """Return the NixAI.app bundle path when running from a packaged build."""
    exe = Path(sys.executable).resolve()
    for parent in exe.parents:
        if parent.suffix == ".app" and parent.name == "NixAI.app":
            return parent
    return None


@router.get("/check", response_model=UpdateInfo)
async def check_updates(force: bool = False) -> UpdateInfo:
    suffix = _platform_asset_suffix()
    if suffix is None:
        return UpdateInfo(current=__version__, platform_supported=False)

    now = time.time()
    with _cache_lock:
        cached = _cache.get("value")
        cached_at = float(_cache.get("at") or 0.0)
        if not force and cached and (now - cached_at) < CHECK_CACHE_SECONDS:
            return UpdateInfo(**cached)  # type: ignore[arg-type]

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(
                RELEASE_URL,
                headers={"Accept": "application/vnd.github+json"},
            )
        if response.status_code == 404:
            info = UpdateInfo(current=__version__, error="no_release")
        else:
            response.raise_for_status()
            data = response.json()
            tag = (data.get("tag_name") or "").strip()
            asset = _pick_asset(data.get("assets") or [], suffix)
            available = bool(tag) and _is_newer(tag, __version__) and asset is not None
            info = UpdateInfo(
                current=__version__,
                latest=tag or None,
                available=available,
                notes=data.get("body") or None,
                asset_url=(asset or {}).get("browser_download_url"),
                asset_name=(asset or {}).get("name"),
                asset_size=(asset or {}).get("size"),
            )
    except Exception as exc:  # noqa: BLE001 — network call, surface as soft error
        info = UpdateInfo(current=__version__, error=str(exc))

    with _cache_lock:
        _cache["at"] = now
        _cache["value"] = info.model_dump()
    return info


@router.get("/status", response_model=InstallStatus)
def install_status() -> InstallStatus:
    with _install_lock:
        return InstallStatus(
            status=str(_install_state["status"]),
            message=str(_install_state["message"]),
            progress=float(_install_state["progress"]),
        )


@router.post("/install", response_model=InstallStatus)
async def install_update() -> InstallStatus:
    if sys.platform != "darwin":
        raise HTTPException(status_code=400, detail="In-place updates are only supported on macOS for now.")

    app_path = _macos_app_path()
    if app_path is None:
        raise HTTPException(status_code=400, detail="In-place updates require the packaged .app build.")

    with _install_lock:
        if _install_state["status"] in {"downloading", "staging", "swapping"}:
            return InstallStatus(
                status=str(_install_state["status"]),
                message=str(_install_state["message"]),
                progress=float(_install_state["progress"]),
            )
        _install_state["status"] = "downloading"
        _install_state["message"] = "Preparing"
        _install_state["progress"] = 0.0

    info = await check_updates(force=True)
    if not info.available or not info.asset_url:
        _set_install_state("idle", "No update available")
        raise HTTPException(status_code=409, detail="No update available.")

    threading.Thread(
        target=_run_macos_install,
        args=(info.asset_url, info.asset_size or 0, app_path),
        daemon=True,
    ).start()
    return InstallStatus(status="downloading", message="Downloading update", progress=0.0)


def _run_macos_install(asset_url: str, asset_size: int, app_path: Path) -> None:
    try:
        updates_dir = data_dir() / "updates"
        updates_dir.mkdir(parents=True, exist_ok=True)
        for stale in updates_dir.glob("staging-*"):
            shutil.rmtree(stale, ignore_errors=True)
        for stale in updates_dir.glob("download-*.zip"):
            try:
                stale.unlink()
            except OSError:
                pass

        zip_path = updates_dir / f"download-{int(time.time())}.zip"
        _set_install_state("downloading", "Downloading update", 0.0)

        with httpx.stream("GET", asset_url, follow_redirects=True, timeout=60.0) as response:
            response.raise_for_status()
            total = int(response.headers.get("Content-Length") or asset_size or 0)
            received = 0
            with zip_path.open("wb") as fh:
                for chunk in response.iter_bytes(chunk_size=1024 * 256):
                    fh.write(chunk)
                    received += len(chunk)
                    if total:
                        _set_install_state("downloading", "Downloading update", received / total)

        _set_install_state("staging", "Preparing installer", 1.0)

        staging = updates_dir / f"staging-{int(time.time())}"
        staging.mkdir(parents=True, exist_ok=True)

        helper = _write_macos_helper(zip_path, staging, app_path, os.getpid())
        _set_install_state("swapping", "Restarting to finish update", 1.0)

        subprocess.Popen(
            ["/bin/bash", str(helper)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )

        threading.Timer(0.8, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()
    except Exception as exc:  # noqa: BLE001
        _set_install_state("error", str(exc), 0.0)


def _write_macos_helper(zip_path: Path, staging: Path, app_path: Path, pid: int) -> Path:
    log_path = staging.parent / "update.log"
    script = f"""#!/bin/bash
set -e
exec >>"{log_path}" 2>&1
echo "[update] $(date) waiting for pid {pid}"
for _ in $(seq 1 200); do
  if ! kill -0 {pid} 2>/dev/null; then break; fi
  sleep 0.2
done
echo "[update] extracting"
/usr/bin/ditto -x -k "{zip_path}" "{staging}"
NEW_APP=$(/usr/bin/find "{staging}" -maxdepth 3 -name "NixAI.app" -type d | head -n 1)
if [ -z "$NEW_APP" ]; then
  echo "[update] new app not found in archive"
  exit 1
fi
echo "[update] swapping $NEW_APP -> {app_path}"
BACKUP="{app_path}.old-$(date +%s)"
/bin/mv "{app_path}" "$BACKUP"
/bin/mv "$NEW_APP" "{app_path}"
/usr/bin/xattr -dr com.apple.quarantine "{app_path}" || true
/bin/rm -rf "$BACKUP"
/bin/rm -f "{zip_path}"
/bin/rm -rf "{staging}"
echo "[update] relaunching"
/usr/bin/open "{app_path}"
"""
    helper_path = staging.parent / f"helper-{int(time.time())}.sh"
    helper_path.write_text(script, encoding="utf-8")
    helper_path.chmod(helper_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return helper_path
