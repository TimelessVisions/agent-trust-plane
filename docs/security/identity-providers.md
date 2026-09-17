# Identity providers

Every agent-facing call is authenticated by one `IdentityProvider`
(`atp_identity.provider`). The provider answers "which agent, under which
credential id?" from request **headers**; the kernel then binds the
envelope's `agent`, the delegation chain's leaf and the execution grant's
audience to that answer, and re-checks liveness under the service lock.
Identity never comes from the envelope (`test_alternative_provider_drives_binding`
shows a second implementation driving the same binding).

```python
class IdentityProvider(Protocol):
    name: str
    def authenticate(self, headers: Mapping[str, str], *, now: datetime) -> AuthenticatedAgent: ...
    def is_live(self, credential_id: str, *, now: datetime) -> bool: ...
```

## Shipped: bearer credentials

`BearerCredentialProvider`: `Authorization: Bearer atpa_<id>.<secret>`,
SHA-256 at rest, constant-time compare, per-credential expiry and
revocation, operator-issued. Adequate for a local deployment and for CI.
Known weaknesses: a stolen token *is* the agent until revoked or expired;
no sender binding; no rotation protocol (security review O2).

## Designed, not built

| Provider | How it would map | Notes |
|---|---|---|
| **mTLS / SPIFFE** | `authenticate` reads the client certificate's SPIFFE ID (from the TLS terminator's header, e.g. `X-Forwarded-Client-Cert`, or from the ASGI scope); `credential_id` = SVID serial; `is_live` = not before/after + revocation list | Proof of possession comes from TLS; no bearer secret; the reverse proxy must strip client-supplied headers |
| **OIDC client credentials (workload identity)** | JWT bearer with `sub` = agent id, `jti` = credential id, issuer keys via JWKS; `is_live` = `exp`, optional revocation via `jti` denylist | Bearer; pair with DPoP for sender binding |
| **DPoP-bound tokens** | As OIDC plus a `DPoP` proof header bound to the request method/URL and a key the agent holds | Makes token theft insufficient; requires the agent runtime to sign each request |
| **Signed requests (HTTP Message Signatures, RFC 9421)** | `Signature-Input`/`Signature` headers over method, path and body digest; key registered per agent | Strongest binding; body digest also prevents envelope substitution in transit |

Selecting a provider is a `TrustPlane(identity=...)` argument today;
configuration from settings (`ATP_IDENTITY_PROVIDER`) is roadmap.

## What stays the same regardless of provider

- The operator key is a separate credential kind and never authenticates
  an agent.
- `AuthenticatedAgent.agent` must equal `envelope.agent`, the chain leaf
  and the grant audience.
- Liveness is re-checked under the lock on authorize, execute, provenance
  writes and outcome reports.
- Human principals do not hold agent credentials; human authority is
  represented by operator-issued root grants (per-human signed authority is
  O11).
