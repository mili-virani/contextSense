#!/usr/bin/env python3
"""
report.py

Queries run_logs where actual_outcome IS NOT NULL and prints accuracy statistics,
including overall directional accuracy, accuracy by confidence bucket, and
a comparison between approved-only vs all (approved + rejected) predictions.
"""

import sys
import os
import asyncio
from pathlib import Path

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


async def fetch_graded_logs(conn):
    """
    Fetch all run log entries where actual_outcome has been populated.
    """
    query = """
        SELECT id, ticker, timestamp, direction, confidence, approved, horizon_days, actual_outcome
        FROM run_logs
        WHERE actual_outcome IS NOT NULL
        ORDER BY timestamp DESC
    """
    return await conn.fetch(query)


def get_accuracy_metrics(rows):
    """
    Helper to calculate accuracy metrics from a set of rows.
    """
    correct = 0
    total = len(rows)
    for r in rows:
        if r['direction'] == r['actual_outcome']:
            correct += 1
    return correct, total


def format_metric(correct, total):
    """
    Format correct/total into a readable percentage.
    """
    if total == 0:
        return "N/A (0)"
    pct = (correct / total) * 100
    return f"{pct:6.2f}% ({correct}/{total})"


def get_bucket_rows(rows, low, high=None):
    """
    Filter rows by confidence bucket.
    """
    filtered = []
    for r in rows:
        conf = r['confidence']
        if high is not None:
            if low <= conf < high:
                filtered.append(r)
        else:
            if conf >= low:
                filtered.append(r)
    return filtered


def compute_accuracy_metrics(rows):
    """
    Compute accuracy metrics from a set of run log rows.
    """
    if not rows:
        return {
            "total_predictions": 0,
            "approved_predictions": 0,
            "rejected_predictions": 0,
            "overall_accuracy": {
                "all": {"correct": 0, "total": 0},
                "approved": {"correct": 0, "total": 0},
                "rejected": {"correct": 0, "total": 0},
            },
            "buckets_all": [],
            "buckets_approved": [],
            "diff": 0.0,
            "analysis_notes": []
        }

    # Subsets
    approved_rows = [r for r in rows if r['approved'] is True]
    rejected_rows = [r for r in rows if r['approved'] is False]

    # Overall metrics
    all_correct, all_total = get_accuracy_metrics(rows)
    app_correct, app_total = get_accuracy_metrics(approved_rows)
    rej_correct, rej_total = get_accuracy_metrics(rejected_rows)

    # Buckets for all predictions
    b1_c, b1_t = get_accuracy_metrics(get_bucket_rows(rows, 0.0, 0.5))
    b2_c, b2_t = get_accuracy_metrics(get_bucket_rows(rows, 0.5, 0.7))
    b3_c, b3_t = get_accuracy_metrics(get_bucket_rows(rows, 0.7, 0.9))
    b4_c, b4_t = get_accuracy_metrics(get_bucket_rows(rows, 0.9, 1.01))

    # Buckets for approved predictions
    ab1_c, ab1_t = get_accuracy_metrics(get_bucket_rows(approved_rows, 0.0, 0.5))
    ab2_c, ab2_t = get_accuracy_metrics(get_bucket_rows(approved_rows, 0.5, 0.7))
    ab3_c, ab3_t = get_accuracy_metrics(get_bucket_rows(approved_rows, 0.7, 0.9))
    ab4_c, ab4_t = get_accuracy_metrics(get_bucket_rows(approved_rows, 0.9, 1.01))

    diff = 0.0
    analysis_notes = []
    if app_total > 0 and rej_total > 0:
        app_acc = app_correct / app_total
        rej_acc = rej_correct / rej_total
        diff = app_acc - rej_acc
        if diff > 0.05:
            analysis_notes.append({
                "type": "positive",
                "message": f"Critic approval correlates with higher accuracy (+{diff*100:.1f}% improvement). The Critic agent is effectively filtering out lower-quality predictions."
            })
        elif diff < -0.05:
            analysis_notes.append({
                "type": "negative",
                "message": f"WARNING: Approved predictions performed WORSE than rejected ones ({app_acc*100:.1f}% vs {rej_acc*100:.1f}%). The Critic filtering logic might be counterproductive or biased."
            })
        else:
            analysis_notes.append({
                "type": "neutral",
                "message": "Critic approval shows no significant correlation with accuracy (+/-5% difference). The Critic filtering logic may need refinement."
            })

    return {
        "total_predictions": len(rows),
        "approved_predictions": app_total,
        "rejected_predictions": rej_total,
        "overall_accuracy": {
            "all": {"correct": all_correct, "total": all_total},
            "approved": {"correct": app_correct, "total": app_total},
            "rejected": {"correct": rej_correct, "total": rej_total},
        },
        "buckets_all": [
            {"bucket": "< 50%", "correct": b1_c, "total": b1_t},
            {"bucket": "50% - 70%", "correct": b2_c, "total": b2_t},
            {"bucket": "70% - 90%", "correct": b3_c, "total": b3_t},
            {"bucket": "90%+", "correct": b4_c, "total": b4_t},
        ],
        "buckets_approved": [
            {"bucket": "< 50%", "correct": ab1_c, "total": ab1_t},
            {"bucket": "50% - 70%", "correct": ab2_c, "total": ab2_t},
            {"bucket": "70% - 90%", "correct": ab3_c, "total": ab3_t},
            {"bucket": "90%+", "correct": ab4_c, "total": ab4_t},
        ],
        "diff": diff,
        "analysis_notes": analysis_notes
    }


