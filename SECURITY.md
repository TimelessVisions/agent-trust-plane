# Security policy

Agent Trust Plane is experimental (v0.3.1). It has had a documented
self-review (`docs/security/security-review.md`), a red-team pass
(`docs/red-team/architecture-attacks.md`) and no independent audit. Do not deploy it in
front of real money or production systems without reading
`docs/security/threat-model.md` and `docs/security/deployment.md`.

## Supported versions

| Version | Supported |
|---|---|
| `main` / latest tagged release | yes |
| anything older | no |

## Reporting a vulnerability

Please do **not** open a public issue for a security problem.

Use GitHub's private vulnerability reporting on this repository ("Security"
tab → "Report a vulnerability") once the repository is public. Until then,
contact the maintainer directly (address in the commit log).

Include: what you did, what you expected, what happened, and a minimal
reproduction (a failing test in `services/gateway/tests/` is ideal). You will
get an acknowledgement within 7 days and a fix or a documented decision
within 30 days for anything that undermines a property listed in
`docs/architecture/design-principles.md`.

## In scope

Anything that lets an action execute without the intended authorization:
identity or credential bypass, delegation widening, grant forgery or reuse,
policy bypass (including a declared policy file that weakens a kernel
policy), trace or evidence-bundle forgery that survives verification, secret
leakage in responses/traces/logs/bundles, path-scope escapes through the
proxy, shadow/enforce confusion, and any way for an offline analysis
(`atp test`, `policy impact`, `mutate`) to execute a tool.

## Out of scope (documented limitations)

Reaching an upstream tool without going through the gateway or proxy;
compromise of the gateway host, its database file, `.atp/keys.env`, the
operator key, or an agent's bearer token; symlinks inside a scoped
directory; denial of service; anything listed under "Findings left open" in
`docs/security/security-review.md`.
