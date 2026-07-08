#!/usr/bin/env python3
"""
Pipeline Coordinator implementation.

Chains Retriever -> Analyst -> Predictor -> Critic agents into a LangGraph graph.
If approved by Critic, writes prediction to Notion database.
"""

import os
import sys
import json
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict, List, Optional, Literal

# Ensure workspace root is in sys.path to enable imports of backend.*
script_path = Path(__file__).resolve()
workspace_root = script_path.parent.parent
if str(workspace_root) not in sys.path:
    sys.path.append(str(workspace_root))

from dotenv import load_dotenv
env_path = workspace_root / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

try:
    from langgraph.graph import StateGraph, END
except ImportError as e:
    print(f"Error: Missing langgraph dependency: {e}")
    sys.exit(1)

from backend.schemas.retrieved_chunk import RetrievedChunk
from backend.schemas.event import Event
from backend.schemas.prediction import Prediction
from backend.schemas.critic_verdict import CriticVerdict
from backend.schemas.run_log import RunLog, persist_run_log


class PipelineState(TypedDict):
    """
    Shared state carried through the LangGraph workflow.
    """
    ticker: str
    query: str
    lookback_days: int
    chunks: List[RetrievedChunk]
    events: List[Event]
    technical_features: dict
    prediction: Optional[Prediction]
    verdict: Optional[CriticVerdict]
    notion_page_url: Optional[str]
    retry_count: int
    feedback: Optional[str]
    request_type: str
    route: str
    tickers: List[str]
    priority: str


def orchestrator_node(state: PipelineState) -> dict:
    """
    Node that runs the Orchestrator Agent to extract tickers and route the request.
    """
    ticker = state.get("ticker")
    user_query = state.get("query")
    request_type = state.get("request_type", "on_demand")

    print(f"\n--- [Pipeline Node: orchestrator] Running Orchestrator Agent ---")
    from backend.agents.orchestrator import orchestrate
    
    result = orchestrate({
        "request_type": request_type,
        "ticker": ticker,
        "user_query": user_query
    })
    
    print(f"Orchestrator output: route={result['route']}, tickers={result['tickers']}, priority={result['priority']}")
    
    updates = {
        "route": result["route"],
        "tickers": result["tickers"],
        "priority": result["priority"]
    }
    
    if result["tickers"]:
        updates["ticker"] = result["tickers"][0]
        
    return updates


def route_after_orchestrator(state: PipelineState) -> str:
    """
    Evaluates the route determined by the Orchestrator.
    """
    route = state.get("route")
    if route == "ticker_analysis":
        return "retriever"
    else:
        print("Orchestrator: No valid ticker found. Routing to end_rejected.")
        return "end_rejected"


def retriever_node(state: PipelineState) -> dict:
    """
    Node that runs the compiled Retriever Agent LangGraph flow.
    """
    ticker = state["ticker"].upper().strip()
    query = state.get("query")
    if not query:
        query = f"What are the recent major developments, regulatory updates, guidance changes, or earnings results for {ticker}?"
    lookback_days = state.get("lookback_days", 7)

    print(f"\n--- [Pipeline Node: retriever] Running Retriever Agent for {ticker} ---")
    from backend.agents.retriever import create_retriever_agent
    retriever_agent = create_retriever_agent()
    
    result = retriever_agent.invoke({
        "ticker": ticker,
        "query": query,
        "lookback_days": lookback_days
    })
    
    chunks = result.get("chunks", [])
    print(f"Retrieved {len(chunks)} news chunks.")
    return {"chunks": chunks}


async def analyst_node(state: PipelineState) -> dict:
    """
    Node that calls the Analyst Agent to extract finance-related events.
    """
    ticker = state["ticker"]
    chunks = state.get("chunks", [])

    print(f"\n--- [Pipeline Node: analyst] Running Analyst Agent for {ticker} ---")
    from backend.agents.analyst import analyze
    events = await analyze(chunks, ticker)
    print(f"Extracted {len(events)} events.")
    return {"events": events}


async def predictor_node(state: PipelineState) -> dict:
    """
    Node that calculates technical features and predicts the price direction.
    """
    ticker = state["ticker"]
    events = state.get("events", [])
    feedback = state.get("feedback")
    retry_count = state.get("retry_count", 0)

    print(f"\n--- [Pipeline Node: predictor] Running Predictor Agent for {ticker} (Attempt {retry_count + 1}) ---")
    from backend.agents.predictor import get_technical_features, predict
    technical_features = await get_technical_features(ticker)
    prediction = await predict(events, technical_features, ticker, feedback)
    print(f"Formulated Forecast: Direction={prediction.direction.upper()} | Confidence={prediction.confidence:.2%}")
    return {
        "technical_features": technical_features,
        "prediction": prediction
    }


