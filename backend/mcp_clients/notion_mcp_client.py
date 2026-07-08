import os
import re
import requests
from dotenv import load_dotenv

# Load env variables dynamically if path is found, otherwise default search
try:
    from pathlib import Path
    script_path = Path(__file__).resolve()
    workspace_root = script_path.parents[2]
    env_path = workspace_root / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
    else:
        load_dotenv()
except Exception:
    load_dotenv()


class NotionClient:
    """
    A minimal client to connect to the Notion API and append rows to a tracking database.
    """
    def __init__(self, api_key: str = None, database_id: str = None):
        self.api_key = api_key or os.environ.get("NOTION_API_KEY")
        raw_db_id = database_id or os.environ.get("NOTION_DATABASE_ID")
        self.database_id = self._extract_database_id(raw_db_id) if raw_db_id else None
        
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json"
        }

    def _extract_database_id(self, db_id_or_url: str) -> str:
        """
        Extracts the 32-character hexadecimal database ID from a Notion URL or raw string.
        """
        db_id_or_url = db_id_or_url.strip()
        # Look for 32 hex characters in a row (removing hyphens if present)
        match = re.search(r'([a-fA-F0-9]{32})', db_id_or_url.replace('-', ''))
        if match:
            return match.group(1)
        return db_id_or_url

    def append_row(self, ticker: str, date: str, direction: str, confidence: float, key_citation: str) -> dict:
        """
        Appends one row to the database at NOTION_DATABASE_ID.
        
        Args:
            ticker (str): Stock ticker (e.g. 'TEST' or 'AAPL')
            date (str): ISO-formatted date string (e.g. '2026-07-04')
            direction (str): Direction/sentiment select value ('Up', 'Down', 'Neutral')
            confidence (float): Confidence score (0.0 to 1.0)
            key_citation (str): Context or source snippet
            
        Returns:
            dict: The JSON response dictionary from the Notion API.
        """
        if not self.api_key:
            raise ValueError("NOTION_API_KEY is not set or passed.")
        if not self.database_id:
            raise ValueError("NOTION_DATABASE_ID is not set or passed.")

        url = "https://api.notion.com/v1/pages"
        
        # Format direction matching Notion's select options: 'Up', 'Down', 'Neutral'
        formatted_direction = direction.strip().capitalize()
        if formatted_direction not in ["Up", "Down", "Neutral"]:
            # Fallback to capitalised string in case of custom configurations
            pass

        payload = {
            "parent": {
                "database_id": self.database_id
            },
            "properties": {
                "Name": {
                    "title": [
                        {
                            "text": {
                                "content": f"Prediction for {ticker}"
                            }
                        }
                    ]
                },
                "Ticker": {
                    "rich_text": [
                        {
                            "text": {
                                "content": ticker
                            }
                        }
                    ]
                },
                "Date": {
                    "date": {
                        "start": date
                    }
                },
                "Direction": {
                    "select": {
                        "name": formatted_direction
                    }
                },
                "Confidence": {
                    "number": confidence
                },
                "Key Citation": {
                    "rich_text": [
                        {
                            "text": {
                                "content": key_citation
                            }
                        }
                    ]
                }
            }
        }

        response = requests.post(url, headers=self.headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()
