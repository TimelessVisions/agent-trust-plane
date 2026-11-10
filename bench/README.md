# atp-bench

Model-free replay benchmark for agent-trust-plane over AgentDojo suites.
A separate uv project (not a root workspace member) so AgentDojo's heavy
dependencies never touch the root `uv.lock`.

Run: `cd bench && uv run pytest`

`atp_bench/dojo.py` is the only module that imports `agentdojo` (pinned
`agentdojo==0.1.35`, benchmark version `v1.2.1`).

## Observed suite sizes (benchmark v1.2.1)

| suite     | user tasks | injection tasks |
|-----------|-----------:|----------------:|
| workspace | 40 | 14 |
| travel    | 20 | 7  |
| banking   | 16 | 9  |
| slack     | 21 | 5  |
