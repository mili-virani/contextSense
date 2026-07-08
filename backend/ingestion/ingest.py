#!/usr/bin/env python3
import sys
import os
import uuid
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv

# Find workspace root: script is at backend/ingestion/ingest.py, so its grandparent's parent is the workspace root
script_path = Path(__file__).resolve()
workspace_root = script_path.parents[2]
env_path = workspace_root / ".env"

if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

class AlphaVantageRateLimitError(Exception):
    """Exception raised when Alpha Vantage rate limits are hit."""
    pass


# We import these after load_dotenv just in case dependencies or configuration are affected
try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, VectorParams, PointStruct
    from sentence_transformers import SentenceTransformer
    from transformers import AutoTokenizer
except ImportError as e:
    print(f"Error: Missing dependency. Make sure you are running in the correct virtual environment. {e}")
    sys.exit(1)


def chunk_text(text: str, tokenizer, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """
    Chunks text into ~chunk_size token chunks with overlap using the model's tokenizer.
    """
    # Tokenize the text into token IDs
    tokens = tokenizer.encode(text, add_special_tokens=False)
    
    if len(tokens) <= chunk_size:
        return [text]
        
    chunks = []
    start = 0
    while start < len(tokens):
        end = start + chunk_size
        chunk_tokens = tokens[start:end]
        chunk_text = tokenizer.decode(chunk_tokens, clean_up_tokenization_spaces=True)
        chunks.append(chunk_text)
        
        # Advance by step size (chunk_size - overlap)
        start += (chunk_size - overlap)
        
        # Stop if we've processed all tokens
        if start >= len(tokens):
            break
            
    return chunks


def main():
    if len(sys.argv) < 2:
        print("Usage: python ingest.py <TICKER>")
        sys.exit(1)
        
    ticker = sys.argv[1].upper().strip()
    if not ticker:
        print("Error: Ticker cannot be empty.")
        sys.exit(1)

    # Load configuration
    api_key = os.environ.get("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        print("Error: ALPHA_VANTAGE_API_KEY environment variable not set.")
        sys.exit(1)

    qdrant_url = os.environ.get("QDRANT_URL", "http://localhost:6333")
    print(f"Initializing Qdrant client at {qdrant_url}...")
    try:
        qdrant_client = QdrantClient(url=qdrant_url)
    except Exception as e:
        print(f"Error: Failed to connect to Qdrant at {qdrant_url}: {e}")
        sys.exit(1)

    # 1. Calls Alpha Vantage's NEWS_SENTIMENT endpoint for the given ticker, last 7 days
    now = datetime.now(timezone.utc)
    seven_days_ago = now - timedelta(days=7)
    time_from = seven_days_ago.strftime("%Y%m%dT%H%M")

    print(f"Fetching news sentiment for {ticker} from the last 7 days (since {seven_days_ago.strftime('%Y-%m-%d %H:%M UTC')})...")
    
    url = "https://www.alphavantage.co/query"
    params = {
        "function": "NEWS_SENTIMENT",
        "tickers": ticker,
        "time_from": time_from,
        "apikey": api_key,
        "sort": "LATEST",
        "limit": 100
    }

    try:
        time.sleep(1.2)
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
    except Exception as e:
        print(f"Error calling Alpha Vantage API: {e}")
        sys.exit(1)

    data = response.json()

    # Basic error handling for rate limits or API key issues
    if "Note" in data:
        raise AlphaVantageRateLimitError(f"Alpha Vantage Rate Limit: {data['Note']}")
    if "Information" in data:
        raise AlphaVantageRateLimitError(f"Alpha Vantage Rate Limit: {data['Information']}")
    if "Error Message" in data:
        print(f"Alpha Vantage Error: {data['Error Message']}")
        sys.exit(1)

    feed = data.get("feed", [])
    if not feed:
        print(f"No articles found for ticker {ticker} in the last 7 days.")
        sys.exit(0)

    print(f"Found {len(feed)} articles. Initializing embedding model and tokenizer...")

    # Load local sentence-transformers model and tokenizer
    try:
        model_name = "all-MiniLM-L6-v2"
        # Suppress long sequence warnings from tokenizer
        # pyrefly: ignore [missing-import]
        from transformers import logging as transformers_logging
        transformers_logging.set_verbosity_error()
        
        # Using huggingface hub / sentence-transformers model path
        model = SentenceTransformer(model_name)
        tokenizer = AutoTokenizer.from_pretrained(f"sentence-transformers/{model_name}")
    except Exception as e:
        print(f"Error loading sentence-transformer model: {e}")
        sys.exit(1)

    # 4. Ensure Qdrant collection "news_chunks" exists (dimension is 384 for all-MiniLM-L6-v2)
    collection_name = "news_chunks"
    try:
        if not qdrant_client.collection_exists(collection_name):
            print(f"Creating Qdrant collection '{collection_name}'...")
            qdrant_client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=384, distance=Distance.COSINE)
            )
    except Exception as e:
        print(f"Error checking/creating Qdrant collection: {e}")
        sys.exit(1)

    # Process, chunk, embed, and prepare upsert points
    points = []
    total_chunks = 0

    for article in feed:
        # Verify that the article is relevant to the target ticker
        ticker_sentiment = article.get("ticker_sentiment", [])
        is_relevant = False
        for ts in ticker_sentiment:
            if ts.get("ticker", "").upper().strip() == ticker:
                try:
                    relevance = float(ts.get("relevance_score", 0))
                    if relevance >= 0.1:  # Relevance threshold of 10%+
                        is_relevant = True
                        break
                except ValueError:
                    pass
        if not is_relevant:
            continue

        title = article.get("title") or ""
        summary = article.get("summary") or ""
        source = article.get("source") or "Unknown"
        time_published = article.get("time_published") or ""

        # Format date safely
        date_str = time_published
        try:
            if len(time_published) >= 15: # Expecting YYYYMMDDTHHMMSS
                dt = datetime.strptime(time_published[:15], "%Y%m%dT%H%M%S")
                date_str = dt.strftime("%Y-%m-%d")
            elif len(time_published) >= 13: # Expecting YYYYMMDDTHHMM
                dt = datetime.strptime(time_published[:13], "%Y%m%dT%H%M")
                date_str = dt.strftime("%Y-%m-%d")
        except Exception:
            pass

        # Combine title and summary to form the text
        article_text = f"{title}\n\n{summary}".strip()
        if not article_text:
            continue

        # Chunk the article's text
        chunks = chunk_text(article_text, tokenizer, chunk_size=500, overlap=50)
        if not chunks:
            continue

        # Embed each chunk
        try:
            embeddings = model.encode(chunks)
        except Exception as e:
            print(f"Error embedding chunks for article '{title[:30]}...': {e}")
            continue

        # Create PointStruct for each chunk
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            point_id = str(uuid.uuid4())
            points.append(
                PointStruct(
                    id=point_id,
                    vector=embedding.tolist(),
                    payload={
                        "ticker": ticker,
                        "source": source,
                        "date": date_str,
                        "text": chunk
                    }
                )
            )
            total_chunks += 1

    if not points:
        print("No valid chunks were generated from the articles.")
        sys.exit(0)

    # Upsert to Qdrant
    print(f"Upserting {total_chunks} chunks into Qdrant collection '{collection_name}'...")
    try:
        qdrant_client.upsert(
            collection_name=collection_name,
            points=points
        )
    except Exception as e:
        print(f"Error upserting points to Qdrant: {e}")
        sys.exit(1)

    print(f"Successfully ingested {total_chunks} chunks.")


if __name__ == "__main__":
    main()
