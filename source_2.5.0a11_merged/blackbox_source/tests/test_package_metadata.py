from pathlib import Path
import re


def test_runtime_version_matches_project_metadata():
    from blackbox_plugin import __version__

    text = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert match is not None
    assert __version__ == match.group(1)


def test_canonical_current_state_is_packaged():
    root = Path(__file__).resolve().parents[1]
    assert (root / "CANONICAL_CURRENT_STATE.md").is_file()
    assert (root / "PRODUCT_LAWS.md").is_file()
