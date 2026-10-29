# Security and limits — the agent authorization platform

This is a developer-use description of the boundary, not a certification
and not a claim that a deployment is safe because the tests passed.
Version remains 0.3.2.

## What the proxy actually enforces

In enforce mode the proxy calls the gateway before it calls the upstream
tool. No execution grant means `session.call_tool` is not invoked. The
sandbox journal test on this line of work records that: an unauthorized
`delete_note` is absent from the upstream’s own log. Shadow mode is the
opposite and is labeled `WOULD_DENY`; it forwards the call on purpose.

The proxy serves stdio only. Whoever can launch that process is the
client. There is no transport authentication on the proxy’s own stdio.

## Bypass-resistant deployment

The decision is void if the agent can perform the same tool call without
the proxy. `test_direct_upstream_access_is_not_protected` demonstrates
that: a client that starts `notes_mcp_server` itself writes the file and
the gateway never sees the call. The proxy cannot observe that second
path. Nothing on the trace means “the agent also called the server
directly.”

These conditions have to be true in the deployment. The software does not
create them.

1. **The upstream is reachable only through the proxy.**
   - Stdio: the proxy is the parent of the upstream process, the upstream
     does not listen on a socket, and the agent host cannot spawn the same
     command (no copy of the binary, no credentials that make a second
     copy useful). The proxy does not search the host for another copy.
     That check would be a guess.
   - HTTP: the upstream accepts connections only from the proxy
     (firewall, security group, or a socket only the proxy user can open).
     Loopback is not enough on a shared machine: any local process can
     open `127.0.0.1`.
2. **Upstream credentials sit only with the proxy.** The API token or
   database password the upstream requires is in `upstream.env` or
   `upstream.headers_env` on the proxy, not in the agent’s environment
   and not in a file the agent can read. Without that secret, a second
   copy of the server cannot do the real work. This is a configuration
   pattern. There is no vault.
3. **Gateway credentials stay off the upstream.** `ATP_OPERATOR_KEY`,
   `ATP_GRANT_SIGNING_KEY`, and the agent token (`ATP_AGENT_TOKEN` unless
   `agent_token_env` says otherwise) must not be copied into
   `upstream.env`, `upstream.headers`, or `upstream.headers_env`. The
   proxy refuses to start when that copy is visible in the config.
   An upstream API token under a different variable name is allowed.
4. **The operator key is not on the agent host.** It is the operator
   credential (`docs/security/deployment.md`). Agents do not receive it.
5. **One proxy, one agent identity, one upstream.** The envelope names
   one agent and the credential must match. Do not share a proxy across
   agents.
6. **TLS in front of a remote gateway.** Bearer tokens travel in headers.
   The local stdio demo does not terminate TLS.

`docs/security/enforcing-the-boundary.md` and
`docs/security/deployment.md` are the longer forms of the same rules.

## What startup can see, and what it cannot

| Condition | What the process does |
|---|---|
| Plain HTTP upstream whose host is not loopback | Refused at config load (`UpstreamConfig`). Already tested. |
| HTTPS or any URL whose host is not loopback (`127.0.0.1`, `localhost`, `::1`, `[::1]`) | Warning on connect: the proxy cannot prove it is the only client. Not a refusal. A remote upstream can be a correct deployment when the network policy is outside this process. |
| `upstream.env` / `headers_env` / static header copies a gateway credential | `ProxyConfig` raises. `atp mcp wrap` exits 2 on `ValueError` from `load_config`. Tested in `adapters/mcp/tests/test_mapping.py`. |
| Agent can spawn the upstream binary itself | **Not detectable.** No startup check. Documented, and demonstrated by the direct-access test. |
| Firewall, mTLS, or “only the proxy’s address” | **Not detectable.** The warning is not evidence that the firewall exists. |
| Loopback HTTP upstream | Allowed. It does **not** mean other processes on the host are blocked. |

Refusing every non-loopback URL would reject a supported Streamable HTTP
upstream that is correctly isolated by something this process cannot see.
That refusal is not implemented.

## Other limits that are still true

- Hash chain is tamper-evident against a naive edit of the stored events.
  A principal who can rewrite the database and any external anchor can
  present a different chain. No external anchor ships in this repository.
- `2026-07-28` is not a supported revision. See `SCOPE.md`.
- `input_required` results are refused after the upstream call returns.
  A tool that already changed state and then asked for input has already
  run.
- The proxy does not serve Streamable HTTP.
- Third-party `@modelcontextprotocol/server-filesystem` is not measured
  in CI.
- No independent security review has been done on this tree.
- Dependency advisories and where they are reachable:
  `REUSE_DECISIONS.md`.
