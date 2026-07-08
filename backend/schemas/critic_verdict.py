from typing import List, Optional
from pydantic import BaseModel, Field

class CriticVerdict(BaseModel):
    """Schema representing the evaluation verdict of the Critic Agent."""
    approved: bool = Field(..., description="Whether the prediction is approved for downstream writing")
    flags: List[str] = Field(default_factory=list, description="Quality warnings, mismatch messages, or review flags")
    final_confidence: float = Field(..., ge=0.0, le=1.0, description="The Critic's adjusted confidence score")
    revision_notes: Optional[str] = Field(None, description="Detailed guidance for revision if approved is false")
