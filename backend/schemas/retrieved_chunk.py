from pydantic import BaseModel

class RetrievedChunk(BaseModel):
    """Schema representing a single retrieved article chunk."""
    id: str | None = None
    ticker: str
    source: str
    date: str
    text: str
    score: float | None = None
