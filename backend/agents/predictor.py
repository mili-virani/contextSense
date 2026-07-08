#!/usr/bin/env python3
"""
Predictor Agent implementation.

This agent makes price direction predictions based on extracted market events
and technical features. It uses DeepSeek V4 Flash with a Chain-of-Thought system prompt.
"""

import os
import sys
import json
import asyncio
import requests
import pandas as pd
from pathlib import Path
from typing import List, Literal, Optional

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
    from openai import AsyncOpenAI
    from pydantic import ValidationError
except ImportError as e:
    print(f"Error: Missing dependency: {e}")
    sys.exit(1)

from backend.schemas.event import Event
from backend.schemas.prediction import Prediction
from backend.agents.analyst import get_deepseek_client

class AlphaVantageRateLimitError(Exception):
    """Exception raised when Alpha Vantage rate limits are hit."""
    pass

# In-memory cache for daily time series calls
# Keys: tuple of (ticker, endpoint), Values: parsed JSON response dict
_av_time_series_cache = {}

PREDICTOR_SYSTEM_PROMPT = """You are an expert stock market predictor assistant.
Your task is to analyze a set of extracted news events and technical indicators for a given stock ticker, and make a price direction forecast.

You MUST perform your reasoning in this exact order:
1. EVENT-BY-EVENT ANALYSIS: For each event in the input list, state what price direction it implies (up, down, or neutral) and the strength of this implication (weak, moderate, or strong).
2. EVENT CONSISTENCY: State whether the events overall agree with each other or conflict.
3. TECHNICAL INDICATORS ALIGNMENT: Analyze the technical features. State whether the technical indicators agree or disagree with the event-based analysis.
4. FINAL PREDICTION AND CONVERGENCE: Combine both views to formulate your final direction, confidence score, and time horizon.

You must output your complete step-by-step reasoning for the four steps above in the `reasoning_summary` field.

The output must be a valid JSON object matching the following structure:
{{
  "direction": "up" | "down" | "neutral",
  "confidence": <float between 0.0 and 1.0>,
  "horizon_days": <integer representing forecast horizon, e.g., 7, 30, 90>,
  "reasoning_summary": "<Your detailed step-by-step reasoning trace covering steps 1, 2, 3, and 4>",
  "cited_event_ids": [<list of strings representing the IDs of the events that were most influential to this prediction>]
}}

Do not include any formatting or explanation outside the JSON output.
"""


def get_mock_technical_features() -> dict:
    """Fallback mock indicators in case of Alpha Vantage query limits or failure."""
    return {
        "momentum": 0.025,
        "rsi": 55.4,
        "volume_change": 0.12,
        "ma_cross": "none"
    }


