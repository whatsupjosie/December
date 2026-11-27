"""The EQ engines run on their own, without PubPartner, Alex Core or the PubCast host.

This copies only the EQ engine files, plus the few shared files they import
(found by reading their import lines; in a branch checkout the shared ones come
from the blobs pinned in STANDALONE_DEPS.json), into an empty folder and imports them
there in a fresh Python process. If an engine starts to depend on PubPartner or
the studio, this test fails and names the module it could not find.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ENGINES = [
    "companion_support/eq_disambiguation_engine.py",
    "companion_support/conversation_pacing.py",
    "modules/situation_reading.py",
    "modules/emotional_orchestrator.py",
    "modules/eq_observation/__init__.py",
    "modules/peq/__init__.py",  # imported as top-level peq, with modules/ on sys.path (see peq_integration.init_peq)
    "modules/cre_eq/__init__.py",  # imported as top-level cre_eq, the same way
    "modules/peq_broker.py",
    "modules/peq_integration.py",
    "modules/care_eq.py",
    "modules/eq_monitoring_recorder.py",
    "modules/wired/eq_card_selector.py",
    "modules/wired/eq_integration_layer.py",
    "modules/wired/eq_adaptor.py",
    "modules/wired/eq_disambiguation_engine.py",
]

# Modules that, if pulled in, mean an engine is no longer standalone.
FORBIDDEN_PREFIXES = ("modules.pubpartner", "pubpartner", "modules.alex_core", "modules.alex_routes",
                      "modules.alex_jeremy_bridge", "modules.alex_memory", "main", "pubpartner_app")


def _assembler():
    spec = importlib.util.spec_from_file_location("assemble", ROOT / "tools" / "standalone" / "assemble.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _pins() -> dict[str, str]:
    manifest = ROOT / "STANDALONE_DEPS.json"
    if not manifest.is_file():
        return {}
    return {p["path"]: p["blob"] for p in json.loads(manifest.read_text(encoding="utf-8"))["pins"]}


def _body(rel: str, pins: dict[str, str]) -> bytes | None:
    """A file from this folder, or, in a branch checkout, its pinned shared blob."""
    if (ROOT / rel).is_file():
        return (ROOT / rel).read_bytes()
    if rel in pins:
        out = subprocess.run(["git", "cat-file", "blob", pins[rel]], cwd=ROOT, capture_output=True)
        if out.returncode == 0:
            return out.stdout
    return None


def _closure(assemble) -> dict[str, bytes]:
    """Engine files plus every December file they import, with their contents."""
    pins = _pins()
    files: dict[str, bytes] = {}
    queue = list(ENGINES)
    while queue:
        rel = queue.pop()
        if rel in files:
            continue
        body = _body(rel, pins)
        if body is None:
            continue
        files[rel] = body
        names = assemble.imports_of(body.decode("utf-8"), rel)
        for name in names:
            if not assemble.is_local(name):
                continue
            parts = name.split(".")
            for i in range(1, len(parts) + 1):
                for cand in assemble.module_to_candidates(".".join(parts[:i])):
                    if (ROOT / cand).is_file() or cand in pins:
                        queue.append(cand)
                        break
        # peq and cre_eq are separate packages that live under modules/.
        for name in names:
            if name.split(".")[0] in ("peq", "cre_eq"):
                for cand in assemble.module_to_candidates("modules." + name):
                    if (ROOT / cand).is_file() or cand in pins:
                        queue.append(cand)
    return files


def test_engines_pull_in_no_pubpartner_alex_core_or_host():
    files = sorted(_closure(_assembler()))
    modules = [f[:-3].replace("/", ".").removesuffix(".__init__") for f in files]
    assert "modules/cre_eq/engine.py" in files and "modules/peq/system.py" in files
    bad = [m for m in modules if m.startswith(FORBIDDEN_PREFIXES)]
    assert not bad, bad


def test_engines_import_and_read_in_an_empty_folder(tmp_path):
    files = _closure(_assembler())
    for rel, body in files.items():
        dest = tmp_path / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
    probe = r"""
import asyncio, importlib, json, os, sys
sys.path.insert(0, sys.argv[1])
names = json.loads(sys.argv[2])
for n in names:
    importlib.import_module(n)
from modules.peq_broker import PEQObservation, init_peq_broker
broker = init_peq_broker(os.path.join(sys.argv[1], "modules"))
peq_available = broker.stats()["peq_available"]
signal = asyncio.run(broker.submit(PEQObservation(subject_id="the-user", source="standalone-test",
                                                  text="I can't stop crying since the funeral")))
from companion_support.eq_disambiguation_engine import ContextDisambiguator
from modules.wired.eq_card_selector import ContextAwareCardSelector
r = ContextDisambiguator().analyze("my dog died", "t", include_history=False)
picks = [c.id for c, _ in ContextAwareCardSelector().select_response(r, 3)]
print(json.dumps({"context": r.primary_context.value, "first": picks[0] if picks else None,
                  "peq_available": peq_available, "signal": signal.to_dict(),
                  "loaded": sorted(m for m in sys.modules if m.split('.')[0] in ('modules', 'companion_support'))}))
"""
    names = [e[:-3].replace("/", ".").removesuffix(".__init__") for e in ENGINES
             if not e.startswith(("modules/peq/", "modules/cre_eq/"))]
    out = subprocess.run([sys.executable, "-I", "-c", probe, str(tmp_path), json.dumps(names)],
                         cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    result = json.loads(out.stdout.strip().splitlines()[-1])
    assert result["context"] == "loss"
    assert result["first"].startswith("loss_validation")
    assert result["peq_available"] is True
    signal = result["signal"]
    assert signal["subject_id"] == "the-user"
    assert 0 <= signal["care_level"] <= 3 and 0.0 <= signal["confidence"] <= 0.985
    assert not [m for m in result["loaded"] if m.startswith(FORBIDDEN_PREFIXES)]