async def critic_node(state: PipelineState) -> dict:
    """
    Node that critiques the prediction for consistency and citation validity.
    """
    ticker = state["ticker"]
    prediction = state.get("prediction")
    events = state.get("events", [])
    chunks = state.get("chunks", [])
    retry_count = state.get("retry_count", 0)

    print(f"\n--- [Pipeline Node: critic] Running Critic Agent for {ticker} (Attempt {retry_count + 1}) ---")
    from backend.agents.critic import critique
    verdict = await critique(prediction, events, chunks, ticker)
    print(f"Verdict: Approved={verdict.approved} | Final Confidence={verdict.final_confidence:.2%}")
    if verdict.flags:
        print(f"Flags Raised: {verdict.flags}")
    if verdict.revision_notes:
        print(f"Revision Notes: {verdict.revision_notes}")

    updates = {"verdict": verdict}
    if not verdict.approved:
        # Formulate feedback context for next Predictor call
        direction_str = prediction.direction if prediction else "unknown"
        notes_str = verdict.revision_notes or "No feedback notes provided."
        feedback_str = (
            f"Your previous prediction of {direction_str} was rejected. "
            f"Reviewer feedback: {notes_str} "
            f"Produce a revised prediction that directly addresses this feedback — "
            f"do not just restate the same direction with softer language if the feedback identifies a real contradiction."
        )
        updates["feedback"] = feedback_str
        updates["retry_count"] = retry_count + 1

    return updates


def route_after_critic(state: PipelineState) -> str:
    """
    Conditional routing function evaluating the Critic's verdict approval and retry limits.
    """
    verdict = state.get("verdict")
    if verdict and verdict.approved:
        return "log_to_notion"
    
    # Check retry count
    retry_count = state.get("retry_count", 0)
    if retry_count < 2:
        print(f"Prediction rejected. Routing back to Predictor node for revision (Attempt {retry_count + 1} next).")
        return "predictor"
    else:
        print("Prediction rejected. Maximum retry attempts reached. Routing to end_rejected.")
        return "end_rejected"


def log_to_notion_node(state: PipelineState) -> dict:
    """
    Node that writes the prediction results to the Notion database.
    """
    ticker = state["ticker"]
    prediction = state.get("prediction")
    verdict = state.get("verdict")
    events = state.get("events", [])

    print(f"\n--- [Pipeline Node: log_to_notion] Logging prediction results to Notion ---")
    from backend.mcp_clients.notion_mcp_client import NotionClient

    try:
        client = NotionClient()
    except Exception as e:
        print(f"Error: Failed to initialize NotionClient: {e}")
        return {"notion_page_url": None}

    if not client.api_key or not client.database_id:
        print("Warning: Notion configuration missing from environment. Skipping logging.")
        return {"notion_page_url": None}

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    direction = prediction.direction if prediction else "neutral"
    confidence = verdict.final_confidence if verdict else (prediction.confidence if prediction else 0.0)

    # Heuristic: resolve key citation text from cited events
    key_citation = "No cited events or reasoning trace available."
    if prediction:
        if prediction.cited_event_ids and events:
            for event in events:
                if any(sid in prediction.cited_event_ids for sid in event.source_ids):
                    key_citation = event.description
                    break
        elif prediction.reasoning_summary:
            key_citation = prediction.reasoning_summary[:200] + ("..." if len(prediction.reasoning_summary) > 200 else "")

    try:
        result = client.append_row(
            ticker=ticker,
            date=date_str,
            direction=direction,
            confidence=confidence,
            key_citation=key_citation
        )
        url = result.get("url")
        print(f"Successfully logged prediction! Notion Page URL: {url}")
        return {"notion_page_url": url}
    except Exception as e:
        print(f"Error appending prediction row to Notion: {e}")
        if hasattr(e, "response") and e.response is not None:
            print(f"Response Details: {e.response.text}")
        return {"notion_page_url": None}


def end_rejected_node(state: PipelineState) -> dict:
    """
    Terminal node when prediction fails verification or is rejected by Critic.
    """
    ticker = state["ticker"]
    verdict = state.get("verdict")
    print(f"\n--- [Pipeline Node: end_rejected] Prediction for {ticker} was REJECTED ---")
    if verdict and verdict.revision_notes:
        print(f"Critic Revision Notes: {verdict.revision_notes}")
    return {}


