"""Accounts-payable demo agent that acts only through the trust plane."""

from finance_agent.agent import AgentBrain, AnthropicAgent, ProposedAction, SimulatedAgent
from finance_agent.invoices import (
    INJECTED_INVOICE,
    LEGITIMATE_INVOICE,
    UNDER_LIMIT_INJECTED_INVOICE,
    Invoice,
)
from finance_agent.runner import DEFAULT_TASK, AgentRunResult, run_accounts_payable
from finance_agent.scenario import (
    AP_AGENT,
    DOC_AGENT,
    HUMAN,
    ORCHESTRATOR,
    AgentIdentities,
    DelegationGraph,
    DemoSeed,
    issue_agent_credentials,
    seed_delegation_graph,
)

__all__ = [
    "AP_AGENT",
    "DEFAULT_TASK",
    "DOC_AGENT",
    "HUMAN",
    "INJECTED_INVOICE",
    "LEGITIMATE_INVOICE",
    "ORCHESTRATOR",
    "UNDER_LIMIT_INJECTED_INVOICE",
    "AgentBrain",
    "AgentIdentities",
    "AgentRunResult",
    "AnthropicAgent",
    "DelegationGraph",
    "DemoSeed",
    "Invoice",
    "ProposedAction",
    "SimulatedAgent",
    "issue_agent_credentials",
    "run_accounts_payable",
    "seed_delegation_graph",
]
