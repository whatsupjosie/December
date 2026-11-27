"""VoxelStudio <-> Filler Cream hookup (2026-11-08)."""
from __future__ import annotations

import json
import struct

import pytest

from modules.filler_cream import FillerCreamError, FillerSelection, FillerStore, bake_with_filler
from modules.filler_cream_fixture import S, build_fixture_object, fixture_annotations
from modules.voxel_studio import VoxelBaker, VoxelStudio

STEPS = frozenset({"P0", "P1", "P2", "P3"})


@pytest.fixture()
def studio(tmp_path):
    st = VoxelStudio(tmp_path)
    st.save_object(build_fixture_object())
    return st


def test_bake_without_cream_is_unchanged(studio):
    obj = studio.get_object("filler_cream_fixture")
    path = studio.bake_object(obj.object_id)
    assert path.read_bytes() == VoxelBaker().bake(obj)


def test_baked_glb_json_is_valid_for_strict_readers(studio):
    obj = studio.get_object("filler_cream_fixture")
    for length in range(1, 5):
        obj.name = "a" * length
        studio.save_object(obj)
        glb = studio.bake_object(obj.object_id).read_bytes()
        size, chunk_type = struct.unpack_from("<II", glb, 12)
        assert chunk_type == 0x4E4F534A
        assert size % 4 == 0
        assert json.loads(glb[20:20 + size])["nodes"][0]["name"] == obj.name


def test_apply_bake_and_reload_after_restart(studio, tmp_path):
    oid = "filler_cream_fixture"
    layer = studio.apply_filler(oid, "steps", FillerSelection(STEPS), fixture_annotations())
    assert layer.cells
    obj = studio.get_object(oid)
    pieces, _ = FillerStore(annotations=fixture_annotations()).pieces(obj)
    expected = bake_with_filler(obj, [layer], pieces=pieces)
    assert studio.bake_object(oid).read_bytes() == expected
    reopened = VoxelStudio(tmp_path)                          # survives a restart
    assert reopened.filler_status(oid) == {"steps": "current"}
    assert reopened.bake_object(oid).read_bytes() == expected


def test_editing_the_object_regenerates_cream_at_bake(studio):
    oid = "filler_cream_fixture"
    studio.apply_filler(oid, "steps", FillerSelection(STEPS), fixture_annotations())
    before = studio.bake_object(oid).read_bytes()
    obj = studio.get_object(oid)
    p1 = next(p for p in obj.primitives if p.primitive_id == "P1")
    p1.position = (p1.position[0], p1.position[1] + 2 * S / 128, p1.position[2])
    studio.save_object(obj)
    assert studio.filler_status(oid) == {"steps": "stale"}
    after = studio.bake_object(oid).read_bytes()               # regenerates, then bakes
    assert after != before
    assert studio.filler_status(oid) == {"steps": "current"}   # and keeps the regenerated cream


def test_cream_that_cannot_regenerate_blocks_the_bake(studio, tmp_path):
    oid = "filler_cream_fixture"
    studio.apply_filler(oid, "steps", FillerSelection(STEPS), fixture_annotations())
    good = studio.bake_object(oid).read_bytes()
    obj = studio.get_object(oid)
    obj.primitives = [p for p in obj.primitives if p.primitive_id != "P1"]   # a selected piece is gone
    studio.save_object(obj)
    with pytest.raises(FillerCreamError):
        studio.bake_object(oid)
    assert (tmp_path / "bakes" / f"{oid}.glb").read_bytes() == good, "the last good bake is untouched"
    assert studio.bake_all() == 0                              # bake_all reports it as a failure
    assert studio.remove_filler(oid, "steps")
    assert studio.bake_object(oid).read_bytes() == VoxelBaker().bake(obj)


def test_failed_write_leaves_the_old_cream_file_intact(studio, tmp_path, monkeypatch):
    import os
    oid = "filler_cream_fixture"
    studio.apply_filler(oid, "steps", FillerSelection(STEPS), fixture_annotations())
    path = tmp_path / "filler" / f"{oid}.json"
    saved = path.read_text()

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        studio.apply_filler(oid, "more", FillerSelection(frozenset({"Q0", "Q1"})))
    assert path.read_text() == saved and not path.with_name(path.name + ".tmp").exists()
    assert json.loads(saved)["kind"] == "filler_cream_store"


def test_deleting_the_object_deletes_its_cream(studio, tmp_path):
    oid = "filler_cream_fixture"
    studio.apply_filler(oid, "steps", FillerSelection(STEPS), fixture_annotations())
    assert (tmp_path / "filler" / f"{oid}.json").exists()
    assert studio.delete_object(oid)
    assert not (tmp_path / "filler" / f"{oid}.json").exists()
    assert studio.filler_status(oid) == {}
    with pytest.raises(FillerCreamError):
        studio.apply_filler(oid, "steps", FillerSelection(STEPS))


@pytest.mark.parametrize("with_cream", [False, True])
def test_interrupted_rebake_preserves_published_glb(studio, monkeypatch, with_cream):
    from contextlib import contextmanager
    from pathlib import Path

    oid = "filler_cream_fixture"
    if with_cream:
        studio.apply_filler(oid, "steps", FillerSelection(STEPS), fixture_annotations())
    path = studio.bake_object(oid)
    expected = path.read_bytes()
    before = set(path.parent.iterdir())
    original_open = Path.open

    @contextmanager
    def interrupted_open(target, mode, *args, **kwargs):
        with original_open(target, mode, *args, **kwargs) as stream:
            class InterruptedWriter:
                def write(self, data):
                    stream.write(data[:12])
                    raise OSError("interrupted GLB write")
            yield InterruptedWriter()

    def open_for_test(target, mode="r", *args, **kwargs):
        if target.parent == path.parent and mode in {"wb", "xb"}:
            return interrupted_open(target, mode, *args, **kwargs)
        return original_open(target, mode, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", open_for_test)
        with pytest.raises(OSError, match="interrupted GLB write"):
            studio.bake_object(oid)
    assert path.read_bytes() == expected
    assert set(path.parent.iterdir()) == before
    assert studio.bake_object(oid).read_bytes() == expected
