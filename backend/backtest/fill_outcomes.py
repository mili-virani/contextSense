#!/usr/bin/env python3
"""
fill_outcomes.py

Queries run_logs where actual_outcome IS NULL and the horizon has passed.
Fetches daily prices from Alpha Vantage and updates the database with actual outcomes.

This is a forward-testing module designed to work under free-tier API limitations.
"""

import sys
import os
import time
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict
import requests

# Ensure workspace root is in sys.path to enable imports of backend.*
script_path = Path(__file__).resolve()
backend_dir = script_path.parents[1]
workspace_root = script_path.parents[2]

# Load dotenv configuration
from dotenv import load_dotenv
env_path = workspace_root / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

if str(workspace_root) not in sys.path:
    sys.path.append(str(workspace_root))

try:
    import asyncpg
except ImportError:
    print("Error: Missing asyncpg dependency. Make sure you are in the correct virtual environment.")
    sys.exit(1)

from backend.ingestion.ingest import AlphaVantageRateLimitError


async def get_pending_run_logs(conn):
    """
    Query run_logs where actual_outcome is NULL and the prediction horizon has passed.
    """
    query = """
        SELECT id, ticker, timestamp, direction, confidence, approved, horizon_days
        FROM run_logs
        WHERE actual_outcome IS NULL
          AND horizon_days IS NOT NULL
          AND (timestamp + (horizon_days * interval '1 day')) <= NOW()
    """
    return await conn.fetch(query)


async def update_run_log_outcome(conn, row_id: int, outcome: str):
    """
    Update the actual_outcome of a run log row in PostgreSQL.
    """
    query = """
        UPDATE run_logs
        SET actual_outcome = $1
        WHERE id = $2
    """
    await conn.execute(query, outcome, row_id)


async def fetch_daily_prices(ticker: str, api_key: str) -> dict:
    """
    Fetch historical daily prices from Alpha Vantage with full history.
    Implements retries and sleeps for API rate limit compliance.
    """
    url = "https://www.alphavantage.co/query"
    params = {
        "function": "TIME_SERIES_DAILY",
        "symbol": ticker.upper().strip(),
        "apikey": api_key,
        "outputsize": "full"
    }

    max_retries = 3
    for attempt in range(max_retries):
        print(f"Fetching daily price history for {ticker} (attempt {attempt + 1}/{max_retries})...")
        await asyncio.sleep(1.2)
        response = requests.get(url, params=params, timeout=20)
        response.raise_for_status()
        data = response.json()

        # Check for rate limits utilizing the shared exception format
        if "Note" in data:
            note = data["Note"]
            print(f"Alpha Vantage Note: {note}")
            if "25 requests per day" in note or "daily rate limit" in note.lower():
                raise AlphaVantageRateLimitError(f"Alpha Vantage Daily Rate Limit Exceeded: {note}")
            print("Assuming minute rate limit hit. Sleeping for 65 seconds...")
            await asyncio.sleep(65)
            continue

        if "Information" in data:
            info = data["Information"]
            print(f"Alpha Vantage Information: {info}")
            if "daily" in info.lower():
                raise AlphaVantageRateLimitError(f"Alpha Vantage Daily Rate Limit Exceeded: {info}")
            print("Assuming minute rate limit hit. Sleeping for 65 seconds...")
            await asyncio.sleep(65)
            continue

        if "Error Message" in data:
            print(f"Alpha Vantage Error for {ticker}: {data['Error Message']}")
            return None

        time_series = data.get("Time Series (Daily)")
        if not time_series:
            print(f"No 'Time Series (Daily)' key found in response for {ticker}.")
            return None

        return time_series

    raise AlphaVantageRateLimitError("Alpha Vantage Rate Limit: Maximum retries exceeded.")


def get_price_on_or_closest_to(time_series: dict, target_date):
    """
    Find the closing price on target_date, or the closest available trading day.
    """
    dates_and_prices = []
    for date_str, daily_data in time_series.items():
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d").date()
            close_val = float(daily_data["4. close"])
            dates_and_prices.append((dt, close_val))
        except (ValueError, KeyError):
            continue

    if not dates_and_prices:
        return None

    # Find the entry with the minimum absolute difference in days
    closest_item = min(dates_and_prices, key=lambda x: abs((x[0] - target_date).days))
    return closest_item[0], closest_item[1]


async def main_async():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("Error: DATABASE_URL environment variable is not set.")
        sys.exit(1)

    api_key = os.environ.get("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        print("Error: ALPHA_VANTAGE_API_KEY environment variable is not set.")
        sys.exit(1)

    print(f"Connecting to database: {database_url.split('@')[-1]}")
    conn = await asyncpg.connect(database_url, statement_cache_size=0)
    try:
        rows = await get_pending_run_logs(conn)
        if not rows:
            print("No pending run logs found to fill outcomes for.")
            return

        print(f"Found {len(rows)} pending run logs where prediction horizon has passed.")

        # Group by ticker to optimize and avoid duplicate queries
        ticker_to_rows = defaultdict(list)
        for row in rows:
            ticker_to_rows[row['ticker'].upper().strip()].append(row)

        updated_count = 0
        total_tickers = len(ticker_to_rows)
        
        for idx, (ticker, ticker_rows) in enumerate(ticker_to_rows.items(), 1):
            print(f"\n[{idx}/{total_tickers}] Processing ticker {ticker} ({len(ticker_rows)} pending rows)")
            
            try:
                time_series = await fetch_daily_prices(ticker, api_key)
                if not time_series:
                    print(f"Skipping ticker {ticker} due to fetch error.")
                    continue
            except AlphaVantageRateLimitError as e:
                print(f"\nRate limit error: {e}")
                print("Aborting remaining updates to respect Alpha Vantage rate limits.")
                break

            for row in ticker_rows:
                start_date = row['timestamp'].date()
                end_date = start_date + timedelta(days=row['horizon_days'])

                # Find start price
                start_res = get_price_on_or_closest_to(time_series, start_date)
                if not start_res:
                    print(f"  Row {row['id']}: Could not find start price for date {start_date}")
                    continue
                act_start_date, start_price = start_res

                # Find end price
                end_res = get_price_on_or_closest_to(time_series, end_date)
                if not end_res:
                    print(f"  Row {row['id']}: Could not find end price for date {end_date}")
                    continue
                act_end_date, end_price = end_res

                if act_start_date == act_end_date:
                    print(f"  Row {row['id']}: Start and end dates resolved to the same day ({act_start_date}). Skipping.")
                    continue

                pct_change = (end_price - start_price) / start_price
                
                # Classify outcome based on +/- 1% threshold
                if pct_change > 0.01:
                    outcome = "up"
                elif pct_change < -0.01:
                    outcome = "down"
                else:
                    outcome = "neutral"

                print(f"  Row {row['id']}: {start_date} ({act_start_date}) price: {start_price:.2f} -> "
                      f"{end_date} ({act_end_date}) price: {end_price:.2f} | "
                      f"Change: {pct_change:+.2%} | Outcome: {outcome.upper()}")

                await update_run_log_outcome(conn, row['id'], outcome)
                updated_count += 1

            # Sleep 12 seconds between ticker queries to avoid rate limit warnings (5 req/min limit)
            if idx < total_tickers:
                print("Waiting 12 seconds to respect Alpha Vantage rate limits...")
                await asyncio.sleep(12)

        print(f"\nCompleted. Filled outcomes for {updated_count} rows.")

    finally:
        await conn.close()


def main():
    try:
        asyncio.run(main_async())
    except Exception as e:
        print(f"Execution failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
