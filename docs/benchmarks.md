# Benchmark: authorization overhead per tool call

Generated 2026-09-17T11:10:22+00:00 at commit `f707ee2` by `benchmarks/authz_overhead.py`.

## Environment

- Windows-11-10.0.26200-SP0
- Python 3.14.6, CPU: Intel64 Family 6 Model 165 Stepping 2, GenuineIntel (12 logical cores)
- Everything on one machine; HTTP is loopback; MCP is stdio subprocesses.

## Method

- 30 warm-up iterations discarded, then n=300 timed iterations per row, sequential (no concurrency). `cold` is the first call after process start.
- A1-A6: kernel components in isolation (see the module docstring).
- B/B2/C: full `/authorize` + `/execute` round trip for a $480 payment envelope (grant minted, verified, consumed; ledger written); memory store, SQLite file, and real loopback HTTP respectively.
- D/E/F: the same `write_note` MCP call directly to the notes server, through `atp mcp proxy` + a loopback gateway, and through `atp mcp wrap` (gateway in-process, persistent SQLite).
- Persistent rows (A6, B2, F) use SQLite in WAL mode with the default `synchronous=FULL`; the kernel commits one transaction per operation (authorize, execute, outcome), so a proxied call costs three fsyncs, not one per event.
- Timings are wall-clock `perf_counter` around the call as seen by the caller.

## Results (milliseconds)

| scenario | n | mean | p50 | p95 | p99 | min | max | cold |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A1. delegation chain resolution (2 links, memory) | 300 | 0.03 | 0.03 | 0.03 | 0.04 | 0.03 | 0.08 | 0.07 |
| A2. policy engine (8 policies, payments-v2) | 300 | 0.26 | 0.25 | 0.30 | 0.45 | 0.25 | 0.48 | 0.57 |
| A3. grant mint (HMAC-SHA256) | 300 | 0.03 | 0.03 | 0.03 | 0.05 | 0.03 | 0.05 | 0.13 |
| A4. grant verify | 300 | 0.06 | 0.06 | 0.07 | 0.09 | 0.06 | 0.13 | 0.13 |
| A5. audit append (memory) | 300 | 0.11 | 0.11 | 0.18 | 0.22 | 0.08 | 0.45 | 0.37 |
| A6. audit append (SQLite file, WAL) | 300 | 1.64 | 1.53 | 2.63 | 3.17 | 1.27 | 5.62 | 1.82 |
| B. gateway authorize+execute (in-process ASGI) | 300 | 15.86 | 15.51 | 17.26 | 20.54 | 13.89 | 74.64 | 14.86 |
| B2. gateway authorize+execute (in-process ASGI, SQLite file) | 300 | 18.86 | 18.40 | 20.78 | 27.08 | 17.47 | 34.01 | 18.88 |
| C. gateway authorize+execute (HTTP loopback) | 300 | 10.81 | 10.67 | 12.72 | 13.72 | 8.96 | 16.23 | 8.93 |
| D. MCP write_note, direct (stdio) | 300 | 3.02 | 2.99 | 3.33 | 3.47 | 2.75 | 3.93 | 140.88 |
| E. MCP write_note via proxy + gateway (HTTP) | 300 | 24.45 | 24.36 | 27.61 | 29.05 | 20.80 | 36.00 | 174.70 |
| F. MCP write_note via atp mcp wrap (in-process gateway, SQLite) | 300 | 14.78 | 14.41 | 16.52 | 23.34 | 13.68 | 24.80 | 159.90 |

End-to-end overhead on an MCP tool call, p50: via proxy + HTTP gateway (E - D) **21.37 ms**; via `atp mcp wrap` (F - D) **11.42 ms**. The two HTTP round trips alone (C, p50): **10.67 ms**.

## Limitations

- Single machine, single client, sequential calls. No concurrency, no network latency, no TLS.
- SQLite in-memory stores; a persistent database will be slower.
- The notes server is trivial; a real tool's own latency dominates in practice.
- No comparison to other gateways is made; this measures our overhead only.
- Resource consumption was not measured.

Reproduce: `uv run python benchmarks/authz_overhead.py --n 300 --out docs/benchmarks.md`
