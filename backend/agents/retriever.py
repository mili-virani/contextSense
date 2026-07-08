#!/usr/bin/env python3
"""
Retriever Agent implementation using LangGraph.

This agent performs the following steps:
1. Runs a vector similarity search against the Qdrant "news_chunks" collection,
   filtered by ticker (top-k=8).
2. If fewer than 3 chunks are returned (cold-start ticker), it calls the
   Alpha Vantage ingestion script as a subprocess to pull and index fresh news.
3. Uses DeepSeek V4 Flash via an OpenAI-compatible client to extract key 
   Knowledge Graph (KG) relations from the retrieved news.
4. Queries Alpha Vantage to fetch real-time global quote metrics (price, change, volume) 
   to populate the live_data field.
"""

import os
import sys
import json
import time
import subprocess
from pathlib import Path
from typing import TypedDict, List, Optional
import requests
from dotenv import load_dotenv

# Ensure the parent directory is in sys.path so we can import backend schemas
script_path = Path(__file__).resolve()
backend_dir = script_path.parents[1]
if str(backend_dir) not in sys.path:
    sys.path.append(str(backend_dir))

from backend.schemas.retrieved_chunk import RetrievedChunk

# Load environment variables
env_path = backend_dir / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

# Lazy imports for dependencies
try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import Filter, FieldCondition, MatchValue
    from openai import OpenAI
    from langgraph.graph import StateGraph, END
except ImportError as e:
    print(f"Error: Missing dependency: {e}")
    sys.exit(1)


# Global model cache to avoid slow load times on subsequent invocations
_embedding_model = None
_tokenizer = None


def get_embedding_model_and_tokenizer():
    """Retrieves or initializes the embedding model and tokenizer."""
    global _embedding_model, _tokenizer
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        from transformers import AutoTokenizer
        from transformers import logging as transformers_logging
        transformers_logging.set_verbosity_error()
        
        _embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
        _tokenizer = AutoTokenizer.from_pretrained("sentence-transformers/all-MiniLM-L6-v2")
    return _embedding_model, _tokenizer


class RetrieverState(TypedDict):
    """LangGraph state schema for the Retriever Agent."""
    ticker: str
    query: str
    lookback_days: int
    chunks: List[RetrievedChunk]
    kg_relations: List[dict]
    live_data: Optional[dict]


def retrieve_chunks_node(state: RetrieverState) -> dict:
    """
    Node that queries Qdrant for ticker-specific news chunks.
    Triggers fresh ingestion if fewer than 3 chunks are found.
    """
    ticker = state["ticker"].upper().strip()
    query = state["query"]
    
    # Initialize Qdrant Client
    qdrant_url = os.environ.get("QDRANT_URL", "http://localhost:6333")
    try:
        qdrant_client = QdrantClient(url=qdrant_url)
    except Exception as e:
        print(f"Error connecting to Qdrant: {e}")
        return {"chunks": []}

    # Helper function to perform vector search
    def search_qdrant() -> List[RetrievedChunk]:
        try:
            model, _ = get_embedding_model_and_tokenizer()
            query_vector = model.encode(query).tolist()
            
            filter_cond = Filter(
                must=[
                    FieldCondition(key="ticker", match=MatchValue(value=ticker))
                ]
            )
            
            response = qdrant_client.query_points(
                collection_name="news_chunks",
                query=query_vector,
                query_filter=filter_cond,
                limit=8
            )
            
            retrieved = []
            for hit in response.points:
                payload = hit.payload
                retrieved.append(
                    RetrievedChunk(
                        id=str(hit.id),
                        ticker=payload.get("ticker", ticker),
                        source=payload.get("source", "Unknown"),
                        date=payload.get("date", ""),
                        text=payload.get("text", ""),
                        score=hit.score
                    )
                )
            return retrieved
        except Exception as ex:
            print(f"Qdrant search error: {ex}")
            return []

    # Attempt initial search
    print(f"Retrieving news chunks for ticker '{ticker}' from Qdrant...")
    chunks = search_qdrant()

    # Cold-start handling: if < 3 chunks, trigger Alpha Vantage ingestion
    if len(chunks) < 3:
        print(f"Fewer than 3 chunks found for ticker '{ticker}' (found {len(chunks)}). Triggering Alpha Vantage ingestion...")
        ingest_script = Path(__file__).resolve().parent.parent / "ingestion" / "ingest.py"
        
        try:
            # Execute the ingestion script as a subprocess using the current python executable
            result = subprocess.run(
                [sys.executable, str(ingest_script), ticker],
                capture_output=True,
                text=True,
                check=True
            )
            print("Ingestion subprocess completed successfully.")
            # Re-run search after ingestion
            chunks = search_qdrant()
        except subprocess.CalledProcessError as err:
            print(f"Ingestion subprocess failed with exit code {err.returncode}.")
            print(f"Stderr: {err.stderr}")
        except Exception as e:
            print(f"Failed to execute ingestion script: {e}")

    return {"chunks": chunks}