async def get_technical_features(ticker: str) -> dict:
    """
    Fetches daily stock history from Alpha Vantage and computes technical indicators:
    - momentum: % change in close price over the last 5 trading days.
    - rsi: a simple 14-day Relative Strength Index calculated directly with pandas.
    - volume_change: % change in average volume (last 5 days vs prior 20 days).
    - ma_cross: 'bullish' if 10-day MA just crossed above 50-day MA, 'bearish' if crossed below, else 'none'.
    """
    api_key = os.environ.get("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        print("Warning: ALPHA_VANTAGE_API_KEY not set. Using mock technical features.")
        return get_mock_technical_features()

    ticker_clean = ticker.upper().strip()
    cache_key = (ticker_clean, "TIME_SERIES_DAILY")

    try:
        if cache_key in _av_time_series_cache:
            print(f"Using cached daily price history for ticker '{ticker_clean}'...")
            data = _av_time_series_cache[cache_key]
        else:
            url = "https://www.alphavantage.co/query"
            params = {
                "function": "TIME_SERIES_DAILY",
                "symbol": ticker_clean,
                "apikey": api_key,
                "outputsize": "compact"
            }

            print(f"Fetching daily price history for ticker '{ticker_clean}' from Alpha Vantage...")
            await asyncio.sleep(1.2)
            response = requests.get(url, params=params, timeout=20)
            response.raise_for_status()
            data = response.json()

            # Check for rate limit warnings or error messages
            if "Note" in data:
                raise AlphaVantageRateLimitError(f"Alpha Vantage Rate Limit: {data['Note']}")
            if "Information" in data:
                raise AlphaVantageRateLimitError(f"Alpha Vantage Rate Limit: {data['Information']}")
            if "Error Message" in data:
                print(f"Alpha Vantage Error: {data['Error Message']}")
                return get_mock_technical_features()

            # Save valid data to cache
            _av_time_series_cache[cache_key] = data

        time_series = data.get("Time Series (Daily)")
        if not time_series:
            print("No 'Time Series (Daily)' key found in Alpha Vantage response.")
            return get_mock_technical_features()

        # Parse data into DataFrame
        df_list = []
        for date_str, daily in time_series.items():
            df_list.append({
                "date": date_str,
                "close": float(daily["4. close"]),
                "volume": float(daily["5. volume"])
            })

        df = pd.DataFrame(df_list)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

        if len(df) < 52:
            print(f"Insufficient history ({len(df)} days) to compute rolling metrics. Minimum required: 52.")
            return get_mock_technical_features()

        # 1. Momentum (% change over last 5 trading days)
        close_today = df["close"].iloc[-1]
        close_5_days_ago = df["close"].iloc[-6]
        momentum = (close_today / close_5_days_ago) - 1.0

        # 2. RSI (14 days)
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)

        avg_gain = gain.rolling(window=14).mean()
        avg_loss = loss.rolling(window=14).mean()
        rs = avg_gain / avg_loss.replace(0.0, 1e-9)
        rsi_series = 100.0 - (100.0 / (1.0 + rs))
        rsi = rsi_series.iloc[-1]

        # 3. Volume Change (last 5 average vs prior 20 average)
        vol_5_avg = df["volume"].iloc[-5:].mean()
        vol_prior_20_avg = df["volume"].iloc[-25:-5].mean()
        volume_change = (vol_5_avg / (vol_prior_20_avg or 1.0)) - 1.0

        # 4. Moving Average Cross (10-day MA crossing 50-day MA)
        df["ma10"] = df["close"].rolling(window=10).mean()
        df["ma50"] = df["close"].rolling(window=50).mean()

        ma10_today = df["ma10"].iloc[-1]
        ma50_today = df["ma50"].iloc[-1]
        ma10_yesterday = df["ma10"].iloc[-2]
        ma50_yesterday = df["ma50"].iloc[-2]

        if ma10_yesterday <= ma50_yesterday and ma10_today > ma50_today:
            ma_cross = "bullish"
        elif ma10_yesterday >= ma50_yesterday and ma10_today < ma50_today:
            ma_cross = "bearish"
        else:
            ma_cross = "none"

        features = {
            "momentum": float(momentum),
            "rsi": float(rsi),
            "volume_change": float(volume_change),
            "ma_cross": ma_cross
        }
        print(f"Calculated technical features: {features}")
        return features

    except AlphaVantageRateLimitError:
        raise
    except Exception as e:
        print(f"Error calculating technical indicators for {ticker}: {e}. Returning mock indicators.")
        return get_mock_technical_features()


def get_mock_prediction(events: List[Event], technical_features: dict, ticker: str, feedback: Optional[str] = None) -> Prediction:
    """Generates heuristic-based mock prediction if LLM API calls fail."""
    avg_event_sentiment = 0.0
    if events:
        avg_event_sentiment = sum(e.sentiment_score for e in events) / len(events)

    momentum = technical_features.get("momentum", 0.0)
    rsi = technical_features.get("rsi", 50.0)
    ma_cross = technical_features.get("ma_cross", "none")

    # Direction score calculation
    score = avg_event_sentiment * 0.6 + momentum * 2.0
    if ma_cross == "bullish":
        score += 0.25
    elif ma_cross == "bearish":
        score -= 0.25

    if rsi > 70:
        score -= 0.1
    elif rsi < 30:
        score += 0.15

    if score > 0.12:
        direction = "up"
    elif score < -0.12:
        direction = "down"
    else:
        direction = "neutral"

    # Revision loop simulation: change direction if feedback indicates it was rejected
    if feedback:
        feedback_lower = feedback.lower()
        if "previous prediction of up was rejected" in feedback_lower:
            direction = "neutral" if direction == "up" else "down"
        elif "previous prediction of down was rejected" in feedback_lower:
            direction = "neutral" if direction == "down" else "up"
        elif "previous prediction of neutral was rejected" in feedback_lower:
            direction = "up"

    confidence = min(max(abs(score) + 0.5, 0.5), 0.95)
    cited_ids = [e.source_ids[0] for e in events if e.source_ids] if events else []

    reasoning = (
        f"[MOCK REASONING TRACE (DeepSeek API Fallback)]\n"
        f"1. EVENT-BY-EVENT ANALYSIS: Analyzed {len(events)} events for {ticker}. Average event sentiment score: {avg_event_sentiment:.2f}.\n"
        f"2. EVENT CONSISTENCY: Evaluated sentiment profiles for consistency across events.\n"
        f"3. TECHNICAL INDICATORS ALIGNMENT: Technical indicators list momentum={momentum:.3f}, rsi={rsi:.1f}, ma_cross={ma_cross}. Combined indicators score = {score:.2f}.\n"
        f"4. FINAL PREDICTION AND CONVERGENCE: Settled on direction forecast = {direction} with {confidence:.2f} confidence over a 30-day horizon."
    )

    return Prediction(
        direction=direction,
        confidence=confidence,
        horizon_days=30,
        reasoning_summary=reasoning,
        cited_event_ids=list(set(cited_ids))[:3]
    )


