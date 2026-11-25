#!/usr/bin/env python3
"""Build reproducible pure-Python alpha wheels without external build tooling."""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import os
import zipfile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from iteration_wallet.version import WALLET_VERSION, BLACKBOX_VERSION
DIST = ROOT / "dist"
DIST.mkdir(exist_ok=True)


def digest(data: bytes) -> str:
    return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()


def build_wheel(*, filename: str, dist_info: str, files: list[tuple[Path, str]], metadata: str, entry_points: str = "", top_level: str = "") -> Path:
    target = DIST / filename
    records: list[tuple[str, str, str]] = []
    wheel_text = """Wheel-Version: 1.0
Generator: Rearview Foresight manual pure-python builder 1
Root-Is-Purelib: true
Tag: py3-none-any
"""
    extras = {
        f"{dist_info}/METADATA": metadata.strip() + "\n",
        f"{dist_info}/WHEEL": wheel_text,
        f"{dist_info}/top_level.txt": top_level.strip() + "\n",
    }
    if entry_points.strip():
        extras[f"{dist_info}/entry_points.txt"] = entry_points.strip() + "\n"

    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for source, arcname in sorted(files, key=lambda item: item[1]):
            data = source.read_bytes()
            info = zipfile.ZipInfo(arcname, date_time=(2026, 7, 25, 12, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o644 & 0xFFFF) << 16
            archive.writestr(info, data)
            records.append((arcname, digest(data), str(len(data))))
        for arcname, text in sorted(extras.items()):
            data = text.encode("utf-8")
            info = zipfile.ZipInfo(arcname, date_time=(2026, 7, 25, 12, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o644 & 0xFFFF) << 16
            archive.writestr(info, data)
            records.append((arcname, digest(data), str(len(data))))
        record_name = f"{dist_info}/RECORD"
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerows(records)
        writer.writerow((record_name, "", ""))
        data = buffer.getvalue().encode("utf-8")
        info = zipfile.ZipInfo(record_name, date_time=(2026, 7, 25, 12, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = (0o644 & 0xFFFF) << 16
        archive.writestr(info, data)
    return target


def package_files(package_root: Path, package_name: str) -> list[tuple[Path, str]]:
    result=[]
    for path in package_root.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        result.append((path, f"{package_name}/{path.relative_to(package_root).as_posix()}"))
    return result


def main() -> None:
    wallet_files = package_files(ROOT / "iteration_wallet", "iteration_wallet")
    wallet_files += package_files(ROOT / "iteration_wallet_blackbox", "iteration_wallet_blackbox")
    wallet_metadata = f"""Metadata-Version: 2.1
Name: iteration-wallet
Version: {WALLET_VERSION}
Summary: Local-first non-destructive project generation custody for AI-assisted work
Author: Josie Curtsey Cobbley
License: Proprietary
Requires-Python: >=3.10
Requires-Dist: fastapi>=0.111.0
Requires-Dist: uvicorn[standard]>=0.29.0
Requires-Dist: pydantic>=2.0.0
Requires-Dist: requests>=2.31.0
Requires-Dist: cryptography>=42.0.0
Requires-Dist: bbx1-iteration-wallet-plugin=={BLACKBOX_VERSION}
"""
    wallet_entries = """[console_scripts]
iteration-wallet = iteration_wallet.cli:main
iw = iteration_wallet.cli:main
iw-private-alpha-flow = iteration_wallet.private_alpha_runner:main
"""
    wallet = build_wheel(
        filename=f"iteration_wallet-{WALLET_VERSION}-py3-none-any.whl",
        dist_info=f"iteration_wallet-{WALLET_VERSION}.dist-info",
        files=wallet_files,
        metadata=wallet_metadata,
        entry_points=wallet_entries,
        top_level="iteration_wallet\niteration_wallet_blackbox",
    )

    blackbox_files = package_files(ROOT / "blackbox_source" / "blackbox_plugin", "blackbox_plugin")
    blackbox_metadata = f"""Metadata-Version: 2.1
Name: bbx1-iteration-wallet-plugin
Version: {BLACKBOX_VERSION}
Summary: Standalone tamper-evident BlackBox recorder for Iteration Wallet
License: Proprietary Alpha
Requires-Python: >=3.10
"""
    blackbox_entries = """[console_scripts]
bbx1 = blackbox_plugin.cli:main
"""
    blackbox = build_wheel(
        filename=f"bbx1_iteration_wallet_plugin-{BLACKBOX_VERSION}-py3-none-any.whl",
        dist_info=f"bbx1_iteration_wallet_plugin-{BLACKBOX_VERSION}.dist-info",
        files=blackbox_files,
        metadata=blackbox_metadata,
        entry_points=blackbox_entries,
        top_level="blackbox_plugin",
    )
    print(wallet)
    print(blackbox)


if __name__ == "__main__":
    main()