def create_pipeline():
    """
    Assembles and compiles the multi-agent LangGraph workflow.
    """
    workflow = StateGraph(PipelineState)

    # Register Nodes
    workflow.add_node("orchestrator", orchestrator_node)
    workflow.add_node("retriever", retriever_node)
    workflow.add_node("analyst", analyst_node)
    workflow.add_node("predictor", predictor_node)
    workflow.add_node("critic", critic_node)
    workflow.add_node("log_to_notion", log_to_notion_node)
    workflow.add_node("end_rejected", end_rejected_node)

    # Set Entry Point
    workflow.set_entry_point("orchestrator")

    # Set Edges
    workflow.add_conditional_edges(
        "orchestrator",
        route_after_orchestrator,
        {
            "retriever": "retriever",
            "end_rejected": "end_rejected"
        }
    )
    workflow.add_edge("retriever", "analyst")
    workflow.add_edge("analyst", "predictor")
    workflow.add_edge("predictor", "critic")

    # Set Conditional Router
    workflow.add_conditional_edges(
        "critic",
        route_after_critic,
        {
            "log_to_notion": "log_to_notion",
            "end_rejected": "end_rejected",
            "predictor": "predictor"
        }
    )

    # Terminals
    workflow.add_edge("log_to_notion", END)
    workflow.add_edge("end_rejected", END)

    return workflow.compile()


async def async_run_pipeline(
    ticker: Optional[str] = None,
    user_query: Optional[str] = None,
    request_type: Literal["scheduled", "on_demand"] = "on_demand"
) -> PipelineState:
    """
    Asynchronously runs the full pipeline starting with Orchestrator routing.
    """
    graph = create_pipeline()
    initial_state = {
        "ticker": ticker,
        "query": user_query or "",
        "lookback_days": 7,
        "chunks": [],
        "events": [],
        "technical_features": {},
        "prediction": None,
        "verdict": None,
        "notion_page_url": None,
        "retry_count": 0,
        "feedback": None,
        "request_type": request_type,
        "route": "unknown",
        "tickers": [],
        "priority": "normal"
    }
    final_state = await graph.ainvoke(initial_state)

    # Persist every run after the graph finishes — approved (log_to_notion),
    # rejected (end_rejected), and early orchestrator failures all reach here.
    try:
        run_log = RunLog.from_pipeline_state(final_state)
        await persist_run_log(run_log)
        print(
            f"Run log persisted: ticker={run_log.ticker}, "
            f"approved={run_log.approved}, direction={run_log.direction}"
        )
    except Exception as e:
        print(f"Warning: Failed to persist run log: {e}")

    return final_state


def run_pipeline(
    ticker: Optional[str] = None,
    user_query: Optional[str] = None,
    request_type: Literal["scheduled", "on_demand"] = "on_demand"
) -> PipelineState:
    """
    Synchronous wrapper to run the full pipeline end to end.
    """
    return asyncio.run(async_run_pipeline(ticker, user_query, request_type))


def main():
    """
    Main runner script to execute pipeline via ticker or user query.
    """
    ticker = None
    user_query = None

    if len(sys.argv) > 1:
        arg = sys.argv[1].strip()
        # If it looks like a single ticker symbol (no spaces, 1-5 chars)
        if " " not in arg and len(arg) <= 5:
            ticker = arg.upper()
        else:
            user_query = arg
    else:
        # Default fallback if no args are passed
        ticker = "AAPL"

    input_str = f"Ticker={ticker}" if ticker else f"Query='{user_query}'"
    print(f"==================================================")
    print(f"STARTING MULTI-AGENT PIPELINE FOR: {input_str}")
    print(f"==================================================")

    try:
        final_state = run_pipeline(ticker=ticker, user_query=user_query)
        
        print(f"\n==================================================")
        print(f"SUMMARY OF AGENT PIPELINE RESULT:")
        print(f"==================================================")
        print(f"Ticker:            {final_state.get('ticker')}")
        
        pred = final_state.get("prediction")
        verdict = final_state.get("verdict")
        retry_count = final_state.get("retry_count", 0)
        
        if pred:
            print(f"Predicted Direction:{pred.direction.upper()}")
            print(f"Predictor Conf:    {pred.confidence:.2%}")
        else:
            print("Predicted Direction: N/A")
            
        if verdict:
            print(f"Critic Approved:   {verdict.approved}")
            print(f"Final Confidence:  {verdict.final_confidence:.2%}")
            
            # Print attempt detail summary
            if verdict.approved:
                print(f"Approval Attempts: Approved in {retry_count + 1} attempt(s)")
            else:
                print(f"Approval Attempts: Failed after all {retry_count} attempts")
                
            if verdict.flags:
                print(f"Critic Flags:      {verdict.flags}")
        else:
            print("Critic Approved:   N/A")
            
        notion_url = final_state.get("notion_page_url")
        if notion_url:
            print(f"Notion Log URL:    {notion_url}")
        else:
            print("Notion Log URL:    Not Logged (Rejected or skipped)")
        print(f"==================================================")

    except Exception as e:
        print(f"\nPipeline run failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
