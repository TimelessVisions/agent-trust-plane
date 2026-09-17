# Design principles

These are the rules the code is held to. When a change violates one, the
change is wrong or the principle needs an ADR.

## 1. Models propose. Infrastructure decides.

No component that produces a proposal may also decide whether it executes.
The agent, its prompt, its "reflection" step, and its self-assessment are all
input. The decision is made by code that reads none of them as authority.

## 2. Nothing the agent says about its authority is believed.

An envelope names a grant id. That is the only thing about authority the
gateway reads from the client. Everything else — capabilities, limits,
expiry, who delegated to whom — comes from the gateway's own store.

## 3. Authority only narrows.

A delegation can restrict what its parent holds; it can never widen it. This
is enforced twice: when a grant is issued and when a chain is resolved. If the
two ever disagree, resolution wins, because resolution is what the decision
is made from.

## 4. Decisions are explainable by construction.

A decision is `outcome + reason code + matched policy + the constraints that
were compared`. There is no "the model felt unsafe". Every policy returns a
typed evaluation, every applicable policy is evaluated even after the first
denial, and all of it is written to the trace. If you cannot point at the
policy and the numbers, the decision does not exist.

## 5. Authorization is bound to execution.

An ALLOW is not a flag; it is a signed, single-use, short-lived grant bound
to the hash of the exact action that was authorized. Executing something
else, executing twice, executing late, or executing without asking are all
distinct, tested failure modes with their own reason codes.

## 6. The trace is the product.

Every step appends an event to a hash-chained log. The dashboard, the evals,
and replay all read from the trace, not from in-memory state. If it is not in
the trace, it did not happen; if it is in the trace, it can be replayed.

## 7. Evals exercise real code paths.

An eval calls the same HTTP routes an agent would, records the trace ids it
produced, and asserts on decisions, reason codes, and the ledger. A scenario
with no checks is a FAIL. A scenario that crashes is an ERROR, never a PASS.
There is no "demo mode".

## 8. Untrusted content is labelled at the boundary.

Anything retrieved from outside — documents, email, web pages, tool output —
enters the trace as an `external_content_ingested` event with a trust label
and a content hash before the agent acts on it. Provenance answers "what
influenced this?" without trusting the agent's account of it.

## 9. Small, typed, boring.

Pydantic models with `extra="forbid"`, Decimals for money, string enums for
reason codes, Protocols for stores, one lock where one lock is enough. No
framework where a function will do. Every package can be read in one sitting.

## 10. Say what is not handled.

The threat model has two tables. The second one is the more important. A
security claim that is not backed by a test in this repository should not be
in the README.
