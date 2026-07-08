"""
Backtesting and Evaluation Module

This module provides tools to grade predictions and report directional accuracy.

Design Architecture: Forward-testing
-------------------------------------
This module implements a forward-testing approach (where predictions are graded
individually once their forecast horizon naturally passes in real-time) rather than
a historical backtest.

Limitation & Justification:
---------------------------
Bulk historical news ingestion is not feasible on this project because bulk historical
news endpoints are not available on the free tier of the Alpha Vantage API. To work around
this limitation:
1. Predictions are generated in real-time or from cached ingest data and stored in `run_logs`.
2. Once the target forecast horizon passes (i.e. `timestamp + horizon_days <= now()`),
   the script `fill_outcomes.py` queries Alpha Vantage's historical daily price endpoint
   to determine the actual price movement direction.
3. The script `report.py` calculates accuracy metrics across all processed outcomes.
"""
