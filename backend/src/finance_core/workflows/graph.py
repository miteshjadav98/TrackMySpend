"""Graph assembly only. Behaviour lives in nodes.py and its helpers.

    START -> understand --+--> prepare_record <--> clarify (interrupt)
                          |         |                 |
                          |         +--> save --------+--> respond -> END
                          +--> summarize ----------------> respond
                          +--> search -------------------> respond
                          +------------------------------> respond

Node names and state keys are persisted in checkpoints: renaming one is a migration
(bump GRAPH_VERSION, route new threads to the new graph, let old ones drain).
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy
from sqlalchemy.exc import InterfaceError, OperationalError

from finance_core.workflows.nodes import FinanceNodes
from finance_core.workflows.state import AgentDeps, FinanceState, GraphInput, TurnContext

GRAPH_VERSION = "finance-v1"

# Only idempotent nodes retry, and only on transient database failures.
_DB_RETRY = RetryPolicy(
    max_attempts=3,
    initial_interval=0.3,
    backoff_factor=2.0,
    jitter=True,
    retry_on=(OperationalError, InterfaceError),
)


def build_graph(deps: AgentDeps) -> StateGraph[FinanceState, TurnContext, GraphInput, FinanceState]:
    nodes = FinanceNodes(deps)
    builder: StateGraph[FinanceState, TurnContext, GraphInput, FinanceState] = StateGraph(
        FinanceState, context_schema=TurnContext, input_schema=GraphInput
    )
    builder.add_node(
        "understand",
        nodes.understand,
        destinations=("prepare_record", "summarize", "search", "respond"),
    )
    builder.add_node(
        "prepare_record", nodes.prepare_record, destinations=("clarify", "save", "respond")
    )
    builder.add_node(
        "clarify", nodes.clarify, destinations=("prepare_record", "understand", "respond")
    )
    builder.add_node("save", nodes.save, retry_policy=_DB_RETRY)
    builder.add_node("summarize", nodes.summarize, retry_policy=_DB_RETRY)
    builder.add_node("search", nodes.search, retry_policy=_DB_RETRY)
    builder.add_node("respond", nodes.respond)

    builder.add_edge(START, "understand")
    builder.add_edge("save", "respond")
    builder.add_edge("summarize", "respond")
    builder.add_edge("search", "respond")
    builder.add_edge("respond", END)
    return builder
