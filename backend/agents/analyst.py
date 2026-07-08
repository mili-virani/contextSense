#!/usr/bin/env python3
"""
Analyst Agent implementation.

This agent performs event extraction from financial news chunks.
It uses DeepSeek V4 Flash via an OpenAI-compatible client, leveraging
few-shot prompting to extract structured Event models.
"""

import os
import sys
import json
import asyncio
from pathlib import Path
from typing import List

# Ensure parent directory is in sys.path so we can import packages
script_path = Path(__file__).resolve()
backend_dir = script_path.parents[1]
if str(backend_dir) not in sys.path:
    sys.path.append(str(backend_dir))

from dotenv import load_dotenv
# Load environment variables
env_path = backend_dir / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

try:
    from openai import AsyncOpenAI
    from pydantic import ValidationError
except ImportError as e:
    print(f"Error: Missing dependency: {e}")
    sys.exit(1)

from backend.schemas.retrieved_chunk import RetrievedChunk
from backend.schemas.event import Event

SYSTEM_PROMPT = """You are a financial analyst assistant specializing in event extraction.
Extract zero or more significant events from the financial text chunk for the stock ticker '{ticker}'.

Each extracted event MUST strictly adhere to the following schema:
- event_type: One of "earnings_beat", "earnings_miss", "guidance_change", "regulatory_risk", "management_change", "other".
- description: A brief summary of the event.
- sentiment_score: Numerical value from -1.0 (most negative) to 1.0 (most positive).
- confidence: Extraction confidence score from 0.0 (uncertain) to 1.0 (highly certain).
- source_ids: List of source chunk IDs. IMPORTANT: Use the exact source chunk ID provided for this chunk.

If there are no events matching the event types or relevant to '{ticker}' in the text, return an empty list of events: {{"events": []}}.

You MUST output ONLY a valid JSON object matching the Event List schema:
{{
  "events": [
    {{
      "event_type": "...",
      "description": "...",
      "sentiment_score": ...,
      "confidence": ...,
      "source_ids": ["..."]
    }}
  ]
}}
Do not include any explanation or text outside the JSON output.

Worked Examples:

Example 1 (earnings_beat):
Input Text (Chunk ID: "example_chunk_1"):
"ACME Corp (ACM) reported Q2 earnings per share of $1.45, beating consensus analyst estimates of $1.30 by $0.15. Revenue for the quarter rose 12% year-over-year to $4.2B, driven by strong growth in its cloud division."
Expected JSON Output:
{{
  "events": [
    {{
      "event_type": "earnings_beat",
      "description": "ACME Corp reported Q2 EPS of $1.45, beating estimates of $1.30, with revenue up 12% YoY to $4.2B.",
      "sentiment_score": 0.8,
      "confidence": 0.95,
      "source_ids": ["example_chunk_1"]
    }}
  ]
}}

Example 2 (regulatory_risk):
Input Text (Chunk ID: "example_chunk_2"):
"The European Commission launched an antitrust investigation into Zenith Logistics (ZLOG) following complaints from competitors. If found guilty of anti-competitive practices, the firm faces potential fines of up to 10% of its global turnover."
Expected JSON Output:
{{
  "events": [
    {{
      "event_type": "regulatory_risk",
      "description": "Zenith Logistics faces antitrust investigation by European Commission with potential fines up to 10% of global turnover.",
      "sentiment_score": -0.7,
      "confidence": 0.9,
      "source_ids": ["example_chunk_2"]
    }}
  ]
}}

Example 3 (guidance_change):
Input Text (Chunk ID: "example_chunk_3"):
"Vortex Technologies (VRTX) adjusted its full-year revenue outlook downwards today. The company now expects revenue of $1.1B to $1.15B, down from its previous guidance of $1.2B to $1.25B, citing persistent supply chain constraints in Asia."
Expected JSON Output:
{{
  "events": [
    {{
      "event_type": "guidance_change",
      "description": "Vortex Technologies lowered its FY revenue guidance to $1.1B-$1.15B from $1.2B-$1.25B due to supply chain constraints.",
      "sentiment_score": -0.6,
      "confidence": 0.95,
      "source_ids": ["example_chunk_3"]
    }}
  ]
}}

Example 4 (management_change):
Input Text (Chunk ID: "example_chunk_4"):
"Apex Systems (APXS) announced that long-time Chief Financial Officer Sarah Jenkins will retire at the end of next month. She will be succeeded by David Vance, current VP of Finance at competitors Zenith Inc."
Expected JSON Output:
{{
  "events": [
    {{
      "event_type": "management_change",
      "description": "CFO Sarah Jenkins retiring from Apex Systems; VP David Vance appointed as successor.",
      "sentiment_score": 0.0,
      "confidence": 1.0,
      "source_ids": ["example_chunk_4"]
    }}
  ]
}}
"""


