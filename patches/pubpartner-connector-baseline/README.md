# PubPartner connector baseline

Moved back here from main-assembly on Nov 25 because it had not been fully proven.

What it is: the local PubPartner connector: shared connection setup, ChatGPT consent and owner-managed MCP transports, a no-key Claude handoff and Claude desktop extension, finding and starting local chat models, safer account switching and consent recovery, cartridge validation, small models kept responsive on CPU, connection readiness and local recovery. Documented in docs/PUBPARTNER_CONNECTOR.md inside the patch.

Where it came from: pre-dec branch `codex/pubpartner-connector-baseline` (2963fd0, nine commits), as merged on pre-dec's studio line in ba93c311 (Nov 22). The patch here is exactly what that merge changed in main-assembly (install merge 496d994, reverted by 0af5028). Nothing in it was changed.

What was proven: 25 of its connection tests passed (Nov 25).

What would prove the rest:
1. Run the connector itself: tests/pubpartner_core/test_connector.py and the occupied-port test in tests/test_pubpartner_connections.py. Both need the `mcp` package (the connector SDK), which the patch adds to requirements.txt and which is not installed in the cloud session.
2. Use the connection screens in a real browser: the four browser tests in tests/test_pubpartner_connections.py (connection screen and saved key, cancelled callback, choosing a local model, late ChatGPT sign-in). They need playwright and Chromium.

The patch also adds PyJWT with crypto, mcp and sse-starlette to requirements.txt.
