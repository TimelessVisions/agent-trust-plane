# Benchmark: authorization overhead per tool call

Generated 2026-09-17T04:25:09+00:00 at commit `444353a` by `benchmarks/authz_overhead.py`.

## Environment

- Windows-11-10.0.26200-SP0
- Python 3.14.6, CPU: Intel64 Family 6 Model 165 Stepping 2, GenuineIntel (12 logical cores)
- Everything on one machine; HTTP is loopback; MCP is stdio subprocesses.

## Method

- 30 warm-up iterations discarded, then n=300 timed iterations per row, sequential (no concurrency).
- A: resolve a 2-link delegation chain and evaluate the 8-policy `payments-v2` set on a $480 envelope.
- B/C: full `/authorize` + `/execute` round trip for the same envelope (grant minted, verified, consumed; ledger written).
- D/E: the same `write_note` MCP call, directly to the notes server vs. through the proxy (which adds authorize + execute + outcome report over loopback HTTP).
- Timings are wall-clock `perf_counter` around the call as seen by the caller.

## Results (milliseconds)

| scenario | n | mean | p50 | p95 | p99 | min | max |
|---|---:|---:|---:|---:|---:|---:|---:|
| A. policy engine + chain resolution (in-process) | 300 | 0.32 | 0.30 | 0.35 | 0.54 | 0.30 | 0.65 |
| B. gateway authorize+execute (in-process ASGI) | 300 | 18.61 | 18.27 | 21.41 | 24.39 | 16.11 | 32.75 |
| C. gateway authorize+execute (HTTP loopback) | 300 | 10.77 | 10.69 | 12.74 | 15.32 | 8.90 | 16.14 |
| D. MCP write_note, direct (stdio) | 300 | 3.18 | 3.08 | 3.93 | 4.67 | 2.76 | 5.62 |
| E. MCP write_note via proxy + gateway | 300 | 25.03 | 24.07 | 30.09 | 33.91 | 20.86 | 37.43 |

End-to-end overhead of the proxy on an MCP tool call (E minus D, p50): **20.99 ms**; the two gateway round trips alone (C, p50): **10.69 ms**.

## Limitations

- Single machine, single client, sequential calls. No concurrency, no network latency, no TLS.
- SQLite in-memory stores; a persistent database will be slower.
- The notes server is trivial; a real tool's own latency dominates in practice.
- No comparison to other gateways is made; this measures our overhead only.
- Resource consumption was not measured.

Reproduce: `uv run python benchmarks/authz_overhead.py --n 300 --out docs/benchmarks.md`
