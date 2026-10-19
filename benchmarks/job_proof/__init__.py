"""M4 5,000-page proof harness (design §12).

Proves the streaming job runner's invariants on a REAL synthetic PDF: flat memory (RSS slope below
a threshold, peak under a bound) and crash-safe resume (kill mid-job → recover → final done set ==
full index set, no duplicates). The invariants are proven LOCALLY at a scaled page count; the full
5,000-page run is the CI nightly gate (documented in docs/m4-verification.md), never faked.
"""