def get_mock_events(chunk: RetrievedChunk, ticker: str) -> List[Event]:
    """Generates heuristic-based mock events if API calls fail or credentials are empty."""
    text_lower = chunk.text.lower()
    source_id = chunk.id or "unknown_chunk"
    
    if "beat" in text_lower or "outperform" in text_lower or "above estimate" in text_lower:
        return [
            Event(
                event_type="earnings_beat",
                description=f"Mock: Detected potential earnings beat or financial outperformance in text for {ticker}.",
                sentiment_score=0.7,
                confidence=0.8,
                source_ids=[source_id]
            )
        ]
    elif "investigation" in text_lower or "antitrust" in text_lower or "regulatory" in text_lower or "fine" in text_lower or "lawsuit" in text_lower:
        return [
            Event(
                event_type="regulatory_risk",
                description=f"Mock: Detected potential regulatory risk or legal investigation for {ticker}.",
                sentiment_score=-0.6,
                confidence=0.85,
                source_ids=[source_id]
            )
        ]
    elif "guidance" in text_lower or "outlook" in text_lower or "forecast" in text_lower:
        return [
            Event(
                event_type="guidance_change",
                description=f"Mock: Detected potential guidance adjustment or outlook change for {ticker}.",
                sentiment_score=0.1,
                confidence=0.75,
                source_ids=[source_id]
            )
        ]
    elif "ceo" in text_lower or "cfo" in text_lower or "retire" in text_lower or "appoint" in text_lower or "executive" in text_lower:
        return [
            Event(
                event_type="management_change",
                description=f"Mock: Detected executive management transition or appointment for {ticker}.",
                sentiment_score=0.0,
                confidence=0.9,
                source_ids=[source_id]
            )
        ]
    else:
        return [
            Event(
                event_type="other",
                description=f"Mock: General market event or news mention detected for {ticker}.",
                sentiment_score=0.2,
                confidence=0.6,
                source_ids=[source_id]
            )
        ]


def parse_and_validate_events(json_str: str, chunk_id: str) -> List[Event]:
    """Helper to parse a JSON string and validate events against the Pydantic schema."""
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as err:
        raise ValueError(f"JSON decode failed: {err}")

    raw_events = data.get("events", [])
    validated_events = []
    
    for event_data in raw_events:
        # Guarantee that the event's source_ids are set to this chunk's ID
        event_data["source_ids"] = [chunk_id]
        
        # Instantiate and validate Pydantic model
        event = Event(**event_data)
        validated_events.append(event)
        
    return validated_events


