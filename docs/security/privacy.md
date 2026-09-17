# Privacy: what ends up in traces, and what does not

Traces are evidence. Evidence is only useful if it is complete, and only
safe if it is bounded and free of secrets. ATP is **not** a data-loss-
prevention system: it records what agents attempted; it does not classify
or scrub the content of those attempts.

## What is recorded

| Field | Bound | Notes |
|---|---|---|
| Envelope arguments | 16 KiB canonical JSON (proxy refuses > 15 KiB) | Full values: this is what argument-aware decisions and regression cases need. Do not route secrets through tool arguments |
| Provenance: task description, rationale | 2,000 / 4,000 chars | Free text from the agent side; untrusted |
| Provenance: content sources | hash always; excerpt ≤ 2,000 chars, optional | The excerpt is the only place external document text can enter a trace |
| Decision, evaluations, constraint values | — | Derived values; may echo arguments (e.g. amount, destination) |
| Upstream result | 200-char text preview + content types | Never the full result |
| Credential id | — | Never the secret |
| Grant id | — | Never the token |

## What is never recorded

Agent bearer secrets, execution grant tokens, the operator key, gateway
signing keys, upstream secrets from `upstream.env`/`headers_env`. Tests:
`test_secrets_never_appear_in_responses_or_traces`,
`test_bundle_never_contains_tokens_or_keys`.

## Redaction

- **Evidence export** drops content-source excerpts and the agent's
  rationale by default (`--include-excerpts` to keep them) and lists the
  redactions in the bundle. Hash-chained events are kept verbatim so the
  chain verifies; the bundle says so.
- **Regression recording** drops provenance entirely (a case carries the
  action and the expected decision, nothing about how it was proposed).
- **No redaction hook** exists at append time; adding one is a `TraceStore`
  wrapper (roadmap; `docs/security/trace-integrity.md` for the same hook).

## The dashboard

The operator dashboard renders envelope arguments, provenance excerpts and
decision messages as text (React escapes them; no HTML/Markdown rendering).
It stores the operator key in a module variable for the page lifetime,
never in `localStorage`. Anyone with the operator key sees everything
above.

## Recommendations

1. Keep secrets out of tool arguments (the tool should read them from its
   own environment; with the proxy, from `upstream.env`).
2. Scope `.atp/` permissions: it contains the operator key and every
   recorded argument.
3. Prefer content hashes to excerpts in provenance unless a reviewer needs
   the text.
4. Export bundles rather than the database when sharing evidence.
