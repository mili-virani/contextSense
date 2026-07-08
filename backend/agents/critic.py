#!/usr/bin/env python3
"""
Critic Agent implementation.

This agent evaluates price direction predictions for consistency, evidence quality,
and citation validity, using Gemini with a self-critique/reflexion prompt.
"""

import os
import sys
import json
import asyncio
from pathlib import Path
from typing import List, Optional

# Ensure parent directory is in sys.path
script_path = Path(__file__).resolve()
backend_dir = script_path.parents[1]
if str(backend_dir) not in sys.path:
    sys.path.append(str(backend_dir))

from dotenv import load_dotenv
env_path = backend_dir / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

try:
    from google import genai
    from google.genai import types
    from pydantic import ValidationError
except ImportError as e:
    print(f"Error: Missing dependency: {e}")
    sys.exit(1)

from backend.schemas.event import Event
from backend.schemas.retrieved_chunk import RetrievedChunk
from backend.schemas.prediction import Prediction
from backend.schemas.critic_verdict import CriticVerdict

CRITIC_SYSTEM_PROMPT = """You are a senior financial analyst and investment critic.
Your role is to rigorously critique a stock price prediction forecast for the ticker '{ticker}' based on the provided extracted news events, technical indicators, and a deterministic citation check.

You MUST perform your critique in this exact order:
1. COUNTER-ARGUMENT & WEAK EVIDENCE (REFLEXION):
   - Argue strongly AGAINST approving the prediction.
   - Identify the weakest cited event.
   - Point out what evidence is thin or speculative.
   - Construct the strongest counter-argument to the predicted direction (e.g. why the opposite direction or neutrality is more likely).
2. CITATION AND REFERENCE VERIFICATION:
   - Review the provided deterministic citation validation report.
   - List any flags or mismatches where cited event IDs or event source chunk IDs failed to resolve.
3. FINAL APPROVAL DECISION:
   - Based on the strength of the evidence and the citation verification, decide whether to approve or reject the prediction.
   - If any citation failed to resolve, you MUST reject the prediction (approved=false) and include the matching error flag in your response.
   - Important Approval Calibration: Financial predictions are inherently uncertain. Do not treat standard market uncertainty or lack of 100% certainty as a reason to reject. You should approve the prediction if the overall reasoning is sound, the cited events are relevant and valid, and there are no direct, unresolved contradictions with the technical indicators. Reject the prediction only if there is a severe flaw (e.g., citation verification fails, cited events do not exist, or the predicted direction directly contradicts the technical indicators without any plausible explanation).

The output must be a valid JSON object matching the schema structure.
Do not include any formatting or explanation outside the JSON output.
"""


def verify_citations_deterministically(
    prediction: Prediction,
    events: List[Event],
    source_chunks: List[RetrievedChunk]
) -> dict:
    """
    Deterministically verifies that:
    1. Every cited event ID in prediction.cited_event_ids maps to a real event.
    2. Every event's source_ids map to real source chunks.
    """
    valid_chunk_ids = {c.id for c in source_chunks if c.id}

    # Extract all event source chunk IDs (since events are mapped by their source chunk IDs)
    event_source_ids = set()
    for event in events:
        for sid in event.source_ids:
            event_source_ids.add(sid)

    missing_events = []
    missing_chunks = []
    flags = []

    # 1. Verify cited event IDs correspond to a real event
    for cited_id in prediction.cited_event_ids:
        if cited_id not in event_source_ids:
            missing_events.append(cited_id)
            flags.append(f"Citation Error: Cited event ID '{cited_id}' does not match any extracted event.")

    # 2. Verify that each event's source_ids correspond to real chunks
    for event in events:
        for sid in event.source_ids:
            if sid not in valid_chunk_ids:
                missing_chunks.append(sid)
                flags.append(f"Citation Error: Event source chunk ID '{sid}' does not exist in raw source chunks.")

    return {
        "valid": len(flags) == 0,
        "flags": flags,
        "missing_events": missing_events,
        "missing_chunks": missing_chunks
    }


def get_mock_verdict(prediction: Prediction, citation_report: dict) -> CriticVerdict:
    """Generates heuristic-based mock CriticVerdict if API calls fail or key is missing."""
    approved = citation_report["valid"]
    flags = citation_report["flags"].copy()

    if not approved:
        revision_notes = f"[MOCK REVISION NOTES] Prediction rejected due to citation mismatches: {'; '.join(flags)}."
        confidence = 0.5
    else:
        # Check prediction confidence
        if prediction.confidence < 0.6:
            approved = False
            flags.append("Warning: Prediction confidence is below threshold (0.60).")
            revision_notes = f"[MOCK REVISION NOTES] Prediction confidence ({prediction.confidence:.2f}) is too thin. Please verify indicators."
            confidence = 0.8
        else:
            revision_notes = None
            confidence = prediction.confidence

    return CriticVerdict(
        approved=approved,
        flags=flags,
        final_confidence=confidence,
        revision_notes=revision_notes
    )


