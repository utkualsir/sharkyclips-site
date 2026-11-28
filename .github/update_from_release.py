"""Runs in the public website repo (utkualsir/sharkyclips-site), copied there by docs/publish-site.sh (1.2.78).

Every release of SharkyClips carries the website built for it (website-<version>.zip, made by the
"Publish the website" job of installer.yml with that release's real sizes and checksums). This
script, started by the site repo's own workflow, unpacks the newest one over the site when the
site still offers an older version, checks it with check_release.py and leaves the commit to the
workflow. It needs no token of the app repo: release assets of a public repo are public.

    python .github/update_from_release.py          exit 0 = updated or already current, 1 = problem
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

SITE = Path(__file__).resolve().parents[1]
APP_REPO = "utkualsir/sharkyclips"
KEEP = {".git", ".github", "README.md", ".nojekyll"}
# what the site is made of: anything else in the zip is refused
ALLOWED = re.compile(r"^[A-Za-z0-9_\-./]+\.(html|css|json|xml|txt|svg|png|ico|webp|webm|mp4|vtt|woff2|jpg)$")
MAX_BYTES = 200_000_000

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_release  # noqa: E402  (copied next to this file)


def _get(url: str) -> bytes:
    headers = {"User-Agent": "sharkyclips-site-update", "Accept": "application/octet-stream"}
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120) as r:  # noqa: S310
        return r.read(MAX_BYTES + 1)


def main() -> int:
    rel_api = json.loads(check_release._get(f"https://api.github.com/repos/{APP_REPO}/releases/latest", api=True))
    version = rel_api["tag_name"].lstrip("v")
    current = json.loads((SITE / "release.json").read_text(encoding="utf-8")) if (SITE / "release.json").is_file() else {}
    rel = check_release.latest_release(APP_REPO)
    live = {n: (SITE / n).read_text(encoding="utf-8") if (SITE / n).is_file() else ""
            for n in ("release.json", "download.html", "updates.html")}
    if not check_release.compare(live, rel):
        print(f"site already offers {version}")
        return 0
    asset = next((a for a in rel_api.get("assets", []) if a["name"] == f"website-{version}.zip"), None)
    if not asset:
        print(f"release v{version} has no website-{version}.zip yet (the release job may still run)")
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
                f.write("waiting=1" + chr(10))
        return 0 if current.get("version") != version else 1
    data = _get(asset["browser_download_url"])
    if len(data) > MAX_BYTES:
        print("website zip too big")
        return 1
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = [i.filename for i in z.infolist() if not i.is_dir()]
        bad = [n for n in names if n.startswith("/") or ".." in n.split("/") or not ALLOWED.match(n)]
        if bad or "release.json" not in names or "index.html" not in names:
            print(f"refusing the website zip: {bad[:5] or 'missing index.html / release.json'}")
            return 1
        tmp = Path(tempfile.mkdtemp(prefix="site-"))
        z.extractall(tmp)
    built = {n: (tmp / n).read_text(encoding="utf-8") for n in ("release.json", "download.html", "updates.html")}
    problems = check_release.compare(built, rel)
    if problems:
        print("the release's website doesn't match the release:\n" + "\n".join(problems))
        return 1
    for child in SITE.iterdir():
        if child.name in KEEP:
            continue
        shutil.rmtree(child) if child.is_dir() else child.unlink()
    for src in tmp.rglob("*"):
        if src.is_file():
            dst = SITE / src.relative_to(tmp)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    shutil.rmtree(tmp)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write(f"version={version}\n")
    print(f"site updated to {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
