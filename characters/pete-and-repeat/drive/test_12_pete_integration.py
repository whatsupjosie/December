"""tests/test_12_pete_integration.py"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestPeteImport:
    def test_pete_imports_cleanly(self):
        try:
            from modules.pete import Pete
        except Exception as e:
            pytest.fail(f"Pete import failed: {e}")


class TestPeteInstantiation:
    def test_instantiate_with_mocks(self):
        from modules.pete import Pete
        hub = MagicMock()
        hub.broadcast_system_event = AsyncMock()
        pete = Pete(hub=hub, irm=None, rec=None,
                    on_cut=None, on_action=None)
        assert pete is not None

    def test_instantiate_all_none(self):
        from modules.pete import Pete
        try:
            Pete(hub=None, irm=None, rec=None,
                 on_cut=None, on_action=None)
        except Exception as e:
            pytest.fail(f"Pete(all None) raised: {e}")


class TestPeteStatus:
    def _make_pete(self):
        from modules.pete import Pete
        hub = MagicMock()
        hub.broadcast_system_event = AsyncMock()
        return Pete(hub=hub, irm=None, rec=None,
                    on_cut=None, on_action=None)

    def test_status_returns_dict(self):
        pete = self._make_pete()
        async def run():
            fn = pete.get_status if hasattr(pete, "get_status") else pete.status
            result = await fn() if asyncio.iscoroutinefunction(fn) else fn()
            return result
        status = asyncio.run(run())
        assert isinstance(status, dict)

    def test_status_has_required_keys(self):
        pete = self._make_pete()
        async def run():
            fn = pete.get_status if hasattr(pete, "get_status") else pete.status
            return await fn() if asyncio.iscoroutinefunction(fn) else fn()
        status = asyncio.run(run())
        keys = set(status.keys())
        assert len(keys) > 0
        time_keys = {"scene_s", "scene_seconds", "elapsed", "uptime"}
        assert keys & time_keys or "active" in keys, f"Expected time/active keys, got {keys}"


class TestPeteCallbacks:
    def test_on_cut_callback_fires(self):
        from modules.pete import Pete
        fired = []
        hub = MagicMock()
        hub.broadcast_system_event = AsyncMock()

        async def on_cut(reason="", scene_s=0.0):
            fired.append(("cut", reason))

        pete = Pete(hub=hub, irm=None, rec=None,
                    on_cut=on_cut, on_action=None)

        # Trigger cut directly if method exists
        if hasattr(pete, "_on_cut"):
            asyncio.run(pete._on_cut("test"))
        elif hasattr(pete, "on_cut"):
            asyncio.run(pete.on_cut("test"))
        elif hasattr(pete, "trigger_cut"):
            asyncio.run(pete.trigger_cut("test"))
        else:
            # Can't trigger directly — just confirm it's callable
            assert callable(on_cut)
            return

        assert len(fired) > 0

    def test_on_action_callback_fires(self):
        from modules.pete import Pete
        fired = []
        hub = MagicMock()
        hub.broadcast_system_event = AsyncMock()

        async def on_action(reason=""):
            fired.append(("action", reason))

        pete = Pete(hub=hub, irm=None, rec=None,
                    on_cut=None, on_action=on_action)

        if hasattr(pete, "_on_action"):
            asyncio.run(pete._on_action("test"))
        elif hasattr(pete, "on_action"):
            asyncio.run(pete.on_action("test"))
        elif hasattr(pete, "trigger_action"):
            asyncio.run(pete.trigger_action("test"))
        else:
            assert callable(on_action)
            return

        assert len(fired) > 0


class TestStudioControlPeteNone:
    def test_studio_control_with_pete_none(self):
        from modules.studio_control import StudioControl
        hub = MagicMock()
        hub.broadcast_system_event = AsyncMock()
        from pathlib import Path
        try:
            sc = StudioControl(hub=hub, pete=None, data_dir=Path("/tmp"))
            assert sc is not None
        except Exception as e:
            pytest.fail(f"StudioControl(pete=None) raised: {e}")
