"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { 
  ArrowLeft, 
  ArrowUpRight, 
  ArrowDownRight, 
  Minus, 
  CheckCircle, 
  XCircle, 
  Calendar,
  AlertTriangle,
  FileText,
  Bookmark,
  Activity,
  Layers,
  ShieldCheck
} from "lucide-react";

interface Event {
  event_type: string;
  description: string;
  sentiment_score: number;
  confidence: number;
  source_ids: string[];
}

interface TechnicalFeatures {
  momentum?: number;
  rsi?: number;
  volume_change?: number;
  ma_cross?: string;
}

interface Chunk {
  id: string;
  text: string;
  source: string;
  date: string;
}

interface PredictionDetail {
  id: number;
  ticker: string;
  timestamp: string;
  direction: "up" | "down" | "neutral";
  confidence: number;
  approved: boolean;
  horizon_days: number | null;
  cited_event_ids: string[];
  actual_outcome: string | null;
  reasoning_summary: string;
  critic_flags: string[];
  technical_features?: TechnicalFeatures | null;
  events?: Event[] | null;
  chunks?: Chunk[] | null;
}

interface ReasoningStep {
  number: string;
  title: string;
  content: string;
}

function parseReasoningSummary(text: string): ReasoningStep[] | null {
  if (!text) return null;

  const regex = /(\d+)\.\s+([A-Z][A-Z\s-]{3,}):/g;
  const matches = Array.from(text.matchAll(regex));

  if (matches.length === 0) return null;

  const steps: ReasoningStep[] = [];
  
  for (let i = 0; i < matches.length; i++) {
    const currentMatch = matches[i];
    const nextMatch = matches[i + 1];
    
    const startIndex = currentMatch.index! + currentMatch[0].length;
    const endIndex = nextMatch ? nextMatch.index! : text.length;
    
    const stepNum = currentMatch[1];
    const rawTitle = currentMatch[2];
    
    const formattedTitle = rawTitle
      .toLowerCase()
      .split(" ")
      .map(word => {
        return word
          .split("-")
          .map((subWord, idx) => {
            if (idx > 0 && ["by", "and", "of", "to", "for", "in", "or"].includes(subWord)) {
              return subWord;
            }
            return subWord.charAt(0).toUpperCase() + subWord.slice(1);
          })
          .join("-");
      })
      .join(" ");

    const content = text.slice(startIndex, endIndex).trim();
    
    steps.push({
      number: stepNum,
      title: formattedTitle,
      content: content
    });
  }

  return steps.length > 0 ? steps : null;
}

