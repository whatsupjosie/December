# BlackBox 0.6.0a4

BlackBox is Rearview Foresight's standalone, append-only local flight recorder for host-supplied facts.

It owns:

- canonical BBX1 record validation;
- segmented append-only storage;
- operation-ID idempotency;
- crash-tail preservation;
- checkpoints and seals;
- verification;
- bounded closed views;
- append receipts;
- the neutral `bbx1-client/1` contract.

It does **not** own Wallet custody policy, Oubliette inspection policy, PubCast vocabulary, Human Intent, or trust decisions. Host adapters live with their hosts.

## CLI

```powershell
bbx1 init --storage .\bbx-data --session demo
bbx1 capabilities --storage .\bbx-data --session demo
bbx1 record --storage .\bbx-data --session demo --event-type candidate.observed --source example --actor human:owner --subject object:1 --operation-id op:1 --payload '{"state":"candidate"}'
bbx1 status --storage .\bbx-data --session demo
bbx1 verify --storage .\bbx-data --session demo
bbx1 summary --storage .\bbx-data --session demo
```

BlackBox records and verifies claims. It does not prove that a host's claim was complete, independently witnessed, or correct beyond the evidence supplied.