def print_report(rows):
    """
    Generate and print the accuracy report in a clean terminal interface.
    """
    if not rows:
        print("============================================================")
        print("           CONTEXTSENSE BACKTEST ACCURACY REPORT            ")
        print("============================================================")
        print("\nNo graded predictions found in the database.")
        print("Please run `python backtest/fill_outcomes.py` first to populate outcomes.")
        print("============================================================")
        return

    metrics = compute_accuracy_metrics(rows)

    print("============================================================")
    print("           CONTEXTSENSE BACKTEST ACCURACY REPORT            ")
    print("============================================================")
    print(f"Total Graded Predictions: {metrics['total_predictions']}")
    print(f"Approved by Critic:       {metrics['approved_predictions']}")
    print(f"Rejected by Critic:       {metrics['rejected_predictions']}")
    print("------------------------------------------------------------")
    print("OVERALL DIRECTIONAL ACCURACY")
    print("------------------------------------------------------------")
    print(f"All Predictions:       {format_metric(metrics['overall_accuracy']['all']['correct'], metrics['overall_accuracy']['all']['total'])}")
    print(f"Approved Predictions:  {format_metric(metrics['overall_accuracy']['approved']['correct'], metrics['overall_accuracy']['approved']['total'])}")
    print(f"Rejected Predictions:  {format_metric(metrics['overall_accuracy']['rejected']['correct'], metrics['overall_accuracy']['rejected']['total'])}")
    print("------------------------------------------------------------")
    print("ACCURACY BY CONFIDENCE BUCKET (ALL PREDICTIONS)")
    print("------------------------------------------------------------")
    print(f"  < 50% Confidence:    {format_metric(metrics['buckets_all'][0]['correct'], metrics['buckets_all'][0]['total'])}")
    print(f"  50% - 70% Confidence:{format_metric(metrics['buckets_all'][1]['correct'], metrics['buckets_all'][1]['total'])}")
    print(f"  70% - 90% Confidence:{format_metric(metrics['buckets_all'][2]['correct'], metrics['buckets_all'][2]['total'])}")
    print(f"  90%+ Confidence:     {format_metric(metrics['buckets_all'][3]['correct'], metrics['buckets_all'][3]['total'])}")
    print("------------------------------------------------------------")
    print("ACCURACY BY CONFIDENCE BUCKET (APPROVED-ONLY PREDICTIONS)")
    print("------------------------------------------------------------")
    print(f"  < 50% Confidence:    {format_metric(metrics['buckets_approved'][0]['correct'], metrics['buckets_approved'][0]['total'])}")
    print(f"  50% - 70% Confidence:{format_metric(metrics['buckets_approved'][1]['correct'], metrics['buckets_approved'][1]['total'])}")
    print(f"  70% - 90% Confidence:{format_metric(metrics['buckets_approved'][2]['correct'], metrics['buckets_approved'][2]['total'])}")
    print(f"  90%+ Confidence:     {format_metric(metrics['buckets_approved'][3]['correct'], metrics['buckets_approved'][3]['total'])}")
    print("============================================================")
    
    if metrics['analysis_notes']:
        print("ANALYSIS SUMMARY:")
        for note in metrics['analysis_notes']:
            if note['type'] == 'positive':
                print(f"  * {note['message']}")
                print("    The Critic agent is effectively filtering out lower-quality predictions.")
            elif note['type'] == 'negative':
                print(f"  * {note['message']}")
                print("    The Critic filtering logic might be counterproductive or biased.")
            else:
                print(f"  * {note['message']}")
                print("    The Critic filtering logic may need refinement.")
        print("============================================================")


async def main_async():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("Error: DATABASE_URL environment variable is not set.")
        sys.exit(1)

    conn = await asyncpg.connect(
        database_url,
        statement_cache_size=0,
    )
    try:
        rows = await fetch_graded_logs(conn)
        print_report(rows)
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
