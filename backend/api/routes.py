import json
from fastapi import APIRouter, HTTPException, Query, Request
from typing import Optional, List
from pydantic import BaseModel
from backend.backtest.report import fetch_graded_logs, compute_accuracy_metrics

router = APIRouter()

class RunRequest(BaseModel):
    ticker: Optional[str] = None
    query: Optional[str] = None

@router.post("/predictions/run")
async def run_prediction_pipeline(req: RunRequest):
    """
    Run the multi-agent prediction pipeline for a given ticker or query.
    This saves the outcome directly to PostgreSQL, and returns the result state.
    """
    from backend.pipeline import async_run_pipeline
    
    ticker_val = req.ticker.upper().strip() if req.ticker else None
    query_val = req.query.strip() if req.query else None
    
    if not ticker_val and not query_val:
        raise HTTPException(
            status_code=400,
            detail="Either ticker or query must be provided to run analysis."
        )
        
    try:
        # Run pipeline
        final_state = await async_run_pipeline(
            ticker=ticker_val,
            user_query=query_val,
            request_type="on_demand"
        )
        
        prediction = final_state.get("prediction")
        verdict = final_state.get("verdict")
        ticker = (final_state.get("ticker") or "UNKNOWN").upper().strip()
        
        # Serialize events
        raw_events = final_state.get("events")
        events = []
        if raw_events:
            for e in raw_events:
                if hasattr(e, "model_dump"):
                    events.append(e.model_dump())
                elif hasattr(e, "dict"):
                    events.append(e.dict())
                else:
                    events.append(dict(e))
        
        return {
            "status": "success",
            "ticker": ticker,
            "direction": prediction.direction if prediction else "neutral",
            "confidence": verdict.final_confidence if verdict else (prediction.confidence if prediction else 0.0),
            "approved": verdict.approved if verdict else False,
            "horizon_days": prediction.horizon_days if prediction else None,
            "reasoning_summary": prediction.reasoning_summary if prediction else "",
            "critic_flags": list(verdict.flags) if verdict else [],
            "technical_features": final_state.get("technical_features") or None,
            "events": events or None
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Pipeline execution failed: {str(e)}"
        )


@router.get("/predictions")
async def get_predictions(
    request: Request,
    ticker: Optional[str] = Query(None, description="Filter predictions by ticker symbol"),
    approved: Optional[bool] = Query(None, description="Filter approved-only predictions"),
    page: int = Query(1, ge=1, description="Page number for pagination"),
    limit: int = Query(10, ge=1, le=100, description="Number of items per page")
):
    """
    Get paginated run logs with optional filtering by ticker and approval status.
    Ordered by most recent first.
    """
    where_clauses = []
    args = []
    arg_idx = 1

    if ticker:
        where_clauses.append(f"ticker = ${arg_idx}")
        args.append(ticker.upper().strip())
        arg_idx += 1

    if approved is not None:
        where_clauses.append(f"approved = ${arg_idx}")
        args.append(approved)
        arg_idx += 1

    where_str = ""
    if where_clauses:
        where_str = "WHERE " + " AND ".join(where_clauses)

    count_query = f"SELECT COUNT(*) FROM run_logs {where_str}"

    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        # Get total count
        total_count = await conn.fetchval(count_query, *args)

        # Get paginated data including new jsonb columns
        offset = (page - 1) * limit
        data_query = f"""
            SELECT id, ticker, timestamp, direction, confidence, approved, horizon_days, actual_outcome, reasoning_summary, critic_flags, technical_features, events
            FROM run_logs
            {where_str}
            ORDER BY timestamp DESC
            LIMIT ${arg_idx} OFFSET ${arg_idx + 1}
        """
        rows = await conn.fetch(data_query, *(args + [limit, offset]))

    predictions = []
    for r in rows:
        tech = r.get("technical_features")
        if isinstance(tech, str):
            tech = json.loads(tech)
            
        evts = r.get("events")
        if isinstance(evts, str):
            evts = json.loads(evts)

        predictions.append({
            "id": r["id"],
            "ticker": r["ticker"],
            "timestamp": r["timestamp"],
            "direction": r["direction"],
            "confidence": r["confidence"],
            "approved": r["approved"],
            "horizon_days": r["horizon_days"],
            "actual_outcome": r["actual_outcome"],
            "reasoning_summary": r.get("reasoning_summary", ""),
            "critic_flags": r.get("critic_flags") or [],
            "technical_features": tech,
            "events": evts
        })

    return {
        "data": predictions,
        "total_count": total_count,
        "page": page,
        "limit": limit
    }


@router.get("/predictions/{ticker}")
async def get_prediction_detail(request: Request, ticker: str):
    """
    Get the full details of the most recent pipeline run for a specific stock ticker.
    """
    query = """
        SELECT id, ticker, timestamp, direction, confidence, approved, horizon_days, cited_event_ids, actual_outcome, reasoning_summary, critic_flags, technical_features, events
        FROM run_logs
        WHERE ticker = $1
        ORDER BY timestamp DESC
        LIMIT 1
    """
    
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, ticker.upper().strip())

    if not row:
        raise HTTPException(
            status_code=404, 
            detail=f"No run logs found for ticker '{ticker}'"
        )

    tech = row.get("technical_features")
    if isinstance(tech, str):
        tech = json.loads(tech)
        
    evts = row.get("events")
    if isinstance(evts, str):
        evts = json.loads(evts)

    chunks = []
    from qdrant_client import QdrantClient
    import os
    qdrant_url = os.environ.get("QDRANT_URL", "http://localhost:6333")
    try:
        qdrant_client = QdrantClient(url=qdrant_url)
        cited_ids = row.get("cited_event_ids") or []
        if cited_ids:
            records = qdrant_client.retrieve(
                collection_name="news_chunks",
                ids=list(cited_ids)
            )
            for record in records:
                payload = record.payload or {}
                chunks.append({
                    "id": str(record.id),
                    "text": payload.get("text", ""),
                    "source": payload.get("source", "Unknown"),
                    "date": payload.get("date", "")
                })
    except Exception as q_err:
        print(f"Warning: Failed to retrieve source chunks from Qdrant: {q_err}")

    return {
        "id": row["id"],
        "ticker": row["ticker"],
        "timestamp": row["timestamp"],
        "direction": row["direction"],
        "confidence": row["confidence"],
        "approved": row["approved"],
        "horizon_days": row["horizon_days"],
        "cited_event_ids": row["cited_event_ids"] or [],
        "actual_outcome": row["actual_outcome"],
        "reasoning_summary": row.get("reasoning_summary", ""),
        "critic_flags": row.get("critic_flags") or [],
        "technical_features": tech,
        "events": evts,
        "chunks": chunks
    }


@router.get("/backtest/summary")
async def get_backtest_summary(request: Request):
    """
    Run backtest summary metrics logic and return accuracy stats in JSON format.
    """
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        rows = await fetch_graded_logs(conn)
        metrics = compute_accuracy_metrics(rows)

    return metrics
