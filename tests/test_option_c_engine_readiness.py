"""Option C readiness regressions; no hardware or real encoder needed."""
import asyncio
from types import SimpleNamespace

from modules import recording_modes
from modules.recording_modes import ModeTake
from modules.evo.distributed_engine import DistributedEngineNode, WorkUnit


def test_first_frame_requires_video_not_audio(monkeypatch):
    monkeypatch.setattr(recording_modes, "FIRST_FRAME_WAIT_SECONDS", 0.001)
    engine = SimpleNamespace(running=lambda key: True,
                             live_report=lambda key: [{"encoded_seconds": 10, "encoded_video_frames": 0}])
    take = SimpleNamespace(controller=SimpleNamespace(capture_engine=engine))
    assert not asyncio.run(ModeTake._first_frame(take, SimpleNamespace(key="test")))


def test_first_frame_accepts_positive_video_counter(monkeypatch):
    monkeypatch.setattr(recording_modes, "FIRST_FRAME_WAIT_SECONDS", 1)
    engine = SimpleNamespace(running=lambda key: True,
                             live_report=lambda key: [{"encoded_video_frames": 1}])
    take = SimpleNamespace(controller=SimpleNamespace(capture_engine=engine))
    assert asyncio.run(ModeTake._first_frame(take, SimpleNamespace(key="test")))


def test_unwired_workers_do_not_claim_success():
    node = DistributedEngineNode.__new__(DistributedEngineNode)
    seen = []
    node._on_work_complete = [seen.append]
    for kind in ("voxel_render", "mesh_generate", "audio_process", "video_encode"):
        work = WorkUnit("test", kind, completed=True, result=b"stale")
        asyncio.run(node._process_work(work))
        assert not work.completed
        assert work.result is None
        assert "not wired" in work.error
    assert len(seen) == 4
