from typing import Literal, List
from pydantic import BaseModel, Field

class Event(BaseModel):
    """Schema representing an extracted market event or driver."""
    event_type: Literal["earnings_beat", "earnings_miss", "guidance_change",
                        "regulatory_risk", "management_change", "other"]
    description: str
    sentiment_score: float = Field(..., ge=-1.0, le=1.0, description="Sentiment impact from -1 (most negative) to 1 (most positive)")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Extraction confidence from 0 to 1")
    source_ids: List[str] = Field(default_factory=list, description="IDs of the source chunks used to extract this event")