def extract_kg_relations_node(state: RetrieverState) -> dict:
    """
    Node that extracts key entity/event relations from chunks using DeepSeek V4 Flash.
    """
    ticker = state["ticker"]
    query = state["query"]
    chunks = state.get("chunks", [])

    if not chunks:
        return {"kg_relations": []}

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("Warning: DEEPSEEK_API_KEY not set. Skipping KG relation extraction.")
        return {"kg_relations": []}

    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    
    # Construct combined news context
    context_list = []
    for c in chunks:
        context_list.append(f"Source: {c.source} | Date: {c.date}\nText: {c.text}")
    chunks_context = "\n\n".join(context_list)

    prompt = f"""
You are a Knowledge Graph extraction assistant.
Given the following news chunks about the stock ticker '{ticker}' and the user's query '{query}', extract key semantic relations (facts, events, entity associations, or market drivers).

Format each relation as a JSON object inside a wrapping "relations" list. The schema of each relation must be:
- "subject": The source entity/actor (e.g. "{ticker}", "CEO", "Federal Reserve", competitor name).
- "relation": The verb or relationship (e.g. "launched", "acquired", "increased revenue", "lowered guidance").
- "object": The target entity or effect.
- "sentiment": Overall sentiment impact of this relation on '{ticker}' ("positive", "negative", "neutral").

Only return a valid JSON object with the "relations" key containing the list. Do not include markdown code block formatting or explanations.

News Chunks:
{chunks_context}
"""

    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        response = client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=[
                {"role": "system", "content": "You are a precise financial analysis assistant."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            timeout=30
        )
        content = response.choices[0].message.content
        data = json.loads(content)
        relations = data.get("relations", [])
        print(f"Extracted {len(relations)} KG relations via DeepSeek.")
        return {"kg_relations": relations}
    except Exception as e:
        print(f"Warning: Failed to extract KG relations via DeepSeek: {e}")
        # Fallback relationship
        fallback = [
            {
                "subject": ticker,
                "relation": "mentioned_in_news",
                "object": f"query: {query}",
                "sentiment": "neutral"
            }
        ]
        return {"kg_relations": fallback}


def fetch_live_data_node(state: RetrieverState) -> dict:
    """
    Node that queries the Alpha Vantage GLOBAL_QUOTE endpoint to retrieve 
    real-time stock pricing, volume, and percentage change.
    """
    ticker = state["ticker"].upper().strip()
    api_key = os.environ.get("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        print("Warning: ALPHA_VANTAGE_API_KEY not set. Skipping live data fetch.")
        return {"live_data": None}

    url = "https://www.alphavantage.co/query"
    params = {
        "function": "GLOBAL_QUOTE",
        "symbol": ticker,
        "apikey": api_key
    }

    print(f"Fetching live global quote data for ticker '{ticker}'...")
    try:
        time.sleep(1.2)
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        # Handle rate limits or error messages gracefully
        if "Note" in data:
            print(f"Alpha Vantage Rate Limit/Note while fetching quote: {data['Note']}")
            return {"live_data": None}
            
        quote = data.get("Global Quote")
        if quote:
            live_data = {
                "ticker": ticker,
                "price": quote.get("05. price"),
                "change": quote.get("09. change"),
                "change_percent": quote.get("10. change percent"),
                "volume": quote.get("06. volume"),
                "latest_trading_day": quote.get("07. latest trading day")
            }
            print(f"Live data retrieved successfully: Price = {live_data['price']}, Change = {live_data['change_percent']}")
            return {"live_data": live_data}
            
    except Exception as e:
        print(f"Warning: Failed to fetch live quote from Alpha Vantage: {e}")
        
    return {"live_data": None}


def create_retriever_agent():
    """Compiles the Retriever Agent LangGraph workflow."""
    workflow = StateGraph(RetrieverState)
    
    # Register nodes
    workflow.add_node("retrieve_chunks", retrieve_chunks_node)
    workflow.add_node("extract_kg_relations", extract_kg_relations_node)
    workflow.add_node("fetch_live_data", fetch_live_data_node)
    
    # Set execution path
    workflow.set_entry_point("retrieve_chunks")
    workflow.add_edge("retrieve_chunks", "extract_kg_relations")
    workflow.add_edge("extract_kg_relations", "fetch_live_data")
    workflow.add_edge("fetch_live_data", END)
    
    return workflow.compile()


def main():
    """Main execution block for manual testing."""
    print("Initializing Retriever Agent...")
    agent = create_retriever_agent()

    # Tickers for testing
    # - AAPL: Should fetch data and run similarity search
    # - MSFT: Can act as a cold start ticker (likely no database entries yet)
    test_ticker = "AAPL"
    if len(sys.argv) > 1:
        test_ticker = sys.argv[1].upper()

    inputs = {
        "ticker": test_ticker,
        "query": "Is the company releasing new hardware or expanding its market presence?",
        "lookback_days": 7
    }

    print(f"\n--- Running Retriever Agent for {test_ticker} ---")
    result = agent.invoke(inputs)

    print("\n--- RESULTS ---")
    print(f"Ticker: {result.get('ticker')}")
    print(f"Query: {result.get('query')}")
    print(f"Lookback Days: {result.get('lookback_days')}")
    
    print("\n--- Live Data Quote ---")
    print(json.dumps(result.get("live_data"), indent=2))
    
    print("\n--- Retrieved Chunks ---")
    chunks = result.get("chunks", [])
    print(f"Total Chunks Retrieved: {len(chunks)}")
    for i, c in enumerate(chunks[:3]):
        print(f"\nChunk {i+1} [Source: {c.source} | Date: {c.date} | Score: {c.score:.4f}]:")
        # Print a short snippet
        text_snippet = c.text.replace("\n", " ")[:150]
        print(f"  {text_snippet}...")

    print("\n--- Extracted KG Relations ---")
    print(json.dumps(result.get("kg_relations"), indent=2))


if __name__ == "__main__":
    main()
