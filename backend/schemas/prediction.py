from typing import Literal, List
from pydantic import BaseModel, Field

class Prediction(BaseModel):
    """Schema representing a price direction prediction for a stock ticker."""
    direction: Literal["up", "down", "neutral"]
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score from 0 to 1")
    horizon_days: int = Field(..., description="Forecast horizon in days")
    reasoning_summary: str = Field(..., description="Chain-of-thought step-by-step reasoning summary")
    cited_event_ids: List[str] = Field(default_factory=list, description="IDs of events cited during prediction")
