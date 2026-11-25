#!/usr/bin/env python3
"""Iteration Wallet static commit-pattern assessment.

The Wallet package does not invoke Git, install hooks, or inspect repository state
by running external commands. An external integration may collect repository facts
and pass a JSON manifest to this module for static assessment.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

BLOCKED_PATTERNS = [
    r"\.env$",
    r"\.env\..*$",
    r"config\.secret",
    r"credentials\.json",
    r"aws_access_key",
    r"private_key",
    r"\.pem$",
    r"oauth.*token",
    r"password.*\.txt",
    r"__pycache__/",
    r"node_modules/",
    r"\.pyc$",
    r"dist/",
    r"build/",
    r"\.DS_Store",
    r"Thumbs\.db",
]

WARN_PATTERNS = [
    r"^large_model_.*\.bin$",
    r"^data/.*\.csv$",
    r"\.zip$",
    r"test_.*_backup",
]


class CommitGuard:
    """Pure pattern assessment over repository facts supplied by the caller."""

    def __init__(
        self,
        *,
        project: str = "unknown",
        staged_files: Optional[Iterable[str]] = None,
        git_user: str = "unknown",
        git_branch: str = "unknown",
        git_root: Optional[Path] = None,
    ) -> None:
        self.project = str(project or "unknown")
        self.staged_files = [str(item) for item in (staged_files or [])]
        self.git_user = str(git_user or "unknown")
        self.git_branch = str(git_branch or "unknown")
        self.git_root = Path(git_root).resolve() if git_root else None

    @classmethod
    def from_manifest(cls, manifest: Dict[str, Any]) -> "CommitGuard":
        """Build an assessment from externally observed repository facts."""
        if not isinstance(manifest, dict):
            raise ValueError("Manifest must be a JSON object.")
        files = manifest.get("staged_files", manifest.get("files", []))
        if not isinstance(files, list) or not all(isinstance(item, str) for item in files):
            raise ValueError("Manifest staged_files/files must be a list of strings.")
        return cls(
            project=str(manifest.get("project") or "unknown"),
            staged_files=files,
            git_user=str(manifest.get("git_user") or "unknown"),
            git_branch=str(manifest.get("git_branch") or "unknown"),
            git_root=manifest.get("git_root"),
        )

    def _check_patterns(self, files: Iterable[str]) -> tuple[List[str], List[str]]:
        blocked: List[str] = []
        warned: List[str] = []
        for raw in files:
            file_name = str(raw).replace("\\", "/")
            if any(re.search(pattern, file_name) for pattern in BLOCKED_PATTERNS):
                blocked.append(str(raw))
            elif any(re.search(pattern, file_name) for pattern in WARN_PATTERNS):
                warned.append(str(raw))
        return blocked, warned

    def assess(self, files: Optional[Iterable[str]] = None) -> Dict[str, Any]:
        """Return a deterministic assessment without changing repository state."""
        assessed_files = [str(item) for item in (self.staged_files if files is None else files)]
        blocked, warned = self._check_patterns(assessed_files)
        return {
            "assessment_version": "1",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "observation_source": "caller_supplied_manifest",
            "project": self.project,
            "git_root": str(self.git_root) if self.git_root else None,
            "git_user": self.git_user,
            "git_branch": self.git_branch,
            "files_count": len(assessed_files),
            "files": assessed_files[:50],
            "blocked": blocked,
            "warnings": warned,
            "allowed": not blocked,
            "authority": "advisory_only",
        }

    def run(self, files: Optional[Iterable[str]] = None) -> bool:
        """Print the static assessment and return whether blocked patterns exist."""
        assessment = self.assess(files)
        if assessment["blocked"]:
            print("\nCommit pattern assessment: BLOCKED")
            for item in assessment["blocked"][:10]:
                print(f"  - {item}")
        else:
            print("\nCommit pattern assessment: OK")
        if assessment["warnings"]:
            print("Warnings:")
            for item in assessment["warnings"][:10]:
                print(f"  - {item}")
        print(f"Project: {assessment['project']}")
        print(f"Files assessed: {assessment['files_count']}")
        print("Authority: advisory only; an external integration owns Git interaction.")
        return bool(assessment["allowed"])


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Assess caller-supplied repository facts without invoking or modifying Git."
    )
    parser.add_argument("--manifest", type=Path, required=True, help="JSON manifest supplied by an external Git integration.")
    parser.add_argument("--json", action="store_true", help="Print the assessment as JSON.")
    args = parser.parse_args(argv)

    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        guard = CommitGuard.from_manifest(manifest)
        assessment = guard.assess()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Commit pattern assessment failed: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(assessment, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        guard.run()
    return 0 if assessment["allowed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
