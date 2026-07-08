#!/usr/bin/env python3
"""
Orchestrator Agent implementation.

Routes incoming user requests to the appropriate analysis flow.
Extracts ticker symbols from natural language queries using DeepSeek or a deterministic fallback.
"""

import os
import re
import json
import sys
from pathlib import Path
from typing import List, Literal, Optional, TypedDict

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

from openai import OpenAI

def get_sync_deepseek_client() -> OpenAI | None:
    """Helper to initialize the synchronous OpenAI client using DeepSeek configurations."""
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    if not api_key:
        return None
    return OpenAI(api_key=api_key, base_url=base_url)


class OrchestratorInput(TypedDict):
    request_type: Literal["scheduled", "on_demand"]
    ticker: Optional[str]
    user_query: Optional[str]


class OrchestratorOutput(TypedDict):
    route: str
    tickers: List[str]
    priority: Literal["low", "normal", "high"]


# Mapping of common company names/keywords to standard tickers for the fallback parser
COMMON_TICKER_MAP = {
    "apple": "AAPL",
    "aapl": "AAPL",
    "nvidia": "NVDA",
    "nvda": "NVDA",
    "microsoft": "MSFT",
    "msft": "MSFT",
    "google": "GOOGL",
    "googl": "GOOGL",
    "goog": "GOOGL",
    "alphabet": "GOOGL",
    "amazon": "AMZN",
    "amzn": "AMZN",
    "tesla": "TSLA",
    "tsla": "TSLA",
    "meta": "META",
    "facebook": "META",
    "netflix": "NFLX",
    "nflx": "NFLX"
}

# Stopwords to ignore in uppercase word regex matches
STOPWORDS = {"I", "A", "US", "GDP", "AI", "CEO", "CFO", "SEC", "FAQ", "ETF", "USD", "EUR", "GBP"}


def local_deterministic_parser(query: str) -> List[str]:
    """
    Fallback parser to extract tickers from a query string.
    Checks common names/stop-words and uppercase word sequences.
    """
    normalized = query.lower().strip()
    tickers = []

    # 1. Search for common company names
    for name, ticker in COMMON_TICKER_MAP.items():
        if re.search(rf"\b{name}\b", normalized):
            tickers.append(ticker)

    # 2. Check for any 1 to 5 character uppercase words in the raw query
    uppercase_words = re.findall(r"\b[A-Z]{1,5}\b", query)
    for word in uppercase_words:
        if word not in STOPWORDS and word not in tickers:
            tickers.append(word)

    return list(set(tickers))


def orchestrate(inputs: OrchestratorInput) -> OrchestratorOutput:
    """
    Orchestrates the entry point of the pipeline.
    Resolves tickers and defines request priority and next route.
    """
    request_type = inputs.get("request_type", "on_demand")
    ticker = inputs.get("ticker")
    user_query = inputs.get("user_query")

    priority: Literal["low", "normal", "high"] = "high" if request_type == "on_demand" else "normal"
    tickers: List[str] = []

    # Case A: Ticker is provided directly
    if ticker:
        ticker_clean = ticker.upper().strip()
        if ticker_clean:
            tickers = [ticker_clean]

    # Case B: Ticker not provided directly, but user query is present
    elif user_query:
        print(f"Orchestrator: Extracting ticker from query: '{user_query}'...")
        
        # Try LLM-based extraction first if client is configured
        client = get_sync_deepseek_client()
        if client:
            model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
            prompt = f"""
            Extract all stock ticker symbols (e.g., AAPL, NVDA, MSFT, TSLA) mentioned in or implied by this user query: '{user_query}'.
            
            Only return a JSON object with the key 'tickers' containing a list of strings. Do not include markdown code block formatting or explanations.
            
            Example 1: "What is the trend for Apple?" -> {{"tickers": ["AAPL"]}}
            Example 2: "Show me NVIDIA news" -> {{"tickers": ["NVDA"]}}
            Example 3: "Is MSFT a buy?" -> {{"tickers": ["MSFT"]}}
            Example 4: "Analyze the current macro economy" -> {{"tickers": []}}
            """
            
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "You are a precise financial assistant that outputs JSON."},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.1,
                    timeout=15
                )
                content = response.choices[0].message.content
                data = json.loads(content)
                extracted_list = data.get("tickers", [])
                
                # Clean up extracted list
                for val in extracted_list:
                    val_clean = val.upper().strip()
                    if val_clean and val_clean not in STOPWORDS:
                        tickers.append(val_clean)
                tickers = list(set(tickers))
                
            except Exception as e:
                print(f"Orchestrator: LLM extraction failed: {e}. Falling back to deterministic parser.")
                tickers = local_deterministic_parser(user_query)
        else:
            print("Orchestrator: No DeepSeek API client available. Using deterministic parser.")
            tickers = local_deterministic_parser(user_query)

    # Determine route based on resolved tickers
    if tickers:
        route = "ticker_analysis"
    else:
        route = "invalid"

    return {
        "route": route,
        "tickers": tickers,
        "priority": priority
    }


def main():
    """Simple testing run."""
    print("Running Orchestrator tests...")
    
    test_inputs = [
        {"request_type": "on_demand", "ticker": "AAPL", "user_query": None},
        {"request_type": "scheduled", "ticker": None, "user_query": "What is the status of Microsoft?"},
        {"request_type": "on_demand", "ticker": None, "user_query": "Explain what is happening to meta shares"},
        {"request_type": "scheduled", "ticker": None, "user_query": "Is NVDA trending upwards?"},
        {"request_type": "on_demand", "ticker": None, "user_query": "Should I sell AAPL or TSLA?"},
        {"request_type": "on_demand", "ticker": None, "user_query": "Analyze macro-economic trends in Europe."}
    ]

    for inp in test_inputs:
        res = orchestrate(inp)
        print(f"\nInput:  {inp}")
        print(f"Output: {res}")


if __name__ == "__main__":
    main()
