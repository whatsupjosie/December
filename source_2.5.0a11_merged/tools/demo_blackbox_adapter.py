from pathlib import Path

from blackbox_plugin import BlackBoxPlugin
from iteration_wallet_blackbox import DurableOutbox, WalletBlackBoxConnector, WalletFact

plugin = BlackBoxPlugin(Path("demo_wallet_blackbox"), "wallet-demo")
connector = WalletBlackBoxConnector(DurableOutbox("demo_wallet_blackbox/wallet_outbox.jsonl"), plugin)
connector.submit(
    WalletFact(
        event_type="CANDIDATE_ADDED",
        actor="human:owner",
        object_id="candidate:1",
        project_id="project:demo",
        operation_id="wallet-demo-operation-1",
        payload={"state": "candidate"},
        session_id="wallet-demo",
    ),
    require_ack=True,
)
print(plugin.object_history("candidate:1"))
