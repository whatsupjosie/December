"""Focused engine regressions: exact broad phase, room isolation, bounded frames."""
import random
import pytest
from modules.bubble_stack import BubbleGridConfig, BubbleStack, BonePresence, ObjectPresence
from modules.bubble_stack_pikpc.core import AABB, BubbleConfig, Vec3
from modules.bubble_stack_pikpc.engine import BubbleStackEngine, FrameObject


def test_index_matches_brute_force():
    rng = random.Random(42)
    stack = BubbleStack(BubbleGridConfig("studio", origin=(-2.3,-1.1,-3.0),
                                        dimensions=(8,3,7), radius=.83, spacing=.4))
    for _ in range(300):
        p = tuple(rng.uniform(-5, 8) for _ in range(3))
        expected = {b.bubble_id for b in stack.bubbles.values() if b.contains(p)}
        actual = {b.bubble_id for b in stack._candidate_bubbles(p) if b.contains(p)}
        assert actual == expected
    for b in list(stack.bubbles.values())[::101]:
        for sign in (-1,1):
            p = (b.center[0]+sign*stack.config.radius, *b.center[1:])
            assert {x.bubble_id for x in stack._candidate_bubbles(p) if x.contains(p)} == {
                x.bubble_id for x in stack.bubbles.values() if x.contains(p)}


def test_actor_and_object_relocation_clears_old_cells():
    s = BubbleStack(BubbleGridConfig("r", radius=.5))
    s.ingest_skeleton_frame("a", [BonePresence("a","head",(0,0,0))])
    s.ingest_skeleton_frame("a", [BonePresence("a","head",(3,0,0))])
    s.ingest_object(ObjectPresence("p","prop",(0,0,0)))
    s.ingest_object(ObjectPresence("p","prop",(4,0,0)))
    assert {b.center for b in s.bubbles.values() if b.bones} == {(3,0,0)}
    assert {b.center for b in s.bubbles.values() if b.objects} == {(4,0,0)}
    s.configure(BubbleGridConfig("other"))
    assert not s.build_stat().actors_seen


def test_giant_bounds_rejected_before_state_changes():
    engine = BubbleStackEngine(BubbleConfig(occupancy_scan_limit=50))
    huge = FrameObject("huge", AABB(Vec3(0,0,0), Vec3(1e7,1e7,1e7)))
    with pytest.raises(RuntimeError, match="too many roots"):
        engine.step([huge])
    assert engine.time_seconds == 0 and not engine.objects and not engine.stack.roots


def test_invalid_dt_and_duplicate_ids_leave_state_untouched():
    engine = BubbleStackEngine()
    obj = FrameObject("a", AABB(Vec3(0,0,0), Vec3(.1,.1,.1)))
    for dt in (0, -1, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            engine.step([obj], dt)
    with pytest.raises(ValueError, match="duplicate"):
        engine.step([obj,obj])
    assert engine.time_seconds == 0 and not engine.objects


def test_grid_rejects_unrepresentable_spacing():
    with pytest.raises(ValueError, match="spacing must advance"):
        BubbleStack(BubbleGridConfig("bad", origin=(1e20,0,0), spacing=1))


def test_pending_events_are_bounded_and_loss_is_reported():
    from modules.bubble_stack import MAX_PENDING_EVENTS
    s = BubbleStack(BubbleGridConfig("r"))
    for i in range(MAX_PENDING_EVENTS + 10):
        s._append_event({"type": "test", "i": i})
    assert len(s._events) == MAX_PENDING_EVENTS
    stat = s.build_stat()
    assert stat.meaningful_events[0]["type"] == "bubble_event_backlog_dropped"
    assert stat.meaningful_events[0]["count"] >= 10


def test_bad_skeleton_preserves_previous_occupancy():
    s = BubbleStack(BubbleGridConfig("r", radius=.5))
    s.ingest_skeleton_frame("a", [BonePresence("a", "head", (0,0,0))])
    with pytest.raises(ValueError):
        s.ingest_skeleton_frame("a", [BonePresence("b", "head", (3,0,0))])
    assert {b.center for b in s.bubbles.values() if b.bones} == {(0,0,0)}
