# BlackBox Client Contract — bbx1-client/1

The public client exposes:

- `capabilities()`
- `submit(EvidenceEvent)`
- `status()`
- `verify_receipt()`
- `verify()`
- `iter_records()`

The current implementation is `LocalBlackBoxClient`, which wraps one standalone `BlackBoxPlugin` instance. The interface intentionally excludes direct evidence-file paths and host policy.

Receipt verification checks the claimed record ID, event hash, and sequence against a fully verified canonical chain.
