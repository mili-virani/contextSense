import os
from datetime import datetime, timezone
from typing import Any, List, Literal, Mapping, Optional

from pydantic import BaseModel, Field

try:
    import asyncpg
except ImportError:  # pragma: no cover - optional at import time for lightweight consumers
    asyncpg = None


class RunLog(BaseModel):
    """Schema representing a persisted pipeline run for outcome tracking and Critic analysis."""

    ticker: str = Field(..., description="Stock ticker analyzed in this run")
    timestamp: datetime = Field(..., description="UTC timestamp when the pipeline run completed")
    direction: Literal["up", "down", "neutral"] = Field(
        ..., description="Predicted price direction from the final Predictor output"
    )
    confidence: float = Field(..., ge=0.0, le=1.0, description="Final confidence score for the run")
    approved: bool = Field(..., description="Whether the Critic approved the prediction")
    horizon_days: Optional[int] = Field(
        None, description="Forecast horizon in days; null when no prediction was produced"
    )
    cited_event_ids: List[str] = Field(
        default_factory=list, description="Event IDs cited in the final prediction"
    )
    actual_outcome: Optional[str] = Field(
        None,
        description="Observed market outcome after horizon_days; filled in later for backtesting",
    )
    reasoning_summary: str = Field(
        default="", description="Chain-of-thought step-by-step reasoning summary"
    )
    critic_flags: List[str] = Field(
        default_factory=list, description="Quality warnings, mismatch messages, or review flags"
    )
    technical_features: Optional[dict] = Field(
        None, description="Technical indicators (momentum, rsi, volume_change, ma_cross)"
    )
    events: Optional[List[dict]] = Field(
        None, description="Extracted news events and drivers"
    )

    @classmethod
    def from_pipeline_state(cls, state: Mapping[str, Any]) -> "RunLog":
        """Build a RunLog from the terminal LangGraph pipeline state."""
        prediction = state.get("prediction")
        verdict = state.get("verdict")

        ticker = (state.get("ticker") or "UNKNOWN").upper().strip()
        direction = prediction.direction if prediction else "neutral"
        confidence = (
            verdict.final_confidence
            if verdict
            else (prediction.confidence if prediction else 0.0)
        )
        approved = verdict.approved if verdict else False
        horizon_days = prediction.horizon_days if prediction else None
        cited_event_ids = list(prediction.cited_event_ids) if prediction else []
        reasoning_summary = prediction.reasoning_summary if prediction and prediction.reasoning_summary else ""
        critic_flags = list(verdict.flags) if verdict and verdict.flags else []

        technical_features = state.get("technical_features") or None
        raw_events = state.get("events")
        events = None
        if raw_events:
            events = []
            for e in raw_events:
                if hasattr(e, "model_dump"):
                    events.append(e.model_dump())
                elif hasattr(e, "dict"):
                    events.append(e.dict())
                else:
                    events.append(dict(e))

        return cls(
            ticker=ticker,
            timestamp=datetime.now(timezone.utc),
            direction=direction,
            confidence=confidence,
            approved=approved,
            horizon_days=horizon_days,
            cited_event_ids=cited_event_ids,
            actual_outcome=None,
            reasoning_summary=reasoning_summary,
            critic_flags=critic_flags,
            technical_features=technical_features,
            events=events,
        )


async def persist_run_log(run_log: RunLog) -> None:
    """Insert a run log row into Postgres using DATABASE_URL."""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("Warning: DATABASE_URL not set. Skipping run log persistence.")
        return

    if asyncpg is None:
        raise ImportError("asyncpg is required to persist run logs")

    conn = await asyncpg.connect(database_url, statement_cache_size=0)
    try:
        import json
        await conn.execute(
            """
            INSERT INTO run_logs (
                ticker,
                timestamp,
                direction,
                confidence,
                approved,
                horizon_days,
                cited_event_ids,
                actual_outcome,
                reasoning_summary,
                critic_flags,
                technical_features,
                events
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            """,
            run_log.ticker,
            run_log.timestamp,
            run_log.direction,
            run_log.confidence,
            run_log.approved,
            run_log.horizon_days,
            run_log.cited_event_ids,
            run_log.actual_outcome,
            run_log.reasoning_summary,
            run_log.critic_flags,
            json.dumps(run_log.technical_features) if run_log.technical_features else None,
            json.dumps(run_log.events) if run_log.events else None,
        )
    finally:
        await conn.close()
