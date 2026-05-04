"""Multi-agent pipeline: Researcher -> Writer -> Critic (with revision loop).

Compiled once at import time as a LangGraph StateGraph and reused per request.
Each request flows through the graph and returns both the final answer and the
intermediate trace (research notes, draft, critique) for transparency.
"""
import re
from typing import TypedDict

from langchain_groq import ChatGroq
from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_core.messages import HumanMessage
from langchain_core.messages.ai import AIMessage
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import create_react_agent


MAX_REVISIONS = 1  # Writer can be invoked up to MAX_REVISIONS+1 times total


class AgentState(TypedDict):
    user_query: str
    system_prompt: str
    allow_search: bool
    model_name: str
    research_notes: str
    draft: str
    critique: str
    needs_revision: bool
    iteration: int
    final_answer: str


def _llm(model_name: str) -> ChatGroq:
    return ChatGroq(model=model_name)


def _last_ai_content(messages) -> str:
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            return msg.content or ""
    return ""


def researcher_node(state: AgentState) -> dict:
    """Gather facts. Uses Tavily web search if allow_search=True; otherwise
    relies on the LLM's training knowledge."""
    llm = _llm(state["model_name"])

    if state["allow_search"]:
        researcher = create_react_agent(
            model=llm,
            tools=[TavilySearchResults(max_results=3)],
            prompt=(
                "You are the RESEARCHER agent in a multi-agent pipeline. "
                "Use the search tool to gather current factual information "
                "relevant to the user's query. Output a concise bulleted list "
                "of key facts and findings, with sources where possible. "
                "Do NOT write a final answer. Stop after the research notes."
            ),
        )
        result = researcher.invoke({"messages": [HumanMessage(content=state["user_query"])]})
        notes = _last_ai_content(result.get("messages", []))
    else:
        prompt = (
            "You are the RESEARCHER agent in a multi-agent pipeline. "
            "List the key facts, concepts, and considerations relevant to the "
            "following query, drawing only on your training data. Output a "
            "concise bulleted list. Do NOT write a final answer.\n\n"
            f"Query: {state['user_query']}"
        )
        notes = llm.invoke(prompt).content

    return {"research_notes": notes}


def writer_node(state: AgentState) -> dict:
    """Synthesize a draft from the research notes. On revision, also takes
    the previous draft and the critic's feedback into account."""
    llm = _llm(state["model_name"])

    style = state.get("system_prompt") or "You are a helpful assistant."

    revision_block = ""
    if state.get("critique") and state.get("draft"):
        revision_block = (
            "\n\nPREVIOUS DRAFT:\n"
            f"{state['draft']}\n\n"
            "CRITIC FEEDBACK ON THAT DRAFT:\n"
            f"{state['critique']}\n\n"
            "Address the critic's feedback in your new draft."
        )

    prompt = (
        f"Persona / style guidance: {style}\n\n"
        "You are the WRITER agent in a multi-agent pipeline. Use the research "
        "notes below to write a clear, complete, well-structured answer to "
        "the user's query. Be concise but thorough.\n\n"
        f"USER QUERY:\n{state['user_query']}\n\n"
        f"RESEARCH NOTES:\n{state['research_notes']}"
        f"{revision_block}"
    )

    draft = llm.invoke(prompt).content
    return {
        "draft": draft,
        "iteration": state.get("iteration", 0) + 1,
    }


def critic_node(state: AgentState) -> dict:
    """Review the draft for accuracy/completeness/clarity. Decide REVISE or APPROVE."""
    llm = _llm(state["model_name"])

    prompt = (
        "You are the CRITIC agent. Review the following draft response for "
        "accuracy, completeness relative to the query, and clarity. Be strict "
        "but fair. Output exactly two sections in this format:\n\n"
        "ASSESSMENT: <1-3 sentences identifying issues, or 'No issues found'>\n"
        "VERDICT: REVISE or APPROVE\n\n"
        f"USER QUERY:\n{state['user_query']}\n\n"
        f"DRAFT:\n{state['draft']}"
    )

    critique_text = llm.invoke(prompt).content
    verdict_match = re.search(r"VERDICT\s*:\s*(REVISE|APPROVE)", critique_text, re.IGNORECASE)
    needs_revision = bool(verdict_match and verdict_match.group(1).upper() == "REVISE")

    return {"critique": critique_text, "needs_revision": needs_revision}


def finalize_node(state: AgentState) -> dict:
    """Promote the current draft to the final answer."""
    return {"final_answer": state["draft"]}


def _route_after_critic(state: AgentState) -> str:
    if state["needs_revision"] and state["iteration"] <= MAX_REVISIONS:
        return "writer"
    return "finalize"


def _build_graph():
    g = StateGraph(AgentState)
    g.add_node("researcher", researcher_node)
    g.add_node("writer", writer_node)
    g.add_node("critic", critic_node)
    g.add_node("finalize", finalize_node)

    g.add_edge(START, "researcher")
    g.add_edge("researcher", "writer")
    g.add_edge("writer", "critic")
    g.add_conditional_edges(
        "critic",
        _route_after_critic,
        {"writer": "writer", "finalize": "finalize"},
    )
    g.add_edge("finalize", END)

    return g.compile()


_GRAPH = _build_graph()


def get_response_from_ai_agents(llm_id: str, query, allow_search: bool, system_prompt: str) -> dict:
    """Run the multi-agent graph for a single user query.

    Returns a dict with the final answer plus the per-agent trace:
        {
          "final_answer": str,
          "research_notes": str,
          "draft": str,
          "critique": str,
          "iterations": int,
        }
    """
    user_query = query[0] if isinstance(query, list) and query else str(query)

    initial_state: AgentState = {
        "user_query": user_query,
        "system_prompt": system_prompt or "",
        "allow_search": bool(allow_search),
        "model_name": llm_id,
        "research_notes": "",
        "draft": "",
        "critique": "",
        "needs_revision": False,
        "iteration": 0,
        "final_answer": "",
    }

    final_state = _GRAPH.invoke(initial_state)

    return {
        "final_answer": final_state["final_answer"],
        "research_notes": final_state.get("research_notes", ""),
        "draft": final_state.get("draft", ""),
        "critique": final_state.get("critique", ""),
        "iterations": final_state.get("iteration", 0),
    }