export default function TickerDetailPage({ params }: { params: { symbol: string } }) {
  const symbol = params.symbol.toUpperCase();
  const [detail, setDetail] = useState<PredictionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadDetail() {
      try {
        setLoading(true);
        setError(null);
        const res = await fetch(`http://localhost:8000/predictions/${symbol}`);
        if (res.status === 404) {
          throw new Error(`No prediction records found for ticker "${symbol}"`);
        }
        if (!res.ok) {
          throw new Error(`Error: Failed to fetch detail (${res.status})`);
        }
        const data = await res.json();
        setDetail(data);
      } catch (err: unknown) {
        console.error(err);
        setError(err instanceof Error ? err.message : "Failed to load prediction details");
      } finally {
        setLoading(false);
      }
    }
    loadDetail();
  }, [symbol]);

  // Helper to format sentiment scores nicely
  const renderSentiment = (score: number) => {
    if (score > 0.1) return <span className="text-emerald-400 font-semibold font-mono">Positive (+{score.toFixed(2)})</span>;
    if (score < -0.1) return <span className="text-rose-400 font-semibold font-mono">Negative ({score.toFixed(2)})</span>;
    return <span className="text-muted-foreground font-semibold font-mono">Neutral ({score.toFixed(2)})</span>;
  };

  return (
    <div className="max-w-6xl mx-auto space-y-8 animate-in fade-in duration-500">
      
      {/* 1. Header & Navigation */}
      <div className="flex items-center justify-between border-b border-border/80 pb-4">
        <Link 
          href="/" 
          className="inline-flex items-center gap-2 text-sm font-semibold text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Predictions Log
        </Link>
        <span className="text-xs text-muted-foreground font-semibold font-mono bg-card border border-border px-3 py-1 rounded-lg">
          Run ID: #{detail?.id || "N/A"}
        </span>
      </div>

      {loading ? (
        <div className="flex flex-col items-center justify-center py-24 space-y-4">
          <div className="h-10 w-10 border-4 border-primary border-t-transparent rounded-full animate-spin" />
          <p className="text-muted-foreground text-sm font-medium animate-pulse">Running detail extraction for {symbol}...</p>
        </div>
      ) : error ? (
        <div className="p-8 border border-border rounded-xl bg-card/50 text-center space-y-4">
          <AlertTriangle className="h-12 w-12 text-amber-500 mx-auto" />
          <h3 className="text-xl font-bold">Analysis Not Found</h3>
          <p className="text-muted-foreground text-sm max-w-md mx-auto">{error}</p>
          <div className="pt-2">
            <Link 
              href="/"
              className="inline-flex items-center justify-center px-4 py-2 text-sm font-semibold rounded-lg bg-primary text-primary-foreground hover:bg-primary/95 transition-colors"
            >
              Return to Dashboard
            </Link>
          </div>
        </div>
      ) : detail ? (
        <div className="space-y-8">
          
          {/* A. Ticker Header Card */}
          <div className="p-6 rounded-2xl border border-border bg-card/45 backdrop-blur-sm shadow-md">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
              <div className="space-y-2">
                <div className="flex items-center gap-3">
                  <h1 className="text-4xl font-black tracking-tight font-mono">{detail.ticker}</h1>
                  {detail.approved ? (
                    <span className="inline-flex items-center gap-1 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                      <CheckCircle className="h-3.5 w-3.5" />
                      Critic Approved
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 px-3 py-1 rounded-full text-xs font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/20">
                      <XCircle className="h-3.5 w-3.5" />
                      Critic Rejected
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-1.5 text-xs text-muted-foreground font-mono">
                  <Calendar className="h-3.5 w-3.5 text-muted-foreground/80" />
                  <span>Pipeline Execution: {new Date(detail.timestamp).toLocaleString()}</span>
                </div>
              </div>

              {/* B. Predictions Summary Row */}
              <div className="flex flex-wrap items-center gap-6 md:border-l md:border-border/80 md:pl-6 shrink-0">
                <div className="bg-secondary/20 border border-border/40 p-3 rounded-xl min-w-28 text-center sm:text-left">
                  <span className="text-[10px] text-muted-foreground uppercase tracking-wider font-bold block">Forecast</span>
                  <div className="flex items-center gap-1 mt-1 font-extrabold text-base justify-center sm:justify-start">
                    {detail.direction === "up" ? (
                      <>
                        <ArrowUpRight className="h-5 w-5 text-emerald-400" />
                        <span className="text-emerald-400 capitalize">{detail.direction}</span>
                      </>
                    ) : detail.direction === "down" ? (
                      <>
                        <ArrowDownRight className="h-5 w-5 text-rose-400" />
                        <span className="text-rose-400 capitalize">{detail.direction}</span>
                      </>
                    ) : (
                      <>
                        <Minus className="h-5 w-5 text-muted-foreground" />
                        <span className="text-muted-foreground capitalize">{detail.direction}</span>
                      </>
                    )}
                  </div>
                </div>

                <div className="bg-secondary/20 border border-border/40 p-3 rounded-xl min-w-28 text-center sm:text-left">
                  <span className="text-[10px] text-muted-foreground uppercase tracking-wider font-bold block">Confidence</span>
                  <div className="flex items-center justify-center sm:justify-start gap-2 mt-1">
                    <span className="text-xl font-black font-mono text-violet-400 block">
                      {(detail.confidence * 100).toFixed(0)}%
                    </span>
                    <div className="w-12 h-1.5 bg-secondary rounded-full overflow-hidden shrink-0">
                      <div 
                        className={`h-full ${
                          detail.confidence * 100 < 40 
                            ? "bg-rose-500" 
                            : detail.confidence * 100 <= 70 
                              ? "bg-amber-500" 
                              : "bg-emerald-500"
                        }`} 
                        style={{ width: `${detail.confidence * 100}%` }}
                      />
                    </div>
                  </div>
                </div>

                {detail.horizon_days && (
                  <div className="bg-secondary/20 border border-border/40 p-3 rounded-xl min-w-28 text-center sm:text-left">
                    <span className="text-[10px] text-muted-foreground uppercase tracking-wider font-bold block">Horizon</span>
                    <span className="text-xl font-black font-mono block mt-0.5">{detail.horizon_days} Days</span>
                  </div>
                )}
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
            
            {/* Left column: Reasoning & Events (Spans 2 columns on large screens) */}
            <div className="lg:col-span-2 space-y-8">
              
              {/* C. Reasoning Summary Card */}
              <div className="p-6 rounded-2xl border border-border bg-card/25 shadow-sm space-y-4">
                <div className="flex items-center gap-2 border-b border-border/50 pb-3">
                  <FileText className="h-5 w-5 text-violet-400" />
                  <h2 className="font-bold text-lg">Reasoning Trace & Chain of Thought</h2>
                </div>
                
                <div className="text-sm leading-relaxed text-foreground/90 whitespace-pre-wrap font-sans space-y-4">
                  {(() => {
                    if (!detail.reasoning_summary) {
                      return "Reasoning trace unavailable (logged before this field was tracked)";
                    }
                    const parsedSteps = parseReasoningSummary(detail.reasoning_summary);
                    if (!parsedSteps) {
                      return detail.reasoning_summary;
                    }
                    return (
                      <div className="space-y-4 font-sans">
                        {parsedSteps.map((step) => (
                          <div key={step.number} className="space-y-1.5">
                            <h3 className="text-xs font-bold uppercase tracking-wider text-violet-400 font-mono">
                              Step {step.number}: {step.title}
                            </h3>
                            <p className="text-foreground/90 leading-relaxed font-sans text-xs bg-secondary/15 border border-border/40 p-3.5 rounded-xl">
                              {step.content}
                            </p>
                          </div>
                        ))}
                      </div>
                    );
                  })()}
                </div>
              </div>

              {/* D. Analyst Events Section */}
              <div className="p-6 rounded-2xl border border-border bg-card/25 shadow-sm space-y-4">
                <div className="flex items-center gap-2 border-b border-border/50 pb-3">
                  <Layers className="h-5 w-5 text-violet-400" />
                  <h2 className="font-bold text-lg">Extracted News Events & Catalysts</h2>
                </div>

                {!detail.events || detail.events.length === 0 ? (
                  <p className="text-sm text-muted-foreground italic bg-secondary/15 p-4 rounded-xl border border-border/30">
                    No structured events were stored for this prediction.
                  </p>
                ) : (
                  <div className="space-y-4">
                    {detail.events.map((evt, idx) => (
                      <div key={idx} className="p-4 border border-border/60 bg-secondary/10 rounded-xl space-y-2">
                        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/40 pb-2">
                          <span className="text-xs font-black font-mono uppercase bg-primary/10 text-primary px-2.5 py-0.5 rounded border border-primary/20">
                            {evt.event_type.replace("_", " ")}
                          </span>
                          <div className="flex items-center gap-4 text-xs">
                            <div className="flex items-center gap-1">
                              <span className="text-muted-foreground font-semibold">Confidence:</span>
                              <span className="font-bold font-mono">{(evt.confidence * 100).toFixed(0)}%</span>
                            </div>
                            <div className="flex items-center gap-1">
                              <span className="text-muted-foreground font-semibold">Sentiment:</span>
                              {renderSentiment(evt.sentiment_score)}
                            </div>
                          </div>
                        </div>
                        
                        <p className="text-sm text-foreground/90 leading-relaxed font-sans">{evt.description}</p>
                        
                        {evt.source_ids && evt.source_ids.length > 0 && (
                          <div className="flex flex-wrap items-center gap-1.5 pt-2 text-[10px] text-muted-foreground font-mono">
                            <span>Evidence IDs:</span>
                            {evt.source_ids.map(sid => (
                              <span key={sid} className="bg-card px-1.5 py-0.5 border border-border rounded text-foreground">
                                {sid}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>

            </div>

            {/* Right column: Indicators, Critic, Citations (Spans 1 column) */}
            <div className="space-y-8">
              
              {/* F. Critic Evaluation Section */}
              <div className="p-6 rounded-2xl border border-border bg-card/25 shadow-sm space-y-4">
                <div className="flex items-center gap-2 border-b border-border/50 pb-3">
                  <ShieldCheck className="h-5 w-5 text-violet-400" />
                  <h2 className="font-bold text-lg">Critic Evaluation</h2>
                </div>

                {detail.approved ? (
                  <div className="space-y-3">
                    <div className="p-4 rounded-xl border border-emerald-500/20 bg-emerald-500/5 flex items-start gap-2.5">
                      <CheckCircle className="h-5 w-5 text-emerald-400 shrink-0 mt-0.5" />
                      <span className="text-sm text-emerald-300 font-semibold leading-relaxed">
                        Critic approved this prediction because citations and reasoning passed verification check.
                      </span>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-3">
                    <div className="p-4 rounded-xl border border-rose-500/20 bg-rose-500/5 flex items-start gap-2.5">
                      <XCircle className="h-5 w-5 text-rose-400 shrink-0 mt-0.5" />
                      <span className="text-sm text-rose-300 font-semibold leading-relaxed">
                        Critic rejected this prediction. Routing revision parameters back to Predictor.
                      </span>
                    </div>
                  </div>
                )}

                {/* Flags list */}
                {detail.critic_flags && detail.critic_flags.length > 0 && (
                  <div className="space-y-2 pt-2 border-t border-border/40">
                    <span className="text-[10px] text-rose-400 block font-bold uppercase tracking-wider">Evaluation Warning Flags</span>
                    <ul className="list-disc pl-4 text-xs text-rose-300/80 space-y-1.5 leading-relaxed font-sans">
                      {detail.critic_flags.map((flag, idx) => (
                        <li key={idx}>{flag}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>

              {/* E. Technical Indicators Section */}
              <div className="p-6 rounded-2xl border border-border bg-card/25 shadow-sm space-y-4">
                <div className="flex items-center gap-2 border-b border-border/50 pb-3">
                  <Activity className="h-5 w-5 text-violet-400" />
                  <h2 className="font-bold text-lg">Technical Indicators</h2>
                </div>

                {!detail.technical_features ? (
                  <p className="text-xs text-muted-foreground italic">
                    Technical indicator details were not stored for this prediction.
                  </p>
                ) : (
                  <div className="space-y-4">
                    {/* Momentum */}
                    <div className="space-y-1.5">
                      <div className="flex items-center justify-between text-xs">
                        <span className="font-bold text-foreground font-mono">Momentum</span>
                        <span className="font-mono text-violet-400 font-bold bg-secondary/40 px-1.5 py-0.5 rounded border border-border/40">
                          {detail.technical_features.momentum !== undefined ? detail.technical_features.momentum.toFixed(4) : "N/A"}
                        </span>
                      </div>
                      <p className="text-[10px] text-muted-foreground leading-relaxed">
                        Recent price trend movement magnitude over the lookback horizon. Positive shows upward velocity.
                      </p>
                    </div>

                    {/* RSI */}
                    <div className="space-y-1.5 border-t border-border/40 pt-2">
                      <div className="flex items-center justify-between text-xs">
                        <span className="font-bold text-foreground font-mono">Relative Strength Index (RSI)</span>
                        <span className="font-mono text-violet-400 font-bold bg-secondary/40 px-1.5 py-0.5 rounded border border-border/40">
                          {detail.technical_features.rsi !== undefined ? detail.technical_features.rsi.toFixed(1) : "N/A"}
                        </span>
                      </div>
                      <p className="text-[10px] text-muted-foreground leading-relaxed">
                        Momentum oscillator showing overbought (above 70) or oversold (below 30) asset conditions.
                      </p>
                    </div>

                    {/* Volume Change */}
                    <div className="space-y-1.5 border-t border-border/40 pt-2">
                      <div className="flex items-center justify-between text-xs">
                        <span className="font-bold text-foreground font-mono">Volume Change</span>
                        <span className="font-mono text-violet-400 font-bold bg-secondary/40 px-1.5 py-0.5 rounded border border-border/40">
                          {detail.technical_features.volume_change !== undefined ? `${(detail.technical_features.volume_change * 100).toFixed(1)}%` : "N/A"}
                        </span>
                      </div>
                      <p className="text-[10px] text-muted-foreground leading-relaxed">
                        Ratio showing recent trade volume change compared to moving average. Positive shows active participation.
                      </p>
                    </div>

                    {/* MA Cross */}
                    <div className="space-y-1.5 border-t border-border/40 pt-2">
                      <div className="flex items-center justify-between text-xs">
                        <span className="font-bold text-foreground font-mono">Moving Average Cross</span>
                        <span className="font-mono text-violet-400 font-bold bg-secondary/40 px-1.5 py-0.5 rounded border border-border/40 uppercase">
                          {detail.technical_features.ma_cross || "None"}
                        </span>
                      </div>
                      <p className="text-[10px] text-muted-foreground leading-relaxed">
                        Golden or Death cross signals showing long-term trend direction pivots.
                      </p>
                    </div>
                  </div>
                )}
              </div>

              {/* G. Citations / Evidence Section */}
              <div className="p-6 rounded-2xl border border-border bg-card/25 shadow-sm space-y-4">
                <div className="flex items-center gap-2 border-b border-border/50 pb-3">
                  <Bookmark className="h-5 w-5 text-violet-400" />
                  <h2 className="font-bold text-lg">Cited Evidence</h2>
                </div>

                {detail.cited_event_ids && detail.cited_event_ids.length > 0 ? (
                  <div className="space-y-2">
                    <span className="text-[10px] text-muted-foreground font-bold uppercase tracking-wider block">Cited Event IDs</span>
                    <div className="flex flex-wrap gap-1.5">
                      {detail.cited_event_ids.map((id) => (
                        <span 
                          key={id}
                          className="px-2 py-0.5 rounded border border-border bg-secondary/50 font-mono text-[10px] font-bold text-foreground"
                        >
                          {id}
                        </span>
                      ))}
                    </div>
                  </div>
                ) : (
                  <p className="text-xs text-muted-foreground italic">
                    No explicit event citations were referenced in the final approved forecast.
                  </p>
                )}
                
                {detail.chunks && detail.chunks.length > 0 ? (
                  <div className="space-y-3 pt-2 border-t border-border/40">
                    <span className="text-[10px] text-muted-foreground font-bold uppercase tracking-wider block">Retrieved News Chunks</span>
                    <div className="space-y-3">
                      {detail.chunks.map((chunk) => (
                        <div key={chunk.id} className="p-3 rounded-xl border border-border bg-secondary/10 space-y-2">
                          <div className="flex items-center justify-between text-[10px] font-semibold text-muted-foreground font-mono">
                            <span>Source: <span className="text-foreground">{chunk.source}</span></span>
                            <span>Date: <span className="text-foreground">{chunk.date}</span></span>
                          </div>
                          <p className="text-xs text-foreground/90 leading-relaxed font-sans">
                            {chunk.text}
                          </p>
                          <div className="text-[9px] font-mono text-muted-foreground/60">
                            Chunk ID: {chunk.id}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="pt-2 border-t border-border/40">
                    <p className="text-[10px] text-muted-foreground leading-relaxed italic">
                      Citations verified by ID; full source text not included in this view.
                    </p>
                  </div>
                )}
              </div>

            </div>

          </div>

        </div>
      ) : null}
    </div>
  );
}