def parse_and_validate_prediction(json_str: str) -> Prediction:
    """Helper to parse JSON and construct the Prediction model."""
    data = json.loads(json_str)
    return Prediction(**data)


async def predict(events: List[Event], technical_features: dict, ticker: str, feedback: Optional[str] = None) -> Prediction:
    """
    Formulates a stock price prediction using events, technical indicators, and a DeepSeek LLM.
    
    Args:
        events (List[Event]): List of extracted market events.
        technical_features (dict): Technical indicators dictionary.
        ticker (str): Stock ticker of interest.
        feedback (str, optional): Revision instructions from the Critic.
        
    Returns:
        Prediction: Forecast direction, confidence, horizon, and reasoning summary.
    """
    client = get_deepseek_client()
    if not client:
        print("Warning: DEEPSEEK_API_KEY not set. Using mock heuristic prediction.")
        return get_mock_prediction(events, technical_features, ticker, feedback)

    # Format input payload for the LLM prompt
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
    
    user_payload = {
        "ticker": ticker,
        "events": events_payload,
        "technical_features": technical_features
    }
    if feedback:
        user_payload["feedback"] = feedback
    
    messages = [
        {"role": "system", "content": PREDICTOR_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(user_payload, indent=2)}
    ]
    
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

    try:
        # First attempt
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.2,
            timeout=30
        )
        content = response.choices[0].message.content
        return parse_and_validate_prediction(content)

    except Exception as e:
        print(f"Warning: Predictor first attempt failed: {e}")
        
        # If billing/insufficient balance issue, fall back immediately to mock
        if "402" in str(e) or "Insufficient Balance" in str(e):
            print("DeepSeek Billing/Balance issue detected. Falling back to mock prediction.")
            return get_mock_prediction(events, technical_features, ticker, feedback)
            
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
                temperature=0.2,
                timeout=30
            )
            content = response.choices[0].message.content
            return parse_and_validate_prediction(content)
            
        except Exception as retry_err:
            print(f"Error: Predictor retry failed: {retry_err}. Falling back to mock prediction.")
            return get_mock_prediction(events, technical_features, ticker, feedback)


async def run_manual_test():
    """Runs the complete Retriever -> Analyst -> Technical Indicators -> Predictor agent pipeline."""
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
    technical_features = await get_technical_features(test_ticker)
    
    print("\n==================================================")
    print("STEP 4: Running Predictor Agent...")
    prediction = await predict(events, technical_features, test_ticker)
    
    print("\n==================================================")
    print("FINAL PREDICTION RESULTS:")
    print(f"Ticker: {test_ticker}")
    print(f"Forecast Direction: {prediction.direction.upper()}")
    print(f"Confidence Score: {prediction.confidence:.2%}")
    print(f"Horizon Days: {prediction.horizon_days} days")
    print(f"Cited Event IDs: {prediction.cited_event_ids}")
    print("\nReasoning Summary Trace:")
    print(prediction.reasoning_summary)
    print("==================================================")


if __name__ == "__main__":
    asyncio.run(run_manual_test())
