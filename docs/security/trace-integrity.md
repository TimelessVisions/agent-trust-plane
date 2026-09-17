# Trace integrity: what the hash chain proves and what it does not

Each trace is a per-trace hash chain: every event commits to its fields and
to the previous event's hash. `GET /traces/{id}` and `atp evidence verify`
recompute the chain.

## What it proves

- **Internal consistency.** Given a set of events, nobody edited, removed
  or reordered one without recomputing every later hash.
- **Bundle consistency.** An evidence bundle carries the events, the
  integrity report and a hash over the whole bundle; a reviewer can check
  both offline (`atp evidence verify`). The red-team tests show that
  editing a decision, an event payload, the event order or the head hash
  is detected.

## What it does not prove

- **Authorship.** The chain is unsigned. Anyone who can write the SQLite
  file can recompute a self-consistent history (security review O4/O5).
- **Completeness.** A trace that was deleted entirely leaves no gap: chains
  are per trace, and there is no global sequence commitment.
- **Time.** Timestamps are the gateway clock's claims.

## The realistic path to stronger evidence

Ordered by effort; none is implemented in v0.3.0.

1. **Signed trace heads.** The gateway signs each trace head with a key
   the DB writer does not have (Ed25519, key in a KMS or HSM). A forged
   history then needs the signing key, not just DB access. Cost: one
   signature per event, key management. This is the first thing to build
   when a deployment needs evidence that survives an insider with DB
   access.
2. **External checkpointing.** Periodically write the set of (trace_id,
   head_hash) to a place the gateway cannot rewrite: an append-only bucket
   with object lock, a ticket, a log service. Detects deletion and
   rewriting after the checkpoint. Cost: an exporter and a store.
3. **Transparency log.** Append heads to a Merkle-tree log (a Trillian or
   Sigstore-Rekor-style service). Provides inclusion proofs to third
   parties. Cost: an external service.
4. **WORM storage for events.** Stream events to write-once storage at
   append time. Detects everything above and needs no crypto beyond the
   chain. Cost: storage and an exporter.

The exporter hook for 2 and 4 is the `TraceStore` protocol: a wrapping
store that forwards `append` to a sink is ~40 lines and is a good first
issue.

## Why signed heads were not shipped now

Signing helps only when the signing key is separated from the process
that writes the DB. In the local-first `atp mcp wrap` deployment they are
the same process on the same machine, so a signature would add
ceremony without a threat model it defeats. It becomes worthwhile with a
separate gateway service and a KMS, which is the `atp serve` deployment
the roadmap targets.
