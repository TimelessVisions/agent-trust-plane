# Deployment requirements

Agent Trust Plane is an experimental MVP. This page says what a deployment
must provide for the guarantees in the threat model to mean anything. If you
cannot meet a line here, the corresponding guarantee does not hold.

## Non-negotiable

1. **Tools are reachable only from the gateway.** The gateway is the boundary;
   a tool that agents can reach directly has no boundary. Enforce it with
   network policy (tool endpoints accept connections only from the gateway)
   and with tool-side credentials that only the gateway holds. The
   in-process `PaymentsTool` in this repo is a stand-in and is deliberately
   unprotected (`test_in_process_tool_call_is_not_protected`).
2. **Keys are explicit and secret.** `ATP_OPERATOR_KEY` (≥ 32 chars) and the
   Ed25519 grant key (`ATP_GRANT_KEYS_DIR` + `ATP_GRANT_SIGNING_KID`; the
   private key is `grant-<kid>.key`, mode 600) come from `atp keygen --write
   .env`. They live in a secret store or a mode-600 `.env` and key directory
   that are never committed. The gateway refuses to start a persistent
   database without them, and refuses a 0.3 HMAC `ATP_GRANT_SIGNING_KEY`.
   Rotate the grant key with `atp keygen --rotate --env .env` (or `atp keygen
   --rotate` for an ATP home) and restart; grants signed by the old key keep
   verifying for one grant TTL.
3. **The operator key is held by the operator only.** It is omnipotent (see
   `docs/security/security-review.md` O1). Agents never receive it. The dashboard is
   an operator tool and asks for it; do not embed it in the dashboard build.
4. **Agent credentials are issued per agent, with an expiry, and revoked
   when the agent is retired or suspected compromised.** A bearer token is
   the agent until then.
5. **TLS in front of the gateway.** Bearer tokens and the operator key travel
   in headers. Terminate TLS at a reverse proxy; bind uvicorn to localhost or
   a private interface.
6. **CORS origins are exact.** `ATP_CORS_ORIGINS` lists the dashboard origin
   only.
7. **Database file permissions.** The SQLite file holds credential hashes,
   grants, and the audit chain. Mode 600, owned by the gateway user, on a
   volume the agents cannot read.

## MCP proxy deployments

- The proxy must be the **only** thing able to launch or reach the upstream
  server. Run upstreams as the proxy's child processes with no other
  listener, or behind a socket only the proxy user can open.
- Give the proxy its own agent credential with a short `expires_at`; revoke
  it when the agent host is rotated.
- One proxy per upstream per agent identity. Do not share a proxy between
  agents; the envelope names one agent and the credential must match.
- Keep `expose_unmapped_tools: false` unless you are mapping a new upstream.

## Strongly recommended

- Ship trace events to an append-only sink and periodically anchor the chain
  head hash somewhere the gateway cannot write (a ticket, a signed log, a
  transparency log). Without this, the hash chain only catches naive edits.
- Run the gateway as its own service account with no access to agent hosts.
- Keep `ATP_GRANT_TTL_SECONDS` short (default 120 s).
- Put rate limiting in the reverse proxy; the gateway has none.
- Rotate the operator key by restarting with a new value; rotate agent
  credentials by issuing a new one and revoking the old.

## Not provided by this MVP

- Agent-to-gateway mutual TLS or proof-of-possession tokens.
- Per-human identity (the operator stands in for all humans).
- Multi-node coordination (one in-process lock; use one gateway instance).
- An approval workflow for `REQUIRE_APPROVAL`.
- Any real payment rail. The ledger is a local table.
