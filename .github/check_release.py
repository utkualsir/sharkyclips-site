"""Check that the website offers the latest GitHub release (1.2.78).

    python docs/sitegen/check_release.py                       the built site in docs/site
    python docs/sitegen/check_release.py --site https://utkualsir.github.io/sharkyclips-site/ --wait 600

Fails (exit 1) when the site's version, installer checksums or file sizes differ from the newest
release on GitHub, or when the Updates page has no entry for it. The CI "Publish the website" job
runs it against the live site after every release, and the "Website matches the release" workflow
runs it every day, so a stale download page can't go unnoticed again (1.2.77 shipped with the
1.2.76 page). Standard library only; GITHUB_TOKEN is used when set (higher API rate limit).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = "utkualsir/sharkyclips"
UA = "sharkyclips-site-check"


def _get(url: str, api: bool = False) -> bytes:
    headers = {"User-Agent": UA}
    if api:
        headers["Accept"] = "application/vnd.github+json"
        if os.environ.get("GITHUB_TOKEN"):
            headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:  # noqa: S310 (https only)
        return r.read()


def latest_release(repo: str = REPO) -> dict:
    """The newest published release: version, installer sizes and the checksums from its .sha256 files."""
    rel = json.loads(_get(f"https://api.github.com/repos/{repo}/releases/latest", api=True))
    version = rel["tag_name"].lstrip("v")
    assets = {a["name"]: a for a in rel.get("assets", [])}
    out: dict = {"version": version, "files": {}}
    for kind, name in (("setup", f"SharkyClips-Setup-{version}.exe"), ("install_sh", "install.sh")):
        info: dict = {"name": name, "bytes": assets[name]["size"] if name in assets else None, "sha256": None}
        sha = assets.get(f"{name}.sha256")
        if sha:
            h = _get(sha["browser_download_url"]).decode("utf-8", "replace").split()[0].lower()
            info["sha256"] = h if re.fullmatch(r"[0-9a-f]{64}", h) else None
        out["files"][kind] = info
    return out


def read_site(site: str) -> dict[str, str]:
    """release.json, download.html and updates.html of a built folder or a live URL."""
    names = ("release.json", "download.html", "updates.html")
    if re.match(r"https?://", site):
        base = site if site.endswith("/") else site + "/"
        bust = f"?check={int(time.time())}"  # GitHub Pages' CDN caches for a few minutes
        return {n: _get(base + n + bust).decode("utf-8") for n in names}
    root = Path(site)
    return {n: (root / n).read_text(encoding="utf-8") if (root / n).is_file() else "" for n in names}


def compare(site: dict[str, str], rel: dict) -> list[str]:
    problems: list[str] = []
    v = rel["version"]
    try:
        offered = json.loads(site["release.json"] or "{}")
    except ValueError:
        offered = {}
    if offered.get("version") != v:
        problems.append(f"site offers version {offered.get('version')!r}, the latest release is {v}")
    for kind, want in rel["files"].items():
        if not want["sha256"]:
            problems.append(f"release v{v} has no {want['name']}.sha256 yet")
            continue
        got = (offered.get("files") or {}).get(kind) or {}
        if got.get("sha256") != want["sha256"]:
            problems.append(f"{want['name']}: site checksum {got.get('sha256')!r} != release {want['sha256']}")
        if want["bytes"] and got.get("bytes") != want["bytes"]:
            problems.append(f"{want['name']}: site size {got.get('bytes')!r} != release {want['bytes']}")
        if want["sha256"] not in site["download.html"]:
            problems.append(f"download page doesn't show the checksum of {want['name']}")
    if f"SharkyClips-Setup-{v}.exe" not in site["download.html"]:
        problems.append(f"download page doesn't link SharkyClips-Setup-{v}.exe")
    if f'id="v{v}"' not in site["updates.html"]:
        problems.append(f"Updates page has no entry for {v}")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--site", default=str(HERE.parent / "site"), help="built folder or live URL")
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--wait", type=int, default=0, help="keep retrying for this many seconds (Pages deploy)")
    a = ap.parse_args(argv)
    rel = latest_release(a.repo)
    deadline = time.monotonic() + a.wait
    while True:
        try:
            problems = compare(read_site(a.site), rel)
        except OSError as e:
            problems = [f"site not readable: {e}"]
        if not problems or time.monotonic() >= deadline:
            break
        print(f"not yet: {problems[0]} (retrying)")
        time.sleep(30)
    if problems:
        print("\n".join(problems))
        return 1
    print(f"site matches release v{rel['version']} ({rel['files']['setup']['sha256']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