async def critique_with_gemini(
    ticker: str,
    payload: dict,
    client: genai.Client,
    model: str
) -> CriticVerdict:
    """Invokes Gemini asynchronously with schema reinforcement."""
    # Format contents
    user_content = json.dumps(payload, indent=2)
    
    # Configure Gemini content generation call
    config = types.GenerateContentConfig(
        system_instruction=CRITIC_SYSTEM_PROMPT.format(ticker=ticker),
        response_mime_type="application/json",
        response_schema=CriticVerdict,
        temperature=0.1,
    )
    
    response = await client.aio.models.generate_content(
        model=model,
        contents=user_content,
        config=config
    )
    
    return CriticVerdict.model_validate_json(response.text)


async def critique(
    prediction: Prediction,
    events: List[Event],
    source_chunks: List[RetrievedChunk],
    ticker: str = "AAPL"
) -> CriticVerdict:
    """
    Critiques a Prediction against extracted events and raw source chunks.
    
    Args:
        prediction (Prediction): Forecast prediction.
        events (List[Event]): List of events.
        source_chunks (List[RetrievedChunk]): Original news source chunks.
        ticker (str): Stock ticker of interest.
        
    Returns:
        CriticVerdict: Evaluation approval decision and flags.
    """
    # 1. Deterministic Python citation check first
    citation_report = verify_citations_deterministically(prediction, events, source_chunks)
    
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Warning: GEMINI_API_KEY not set. Using mock critic verification.")
        return get_mock_verdict(prediction, citation_report)

    # Set model default
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    client = genai.Client(api_key=api_key)

    # Format payload
    events_payload = [
        {
            "event_type": e.event_type,
            "description": e.description,
            "sentiment_score": e.sentiment_score,
            "confidence": e.confidence,
            "source_ids": e.source_ids
        }
        for e in events
    ]

    payload = {
        "prediction": {
            "direction": prediction.direction,
            "confidence": prediction.confidence,
            "horizon_days": prediction.horizon_days,
            "reasoning_summary": prediction.reasoning_summary,
            "cited_event_ids": prediction.cited_event_ids
        },
        "events": events_payload,
        "deterministic_citation_report": {
            "valid": citation_report["valid"],
            "flags": citation_report["flags"]
        }
    }

    try:
        # First attempt
        return await critique_with_gemini(ticker, payload, client, model)

    except Exception as e:
        print(f"Warning: Critic first attempt failed: {e}")
        
        try:
            # Second attempt (retry once by wrapping prompt with diagnostic note)
            payload["diagnostic_note"] = "your last response was not valid JSON, return ONLY the JSON object matching the schema"
            return await critique_with_gemini(ticker, payload, client, model)
            
        except Exception as retry_err:
            print(f"Error: Critic retry failed: {retry_err}. Falling back to mock verification.")
            return get_mock_verdict(prediction, citation_report)


async def run_manual_test():
    """Runs the complete Retriever -> Analyst -> Technical Indicators -> Predictor -> Critic pipeline."""
    print("==================================================")
    print("STEP 1: Initializing Retriever Agent...")
    from backend.agents.retriever import create_retriever_agent
    retriever = create_retriever_agent()
    
    test_ticker = "AAPL"
    inputs = {
        "ticker": test_ticker,
        "query": "What are the recent major developments, regulatory updates, guidance changes, or earnings results for AAPL?",
        "lookback_days": 7
    }
    
    print(f"Retrieving news chunks for {test_ticker}...")
    retriever_result = retriever.invoke(inputs)
    chunks = retriever_result.get("chunks", [])
    print(f"Retrieved {len(chunks)} chunks.")
    
    print("\n==================================================")
    print("STEP 2: Running Analyst Agent...")
    from backend.agents.analyst import analyze
    events = await analyze(chunks, test_ticker)
    print(f"Extracted {len(events)} events.")
    
    print("\n==================================================")
    print("STEP 3: Fetching Technical Features...")
    from backend.agents.predictor import get_technical_features
    technical_features = await get_technical_features(test_ticker)
    
    print("\n==================================================")
    print("STEP 4: Running Predictor Agent...")
    from backend.agents.predictor import predict
    prediction = await predict(events, technical_features, test_ticker)
    print(f"Forecast Direction: {prediction.direction.upper()} | Confidence: {prediction.confidence:.2%}")
    
    print("\n==================================================")
    print("STEP 5: Running Critic Agent...")
    verdict = await critique(prediction, events, chunks, test_ticker)
    
    print("\n==================================================")
    print("CRITIC EVALUATION VERDICT:")
    print(f"Approved: {verdict.approved}")
    print(f"Final Confidence: {verdict.final_confidence:.2%}")
    print(f"Flags Raised: {verdict.flags}")
    print(f"Revision Notes:")
    print(verdict.revision_notes)
    print("==================================================")


if __name__ == "__main__":
    asyncio.run(run_manual_test())
