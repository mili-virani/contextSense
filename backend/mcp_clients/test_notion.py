#!/usr/bin/env python3
import sys
from datetime import datetime
from backend.mcp_clients.notion_mcp_client import NotionClient

def main():
    print("Initializing Notion Client...")
    try:
        client = NotionClient()
    except Exception as e:
        print(f"Failed to initialize NotionClient: {e}")
        sys.exit(1)

    # Validate configuration exists
    if not client.api_key:
        print("Error: NOTION_API_KEY environment variable is not set.")
        sys.exit(1)
    if not client.database_id:
        print("Error: NOTION_DATABASE_ID environment variable is not set.")
        sys.exit(1)

    print(f"Targeting Database ID: {client.database_id}")

    # Set up dummy values
    ticker = "TEST"
    direction = "up"
    confidence = 0.75
    date_str = datetime.today().strftime("%Y-%m-%d")
    key_citation = "This is a verification test to confirm Notion API integration and database permissions are set up correctly."

    print(f"Appending row to database: Ticker={ticker}, Date={date_str}, Direction={direction}, Confidence={confidence}...")
    try:
        result = client.append_row(
            ticker=ticker,
            date=date_str,
            direction=direction,
            confidence=confidence,
            key_citation=key_citation
        )
        print("Row appended successfully!")
        print(f"Created Page URL: {result.get('url')}")
    except Exception as e:
        print(f"Error appending row to Notion database: {e}")
        # If response body contains more information, try to print it
        if hasattr(e, 'response') and e.response is not None:
            print(f"Details: {e.response.text}")
        sys.exit(1)

if __name__ == "__main__":
    main()
