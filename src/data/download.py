"""Download and manifest generation for X-SPIDE, PonziGuard, and Blockchain@Unica."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

XSPIDE_REPO = "https://github.com/LucaPennella/x-spide-smart-ponzi-detection.git"
PONZIGUARD_COMMIT = "e748f4621d2778f82e05df54bfe59721d54dbd14"
UNICA_COMMIT = "e083ce720f934e17ea1fe9124b0ea874aa042bf"

PONZIGUARD_FILES = {
    "Ponzi.zip": (
        f"https://raw.githubusercontent.com/PonziDetection/PonziGuard/{PONZIGUARD_COMMIT}/dataset/Ponzi.zip"
    ),
    "non-Ponzi.zip": (
        f"https://raw.githubusercontent.com/PonziDetection/PonziGuard/{PONZIGUARD_COMMIT}/dataset/non-Ponzi.zip"
    ),
    "README.md": (
        f"https://raw.githubusercontent.com/PonziDetection/PonziGuard/{PONZIGUARD_COMMIT}/README.md"
    ),
}

UNICA_FILES = {
    "ponzi-addresses.csv": (
        "https://raw.githubusercontent.com/blockchain-unica/ethereum-ponzi/master/ponzi-addresses.csv"
    ),
    "LICENSE": (
        "https://raw.githubusercontent.com/blockchain-unica/ethereum-ponzi/master/LICENSE"
    ),
    "README.md": (
        "https://raw.githubusercontent.com/blockchain-unica/ethereum-ponzi/master/README.md"
    ),
}


def sha256_file(path: Path) -> str:
    """Compute hex SHA-256 digest of a file."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download_file(url: str, dest: Path, force: bool = False) -> Path:
    """Download URL to destination unless already present and not forced."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not force:
        return dest
    req = urllib.request.Request(url, headers={"User-Agent": "x-spide-g-phase1/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp, dest.open("wb") as out:
        while True:
            buf = resp.read(1 << 16)
            if not buf:
                break
            out.write(buf)
    return dest


def ensure_xspide_clone(xspide_dir: Path) -> str:
    """Clone X-SPIDE repo if absent and return its HEAD commit hash."""
    if not xspide_dir.exists():
        xspide_dir.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--depth", "1", XSPIDE_REPO, str(xspide_dir)], check=True)
    res = subprocess.run(
        ["git", "-C", str(xspide_dir), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return res.stdout.strip()


def detect_license(directory: Path) -> str:
    """Return license snippet if LICENSE file exists, else 'unspecified'."""
    for name in ("LICENSE", "LICENSE.md", "LICENSE.txt"):
        candidate = directory / name
        if candidate.exists():
            first_line = candidate.read_text(encoding="utf-8", errors="replace").splitlines()[0].strip()
            return f"{name}: {first_line}"
    return "unspecified (do not redistribute raw files)"


def inventory_directory(root: Path, exclude_git: bool = True) -> list[dict[str, Any]]:
    """List regular files with relative paths, sizes, and SHA-256 checksums."""
    items: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if exclude_git and ".git" in path.parts:
            continue
        items.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return items


def extract_zip_safe(zip_path: Path, dest_dir: Path) -> int:
    """Extract zip file safely (preventing path traversal) and return file count."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_resolved = dest_dir.resolve()
    count = 0
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.infolist():
            if member.is_dir():
                continue
            target = (dest_dir / member.filename).resolve()
            if not str(target).startswith(str(dest_resolved)):
                raise ValueError(f"Unsafe zip member path: {member.filename}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member, "r") as src, target.open("wb") as dst:
                dst.write(src.read())
            count += 1
    return count


def run_download(repo_root: Path, force: bool = False) -> Path:
    """Download all Phase 1 raw datasets and generate data/manifest.json."""
    raw_dir = repo_root / "data" / "raw"
    xspide_dir = raw_dir / "x-spide"
    pg_dir = raw_dir / "ponziguard"
    unica_dir = raw_dir / "unica"

    xspide_commit = ensure_xspide_clone(xspide_dir)

    for fname, url in PONZIGUARD_FILES.items():
        download_file(url, pg_dir / fname, force=force)
    ponzi_extracted = extract_zip_safe(pg_dir / "Ponzi.zip", pg_dir / "extracted" / "Ponzi")
    non_ponzi_extracted = extract_zip_safe(pg_dir / "non-Ponzi.zip", pg_dir / "extracted" / "non-Ponzi")

    for fname, url in UNICA_FILES.items():
        download_file(url, unica_dir / fname, force=force)

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "generated_at_utc": now_utc,
        "notes": "Raw files under data/raw/ are excluded from Git via .gitignore; verify checksums with this manifest.",
        "sources": {
            "x_spide": {
                "name": "X-SPIDE Official Source Code and Dataset",
                "url": XSPIDE_REPO,
                "commit": xspide_commit,
                "downloaded_at_utc": now_utc,
                "license": detect_license(xspide_dir),
                "local_dir": "data/raw/x-spide",
                "files": inventory_directory(xspide_dir, exclude_git=True),
            },
            "ponziguard": {
                "name": "PonziGuard / XBlock Dataset",
                "url": "https://github.com/PonziDetection/PonziGuard/tree/main/dataset",
                "commit": PONZIGUARD_COMMIT,
                "downloaded_at_utc": now_utc,
                "license": detect_license(pg_dir),
                "local_dir": "data/raw/ponziguard",
                "extracted_counts": {
                    "Ponzi": ponzi_extracted,
                    "non-Ponzi": non_ponzi_extracted,
                },
                "files": [
                    {
                        "path": fname,
                        "url": url,
                        "size_bytes": (pg_dir / fname).stat().st_size,
                        "sha256": sha256_file(pg_dir / fname),
                    }
                    for fname, url in PONZIGUARD_FILES.items()
                ],
            },
            "blockchain_unica": {
                "name": "Blockchain@Unica Ethereum Ponzi Address List",
                "url": "https://github.com/blockchain-unica/ethereum-ponzi/blob/master/ponzi-addresses.csv",
                "commit": UNICA_COMMIT,
                "downloaded_at_utc": now_utc,
                "license": detect_license(unica_dir),
                "local_dir": "data/raw/unica",
                "files": [
                    {
                        "path": fname,
                        "url": url,
                        "size_bytes": (unica_dir / fname).stat().st_size,
                        "sha256": sha256_file(unica_dir / fname),
                    }
                    for fname, url in UNICA_FILES.items()
                ],
            },
        },
    }

    manifest_path = repo_root / "data" / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest_path


def verify_manifest(repo_root: Path) -> None:
    """Verify SHA-256 digests of raw downloaded files against data/manifest.json."""
    manifest_path = repo_root / "data" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for src_name, src in manifest["sources"].items():
        base = repo_root / src["local_dir"]
        for entry in src["files"]:
            fp = base / entry["path"]
            if not fp.exists():
                raise FileNotFoundError(f"[{src_name}] Missing file: {fp}")
            actual = sha256_file(fp)
            if actual != entry["sha256"]:
                raise ValueError(f"[{src_name}] SHA-256 mismatch for {fp}: {actual} != {entry['sha256']}")
    print("Manifest SHA-256 verification passed.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download Phase 1 datasets and manage manifest.json.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--force", action="store_true", help="Re-download archived files.")
    parser.add_argument("--verify", action="store_true", help="Verify existing files against data/manifest.json.")
    args = parser.parse_args()

    if args.verify:
        verify_manifest(args.root)
    else:
        manifest_path = run_download(args.root, force=args.force)
        print(f"Wrote {manifest_path}")


if __name__ == "__main__":
    main()