async def analyze_chunk(chunk: RetrievedChunk, ticker: str, client: AsyncOpenAI) -> List[Event]:
    """Analyzes a single news chunk to extract events using DeepSeek V4 Flash."""
    chunk_id = chunk.id or "unknown_chunk"
    user_content = f"Input Text (Chunk ID: \"{chunk_id}\"):\n\"{chunk.text}\""
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.format(ticker=ticker)},
        {"role": "user", "content": user_content}
    ]
    
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
    
    try:
        # First attempt
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.1,
            timeout=30
        )
        content = response.choices[0].message.content
        return parse_and_validate_events(content, chunk_id)
        
    except Exception as e:
        print(f"Warning: First attempt failed for chunk {chunk_id}: {e}")
        
        # If it was an API billing/auth issue, avoid retry spam and return mock events
        if "402" in str(e) or "Insufficient Balance" in str(e):
            print(f"DeepSeek Billing/Balance issue detected. Falling back to mock extraction for chunk {chunk_id}.")
            return get_mock_events(chunk, ticker)
            
        try:
            # Second attempt (retry once)
            messages.append({"role": "assistant", "content": locals().get("content", "{}")})
            messages.append({
                "role": "user",
                "content": "your last response was not valid JSON, return ONLY the JSON object matching the schema"
            })
            
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.1,
                timeout=30
            )
            content = response.choices[0].message.content
            return parse_and_validate_events(content, chunk_id)
            
        except Exception as retry_err:
            print(f"Error: Retry failed for chunk {chunk_id}: {retry_err}. Falling back to mock extraction.")
            return get_mock_events(chunk, ticker)


def get_deepseek_client() -> AsyncOpenAI | None:
    """Helper to initialize the AsyncOpenAI client using DeepSeek configurations."""
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    if not api_key:
        return None
    return AsyncOpenAI(api_key=api_key, base_url=base_url)


async def analyze(chunks: List[RetrievedChunk], ticker: str) -> List[Event]:
    """
    Analyzes a list of news chunks concurrently to extract finance-related events.
    
    Args:
        chunks (List[RetrievedChunk]): List of news text snippets.
        ticker (str): The stock ticker of interest.
        
    Returns:
        List[Event]: Extracted structured Event objects.
    """
    if not chunks:
        return []
        
    client = get_deepseek_client()
    if not client:
        print("Warning: DEEPSEEK_API_KEY is not set. Using mock heuristic extraction.")
        return [evt for chunk in chunks for evt in get_mock_events(chunk, ticker)]
        
    # Process chunks concurrently
    tasks = [analyze_chunk(chunk, ticker, client) for chunk in chunks]
    results = await asyncio.gather(*tasks)
    
    # Flatten the list of lists
    all_events = []
    for events_list in results:
        all_events.extend(events_list)
        
    return all_events


async def run_manual_test():
    """Retrieves news chunks and runs them through the Analyst agent."""
    print("Initializing Retriever Agent...")
    from backend.agents.retriever import create_retriever_agent
    retriever = create_retriever_agent()
    
    test_ticker = "AAPL"
    inputs = {
        "ticker": test_ticker,
        "query": "What are the recent major developments, regulatory updates, guidance changes, or earnings results for AAPL?",
        "lookback_days": 7
    }
    
    print(f"Retrieving news chunks for {test_ticker}...")
    # retriever agent runs synchronously
    result = retriever.invoke(inputs)
    chunks = result.get("chunks", [])
    print(f"Retrieved {len(chunks)} chunks.")
    
    if not chunks:
        print("No chunks retrieved. Please ensure Qdrant has ingested data for this ticker.")
        return
        
    print(f"\nAnalyzing chunks for {test_ticker}...")
    events = await analyze(chunks, test_ticker)
    
    print(f"\n--- EXTRACTED EVENTS ({len(events)}) ---")
    for i, event in enumerate(events):
        print(f"\nEvent {i+1}:")
        print(f"  Type: {event.event_type}")
        print(f"  Description: {event.description}")
        print(f"  Sentiment Score: {event.sentiment_score:.2f}")
        print(f"  Confidence: {event.confidence:.2f}")
        print(f"  Source Chunk IDs: {event.source_ids}")


if __name__ == "__main__":
    asyncio.run(run_manual_test())
