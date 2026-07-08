"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { 
  ArrowUpRight, 
  ArrowDownRight, 
  Minus, 
  Search, 
  CheckCircle, 
  XCircle, 
  Calendar,
  AlertCircle,
  Play,
  RotateCw,
  Clock,
  Compass,
  Database
} from "lucide-react";

interface Event {
  event_type: string;
  description: string;
  sentiment_score: number;
  confidence: number;
  source_ids: string[];
}

interface Prediction {
  id: number;
  ticker: string;
  timestamp: string;
  direction: "up" | "down" | "neutral";
  confidence: number;
  approved: boolean;
  horizon_days: number | null;
  actual_outcome: string | null;
  reasoning_summary: string;
  critic_flags: string[];
  events?: Event[] | null;
}

export default function PredictionsDashboard() {
  const [predictions, setPredictions] = useState<Prediction[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  // Filters
  const [tickerSearch, setTickerSearch] = useState("");
  const [approvedOnly, setApprovedOnly] = useState(false);

  // New prediction pipeline run state
  const [newQuery, setNewQuery] = useState("");
  const [runningPipeline, setRunningPipeline] = useState(false);
  const [pipelineResult, setPipelineResult] = useState<{
    status: string;
    ticker: string;
    approved: boolean;
    direction: string;
    confidence: number;
  } | null>(null);
  const [pipelineError, setPipelineError] = useState<string | null>(null);

  // Load predictions list from API
  async function loadPredictions() {
    try {
      setLoading(true);
      setError(null);
      const res = await fetch("http://localhost:8000/predictions?limit=100");
      if (!res.ok) {
        throw new Error(`Error: ${res.statusText} (${res.status})`);
      }
      const payload = await res.json();
      setPredictions(payload.data || []);
    } catch (err: unknown) {
      console.error(err);
      setError(err instanceof Error ? err.message : "Failed to fetch predictions from backend API");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadPredictions();
  }, []);

  // Run new pipeline analysis
  async function handleRunAnalysis(e: React.FormEvent) {
    e.preventDefault();
    if (!newQuery.trim()) return;

    try {
      setRunningPipeline(true);
      setPipelineError(null);
      setPipelineResult(null);

      // Determine if input is a pure ticker symbol or general company query
      const cleanInput = newQuery.trim();
      const isTicker = /^[a-zA-Z]{1,5}$/.test(cleanInput);
      const bodyPayload = isTicker ? { ticker: cleanInput } : { query: cleanInput };

      const res = await fetch("http://localhost:8000/predictions/run", {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify(bodyPayload)
      });

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(errorData.detail || `Pipeline failed with status ${res.status}`);
      }

      const result = await res.json();
      setPipelineResult({
        status: result.status,
        ticker: result.ticker,
        approved: result.approved,
        direction: result.direction,
        confidence: result.confidence
      });
      setNewQuery("");
      
      // Reload predictions log
      await loadPredictions();
    } catch (err: unknown) {
      console.error(err);
      setPipelineError(err instanceof Error ? err.message : "Failed to execute multi-agent RAG pipeline");
    } finally {
      setRunningPipeline(false);
    }
  }

  // Filter list logic
  const filteredPredictions = predictions.filter((p) => {
    const matchesSearch = p.ticker.toLowerCase().includes(tickerSearch.toLowerCase().trim());
    const matchesApproval = !approvedOnly || p.approved;
    return matchesSearch && matchesApproval;
  });

  return (
    <div className="space-y-10 animate-in fade-in duration-500">
      
      {/* 1. Run New Prediction Section */}
      <section className="p-6 sm:p-8 rounded-2xl border border-border bg-card/30 backdrop-blur-md shadow-lg space-y-6">
        <div>
          <div className="flex items-center gap-2 text-primary font-bold text-sm tracking-wider uppercase">
            <Compass className="h-4 w-4 animate-spin-slow text-violet-400" />
            Agent Analysis Engine
          </div>
          <h2 className="text-2xl font-black tracking-tight mt-1">Run New Stock Analysis</h2>
          <p className="text-muted-foreground text-sm mt-1 max-w-2xl">
            Enter a ticker symbol or company name. The multi-agent RAG pipeline will query historical chunks, fetch live pricing, extract news events, forecast price direction, and verify citations via the Critic.
          </p>
        </div>

        <form onSubmit={handleRunAnalysis} className="flex flex-col sm:flex-row gap-3">
          <div className="relative flex-1">
            <Search className="absolute left-3.5 top-3 h-5 w-5 text-muted-foreground" />
            <input
              type="text"
              required
              placeholder="Enter stock ticker or company name, e.g. AAPL, Tesla, Nvidia..."
              value={newQuery}
              onChange={(e) => setNewQuery(e.target.value)}
              disabled={runningPipeline}
              className="w-full pl-11 pr-4 py-3 text-sm bg-background border border-border rounded-xl focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent transition-all placeholder:text-muted-foreground text-foreground"
            />
          </div>
          
          <button
            type="submit"
            disabled={runningPipeline}
            className="sm:w-44 inline-flex items-center justify-center gap-2 px-6 py-3 text-sm font-bold rounded-xl bg-primary text-primary-foreground hover:bg-primary/95 transition-all shadow-md shadow-primary/20 hover:scale-[1.01] active:scale-[0.99] disabled:opacity-50 disabled:pointer-events-none"
          >
            {runningPipeline ? (
              <>
                <RotateCw className="h-4 w-4 animate-spin" />
                Analyzing...
              </>
            ) : (
              <>
                <Play className="h-4 w-4 fill-current" />
                Run Analysis
              </>
            )}
          </button>
        </form>

        {/* Loading notification state */}
        {runningPipeline && (
          <div className="p-4 rounded-xl border border-primary/20 bg-primary/5 flex items-center gap-3 animate-pulse">
            <RotateCw className="h-5 w-5 text-primary animate-spin" />
            <span className="text-sm font-semibold text-primary">
              Running multi-agent pipeline: Orchestrator, Qdrant Retriever, event Analyst, Predictor, and Critic...
            </span>
          </div>
        )}

        {/* Pipeline run success state */}
        {pipelineResult && (
          <div className="p-5 border border-emerald-500/20 rounded-xl bg-emerald-500/5 space-y-2 animate-in slide-in-from-top-2 duration-300">
            <div className="flex items-center gap-2 text-emerald-400 font-bold text-sm">
              <CheckCircle className="h-5 w-5" />
              Pipeline Run Successful
            </div>
            <p className="text-sm text-muted-foreground leading-relaxed">
              Successfully generated analysis for <span className="font-bold text-foreground font-mono">{pipelineResult.ticker}</span>. 
              Forecast: <span className="font-bold text-foreground capitalize">{pipelineResult.direction}</span> with{" "}
              <span className="font-bold text-violet-400 font-mono">{(pipelineResult.confidence * 100).toFixed(0)}%</span> confidence. 
              Critic Verdict:{" "}
              <span className={`font-bold ${pipelineResult.approved ? "text-emerald-400" : "text-rose-400"}`}>
                {pipelineResult.approved ? "Approved" : "Rejected"}
              </span>.
            </p>
            <div className="pt-2">
              <Link 
                href={`/ticker/${pipelineResult.ticker}`}
                className="inline-flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-lg bg-secondary text-secondary-foreground hover:bg-muted text-xs font-bold transition-all border border-border"
              >
                View Full Analysis Report
              </Link>
            </div>
          </div>
        )}

        {/* Pipeline run error state */}
        {pipelineError && (
          <div className="p-5 border border-rose-500/20 rounded-xl bg-rose-500/5 space-y-1 text-rose-400">
            <div className="flex items-center gap-2 font-bold text-sm">
              <AlertCircle className="h-5 w-5 text-rose-400" />
              Pipeline Execution Error
            </div>
            <p className="text-sm opacity-90">{pipelineError}</p>
          </div>
        )}
      </section>

      {/* 2. Historical Logs & Filters Grid */}
      <section className="space-y-6">
        
        {/* Section title & count */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-border/80 pb-4">
          <div>
            <h2 className="text-2xl font-bold tracking-tight">Predictions Log History</h2>
            <p className="text-muted-foreground text-xs mt-1">Showing historical runs logged in Postgres.</p>
          </div>
          
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-card border border-border rounded-lg text-xs font-semibold">
              <Database className="h-3.5 w-3.5 text-muted-foreground" />
              Logged: {predictions.length}
            </span>
          </div>
        </div>

        {/* Filters control bar */}
        <div className="flex flex-col sm:flex-row gap-3">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-2.5 h-4.5 w-4.5 text-muted-foreground" />
            <input
              type="text"
              placeholder="Filter list by ticker (e.g. AAPL)..."
              value={tickerSearch}
              onChange={(e) => setTickerSearch(e.target.value)}
              className="w-full pl-10 pr-4 py-2 text-sm bg-card border border-border rounded-lg focus:outline-none focus:ring-1 focus:ring-primary focus:border-transparent transition-all placeholder:text-muted-foreground text-foreground"
            />
          </div>
          
          <button
            onClick={() => setApprovedOnly(!approvedOnly)}
            className={`flex items-center justify-center gap-2 px-4 py-2 text-sm font-semibold border rounded-lg transition-all ${
              approvedOnly 
                ? "bg-primary border-primary text-primary-foreground hover:bg-primary/95" 
                : "bg-card border-border text-foreground hover:bg-muted/50"
            }`}
          >
            <CheckCircle className="h-4 w-4" />
            Approved Only
          </button>
        </div>

        {/* Predictions grid list */}
        {loading ? (
          <div className="flex flex-col items-center justify-center py-20 space-y-4">
            <div className="h-10 w-10 border-4 border-primary border-t-transparent rounded-full animate-spin" />
            <p className="text-muted-foreground text-sm font-medium animate-pulse">Loading predictions from database...</p>
          </div>
        ) : error ? (
          <div className="p-6 border border-destructive/20 rounded-xl bg-destructive/10 text-destructive flex items-start gap-4">
            <AlertCircle className="h-6 w-6 shrink-0 mt-0.5" />
            <div>
              <h3 className="font-bold text-lg">Connection Failure</h3>
              <p className="text-sm mt-1 opacity-90">{error}</p>
            </div>
          </div>
        ) : filteredPredictions.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-center border border-dashed border-border rounded-2xl bg-card/10">
            <AlertCircle className="h-12 w-12 text-muted-foreground mb-3" />
            <h3 className="text-lg font-bold">No Records Found</h3>
            <p className="text-muted-foreground text-sm max-w-sm mt-1">
              No logged predictions match your filters. Run an analysis above or adjust your search.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {filteredPredictions.map((p) => {
              const formattedDate = new Date(p.timestamp).toLocaleString(undefined, {
                dateStyle: "medium",
                timeStyle: "short",
              });
              
              const isUp = p.direction === "up";
              const isDown = p.direction === "down";
              const eventCount = p.events ? p.events.length : 0;
              
              // Short reasoning text preview
              const reasoningPreview = p.reasoning_summary 
                ? p.reasoning_summary.slice(0, 140) + (p.reasoning_summary.length > 140 ? "..." : "")
                : "Reasoning trace unavailable (logged before this field was tracked)";
              
              return (
                <div 
                  key={p.id}
                  className="group relative flex flex-col justify-between overflow-hidden rounded-xl border border-border bg-card hover:border-primary/50 hover:shadow-lg hover:shadow-primary/5 transition-all duration-300"
                >
                  <div className="p-5 space-y-4">
                    {/* Header line: Ticker and Approved badge */}
                    <div className="flex items-center justify-between">
                      <span className="text-2xl font-black tracking-tight group-hover:text-primary transition-colors font-mono">
                        {p.ticker}
                      </span>
                      
                      {p.approved ? (
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                          <CheckCircle className="h-3 w-3" />
                          Approved
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/20">
                          <XCircle className="h-3 w-3" />
                          Rejected
                        </span>
                      )}
                    </div>

                    {/* Event count badge */}
                    <div className="flex flex-wrap gap-2">
                      <span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold tracking-wide uppercase ${
                        eventCount > 0 
                          ? "bg-violet-500/10 text-violet-400 border border-violet-500/20"
                          : "bg-amber-500/10 text-amber-400 border border-amber-500/20"
                      }`}>
                        {eventCount === 1 
                          ? "1 event cited" 
                          : eventCount > 1 
                            ? `${eventCount} events cited` 
                            : "0 events - low evidence"}
                      </span>
                    </div>

                    {/* Direction, Confidence and Horizon statistics row */}
                    <div className="grid grid-cols-2 gap-3 p-3 bg-secondary/35 border border-border/40 rounded-xl">
                      <div>
                        <span className="text-[10px] text-muted-foreground block uppercase font-bold tracking-wider">Direction</span>
                        <div className="flex items-center gap-1 mt-0.5 font-extrabold text-sm">
                          {isUp ? (
                            <>
                              <ArrowUpRight className="h-4.5 w-4.5 text-emerald-400" />
                              <span className="text-emerald-400 capitalize">{p.direction}</span>
                            </>
                          ) : isDown ? (
                            <>
                              <ArrowDownRight className="h-4.5 w-4.5 text-rose-400" />
                              <span className="text-rose-400 capitalize">{p.direction}</span>
                            </>
                          ) : (
                            <>
                              <Minus className="h-4.5 w-4.5 text-muted-foreground" />
                              <span className="text-muted-foreground capitalize">{p.direction}</span>
                            </>
                          )}
                        </div>
                      </div>

                      <div>
                        <span className="text-[10px] text-muted-foreground block uppercase font-bold tracking-wider">Confidence</span>
                        <div className="flex items-center gap-2 mt-0.5">
                          <span className="text-sm font-extrabold font-mono text-violet-400 block">
                            {(p.confidence * 100).toFixed(0)}%
                          </span>
                          <div className="w-12 h-1.5 bg-secondary rounded-full overflow-hidden shrink-0">
                            <div 
                              className={`h-full ${
                                p.confidence * 100 < 40 
                                  ? "bg-rose-500" 
                                  : p.confidence * 100 <= 70 
                                    ? "bg-amber-500" 
                                    : "bg-emerald-500"
                              }`} 
                              style={{ width: `${p.confidence * 100}%` }}
                            />
                          </div>
                        </div>
                      </div>
                    </div>

                    {/* Reasoning preview */}
                    <div className="text-xs text-muted-foreground/95 leading-relaxed italic bg-muted/10 p-3 rounded-lg border border-border/30">
                      {reasoningPreview}
                    </div>

                    {/* Metadata line */}
                    <div className="space-y-1.5 text-[11px] text-muted-foreground pt-1 border-t border-border/40">
                      {p.horizon_days && (
                        <div className="flex items-center gap-1">
                          <Clock className="h-3.5 w-3.5 text-muted-foreground/85" />
                          <span>Horizon: <span className="font-semibold text-foreground font-mono">{p.horizon_days} Days</span></span>
                        </div>
                      )}
                      <div className="flex items-center gap-1">
                        <Calendar className="h-3.5 w-3.5 text-muted-foreground/85" />
                        <span>Timestamp: <span className="font-semibold text-foreground font-mono">{formattedDate}</span></span>
                      </div>
                    </div>
                  </div>

                  {/* Details Navigation Link button */}
                  <div className="border-t border-border bg-card/60 p-4">
                    <Link 
                      href={`/ticker/${p.ticker}`}
                      className="w-full inline-flex items-center justify-center gap-2 px-4 py-2 text-xs font-bold rounded-lg bg-secondary text-secondary-foreground hover:bg-primary hover:text-primary-foreground transition-all duration-200"
                    >
                      View Full Analysis Detail
                    </Link>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
