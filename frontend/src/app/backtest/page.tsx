"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { 
  ArrowLeft,
  Activity, 
  CheckSquare, 
  XSquare, 
  AlertCircle,
  Award,
  TrendingUp
} from "lucide-react";

interface AccuracyMetric {
  correct: number;
  total: number;
}

interface BucketMetric {
  bucket: string;
  correct: number;
  total: number;
}

interface AnalysisNote {
  type: "positive" | "negative" | "neutral";
  message: string;
}

interface BacktestSummary {
  total_predictions: number;
  approved_predictions: number;
  rejected_predictions: number;
  overall_accuracy: {
    all: AccuracyMetric;
    approved: AccuracyMetric;
    rejected: AccuracyMetric;
  };
  buckets_all: BucketMetric[];
  buckets_approved: BucketMetric[];
  diff: number;
  analysis_notes: AnalysisNote[];
}

export default function BacktestPage() {
  const [summary, setSummary] = useState<BacktestSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadSummary() {
      try {
        setLoading(true);
        setError(null);
        const res = await fetch("http://localhost:8000/backtest/summary");
        if (!res.ok) {
          throw new Error(`Error: Failed to fetch backtest summary (${res.status})`);
        }
        const data = await res.json();
        setSummary(data);
      } catch (err: unknown) {
        console.error(err);
        setError(err instanceof Error ? err.message : "Failed to load backtest metrics");
      } finally {
        setLoading(false);
      }
    }
    loadSummary();
  }, []);

  const formatPercentage = (metric: AccuracyMetric) => {
    if (metric.total === 0) return "N/A";
    const pct = (metric.correct / metric.total) * 100;
    return `${pct.toFixed(1)}%`;
  };

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      
      {/* Header Section */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-border/80 pb-4">
        <div>
          <h1 className="text-3xl font-extrabold tracking-tight bg-clip-text text-transparent bg-gradient-to-r from-foreground to-muted-foreground">
            Backtest Accuracy Report
          </h1>
          <p className="text-muted-foreground mt-1 text-sm">
            Compare forecast direction results with actual market outcomes to evaluate pipeline performance.
          </p>
        </div>
        
        <Link 
          href="/" 
          className="inline-flex items-center justify-center gap-2 px-4 py-2 text-sm font-semibold rounded-lg bg-secondary text-secondary-foreground hover:bg-card border border-border transition-colors shrink-0"
        >
          <ArrowLeft className="h-4 w-4" />
          Dashboard
        </Link>
      </div>

      {loading ? (
        <div className="flex flex-col items-center justify-center py-24 space-y-4">
          <div className="h-10 w-10 border-4 border-primary border-t-transparent rounded-full animate-spin" />
          <p className="text-muted-foreground text-sm font-medium animate-pulse">Running backtest summary computations...</p>
        </div>
      ) : error ? (
        <div className="p-6 border border-destructive/20 rounded-xl bg-destructive/10 text-destructive flex items-start gap-4">
          <AlertCircle className="h-6 w-6 shrink-0 mt-0.5" />
          <div>
            <h3 className="font-bold text-lg">Connection Failure</h3>
            <p className="text-sm mt-1 opacity-90">{error}</p>
            <p className="text-xs mt-3 opacity-75">
              Make sure the FastAPI backend is running at <code className="bg-black/20 dark:bg-white/10 px-1 py-0.5 rounded font-mono">http://localhost:8000</code>
            </p>
          </div>
        </div>
      ) : summary ? (
        <div className="space-y-8">
          
          {/* Summary Cards Grid */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="p-5 rounded-2xl border border-border bg-card/45 flex items-center gap-4 shadow-sm">
              <div className="h-11 w-11 rounded-xl bg-violet-500/10 text-violet-400 flex items-center justify-center border border-violet-500/20">
                <Activity className="h-5 w-5" />
              </div>
              <div>
                <span className="text-[10px] text-muted-foreground font-bold uppercase tracking-wider block">Graded Predictions</span>
                <span className="text-2xl font-black font-mono mt-0.5 block">{summary.total_predictions}</span>
              </div>
            </div>

            <div className="p-5 rounded-2xl border border-border bg-card/45 flex items-center gap-4 shadow-sm">
              <div className="h-11 w-11 rounded-xl bg-emerald-500/10 text-emerald-400 flex items-center justify-center border border-emerald-500/20">
                <CheckSquare className="h-5 w-5" />
              </div>
              <div>
                <span className="text-[10px] text-muted-foreground font-bold uppercase tracking-wider block">Approved by Critic</span>
                <span className="text-2xl font-black font-mono mt-0.5 block">{summary.approved_predictions}</span>
              </div>
            </div>

            <div className="p-5 rounded-2xl border border-border bg-card/45 flex items-center gap-4 shadow-sm">
              <div className="h-11 w-11 rounded-xl bg-rose-500/10 text-rose-400 flex items-center justify-center border border-rose-500/20">
                <XSquare className="h-5 w-5" />
              </div>
              <div>
                <span className="text-[10px] text-muted-foreground font-bold uppercase tracking-wider block">Rejected by Critic</span>
                <span className="text-2xl font-black font-mono mt-0.5 block">{summary.rejected_predictions}</span>
              </div>
            </div>
          </div>

          {/* Analysis Note from Critic Impact */}
          {summary.analysis_notes.length > 0 && (
            <div className="p-5 rounded-xl border border-primary/20 bg-primary/5 space-y-2">
              <div className="flex items-center gap-2 font-bold text-primary text-sm">
                <Award className="h-4.5 w-4.5" />
                Critic Impact Analysis
              </div>
              <div className="space-y-1.5">
                {summary.analysis_notes.map((note, idx) => (
                  <p key={idx} className="text-xs leading-relaxed text-foreground/90 font-medium font-sans">
                    {note.message}
                  </p>
                ))}
              </div>
            </div>
          )}

          {summary.total_predictions === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 text-center border border-dashed border-border rounded-2xl bg-card/10 space-y-4 p-6">
              <AlertCircle className="h-12 w-12 text-muted-foreground" />
              <h3 className="text-lg font-bold">No Graded Backtest Outcomes Available</h3>
              <p className="text-muted-foreground text-sm max-w-lg mt-1 font-sans">
                No predictions have passed their horizon window yet. Backtest results will appear after predictions have <code className="text-xs bg-muted px-1.5 py-0.5 rounded font-mono font-semibold text-foreground">actual_outcome</code> populated.
              </p>
              
              <div className="pt-2 max-w-md w-full">
                <span className="text-[10px] text-muted-foreground font-bold uppercase tracking-wider block mb-2">Run this in backend to pull outcomes:</span>
                <div className="bg-card text-xs font-mono border border-border rounded-xl p-3 flex items-center justify-between shadow-inner">
                  <span>python backtest/fill_outcomes.py</span>
                  <span className="px-2 py-0.5 rounded bg-secondary text-[10px] border border-border text-muted-foreground font-sans font-bold uppercase select-none">
                    CLI Script
                  </span>
                </div>
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
              
              {/* Overall Accuracy Table */}
              <div className="p-6 rounded-2xl border border-border bg-card/25 shadow-sm space-y-4">
                <div className="flex items-center gap-2 border-b border-border/50 pb-3">
                  <TrendingUp className="h-5 w-5 text-violet-400" />
                  <h2 className="font-bold text-base">Overall Directional Accuracy</h2>
                </div>
                
                <div className="overflow-hidden border border-border rounded-xl">
                  <table className="w-full text-left border-collapse text-xs">
                    <thead>
                      <tr className="bg-muted/40 font-semibold border-b border-border text-muted-foreground uppercase tracking-wider">
                        <th className="p-3">Prediction Set</th>
                        <th className="p-3 text-right">Correct / Total</th>
                        <th className="p-3 text-right">Accuracy Rate</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border font-mono">
                      <tr className="hover:bg-muted/15 transition-colors">
                        <td className="p-3 font-medium text-foreground font-sans">All Predictions</td>
                        <td className="p-3 text-right">{summary.overall_accuracy.all.correct} / {summary.overall_accuracy.all.total}</td>
                        <td className="p-3 text-right text-violet-400 font-bold">{formatPercentage(summary.overall_accuracy.all)}</td>
                      </tr>
                      <tr className="hover:bg-muted/15 transition-colors">
                        <td className="p-3 font-medium text-foreground font-sans">Approved Predictions</td>
                        <td className="p-3 text-right">{summary.overall_accuracy.approved.correct} / {summary.overall_accuracy.approved.total}</td>
                        <td className="p-3 text-right text-emerald-400 font-bold">{formatPercentage(summary.overall_accuracy.approved)}</td>
                      </tr>
                      <tr className="hover:bg-muted/15 transition-colors">
                        <td className="p-3 font-medium text-foreground font-sans">Rejected Predictions</td>
                        <td className="p-3 text-right">{summary.overall_accuracy.rejected.correct} / {summary.overall_accuracy.rejected.total}</td>
                        <td className="p-3 text-right text-rose-400 font-bold">{formatPercentage(summary.overall_accuracy.rejected)}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Confidence Buckets Grid */}
              <div className="space-y-8">
                
                {/* Buckets (All) */}
                <div className="p-6 rounded-2xl border border-border bg-card/25 shadow-sm space-y-4">
                  <div className="flex items-center gap-2 border-b border-border/50 pb-3">
                    <TrendingUp className="h-5 w-5 text-violet-400" />
                    <h2 className="font-bold text-base">Accuracy by Confidence (All)</h2>
                  </div>
                  
                  <div className="overflow-hidden border border-border rounded-xl">
                    <table className="w-full text-left border-collapse text-xs">
                      <thead>
                        <tr className="bg-muted/40 font-semibold border-b border-border text-muted-foreground uppercase tracking-wider">
                          <th className="p-3">Bucket</th>
                          <th className="p-3 text-right">Count</th>
                          <th className="p-3 text-right">Accuracy</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-border font-mono">
                        {summary.buckets_all.map((b) => (
                          <tr key={b.bucket} className="hover:bg-muted/15 transition-colors">
                            <td className="p-3 font-medium text-foreground font-sans">{b.bucket}</td>
                            <td className="p-3 text-right">{b.correct} / {b.total}</td>
                            <td className="p-3 text-right font-bold text-violet-400">{formatPercentage(b)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Buckets (Approved) */}
                <div className="p-6 rounded-2xl border border-border bg-card/25 shadow-sm space-y-4">
                  <div className="flex items-center gap-2 border-b border-border/50 pb-3">
                    <TrendingUp className="h-5 w-5 text-emerald-400" />
                    <h2 className="font-bold text-base">Accuracy by Confidence (Approved-Only)</h2>
                  </div>
                  
                  <div className="overflow-hidden border border-border rounded-xl">
                    <table className="w-full text-left border-collapse text-xs">
                      <thead>
                        <tr className="bg-muted/40 font-semibold border-b border-border text-muted-foreground uppercase tracking-wider">
                          <th className="p-3">Bucket</th>
                          <th className="p-3 text-right">Count</th>
                          <th className="p-3 text-right">Accuracy</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-border font-mono">
                        {summary.buckets_approved.map((b) => (
                          <tr key={b.bucket} className="hover:bg-muted/15 transition-colors">
                            <td className="p-3 font-medium text-foreground font-sans">{b.bucket}</td>
                            <td className="p-3 text-right">{b.correct} / {b.total}</td>
                            <td className="p-3 text-right font-bold text-emerald-400">{formatPercentage(b)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

              </div>

            </div>
          )}

        </div>
      ) : null}
    </div>
  );
}
