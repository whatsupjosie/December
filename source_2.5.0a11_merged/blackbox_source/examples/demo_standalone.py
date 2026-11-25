from pathlib import Path

from blackbox_plugin import BlackBoxPlugin

root = Path("demo_blackbox_data")
plugin = BlackBoxPlugin(root, "demo-session", checkpoint_every_events=2)
plugin.record(
    event_type="ai.tool_requested",
    source="demo_agent",
    actor="ai:demo",
    subject_id="tool-request:1",
    operation_id="demo-operation-1",
    payload={"action": "inspect", "status": "requested"},
    channel="ACT",
    event_code="TCR",
)
plugin.record(
    event_type="approval.approved",
    source="demo_host",
    actor="human:owner",
    subject_id="tool-request:1",
    operation_id="demo-operation-2",
    payload={"decision": "approved", "status": "complete"},
    channel="APP",
    event_code="APR",
)
print(plugin.closed_summary())
print(plugin.known_record_report())
plugin.seal("demo complete")
