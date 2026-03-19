"use client";

import { useEffect, useState } from "react";

import {
  getRunResults,
  type CitationRepetitionSummary,
  type RepetitionCountItem,
  type RepetitionExample,
  type RepetitionLevelSummary,
  type RunResultsResponse,
} from "../lib/api";

type ResultsPanelProps = {
  runId: string;
};

export function ResultsPanel({ runId }: ResultsPanelProps) {
  const [results, setResults] = useState<RunResultsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadResults() {
      try {
        const payload = await getRunResults(runId);
        if (!cancelled) {
          setResults(payload);
          setError(null);
        }
      } catch (loadError) {
        if (!cancelled) {
          const message = loadError instanceof Error ? loadError.message : "Failed to load results";
          setError(message);
        }
      }
    }

    loadResults();

    return () => {
      cancelled = true;
    };
  }, [runId]);

  return (
    <div className="card stack">
      <h2 style={{ margin: 0 }}>Run results</h2>

      {error ? <div className="error">{error}</div> : null}

      {!results ? <div className="muted">Loading results...</div> : null}

      {results ? (
        <>
          {results.quality_gate?.passed === false ? (
            <div className="error" style={{ overflowWrap: "anywhere" }}>
              Quality gate failed for this run.
              {results.quality_gate.issues && results.quality_gate.issues.length > 0
                ? ` Reasons: ${results.quality_gate.issues.join(" | ")}`
                : ""}
            </div>
          ) : null}

          <div>Reveal output: {results.reveal_path || "not available"}</div>
          <div>PPTX output: {results.pptx_path || "not available"}</div>
          <div>Notes path: {results.notes_path || "not available"}</div>
          <div>Audit report path: {results.audit_report_path || "not available"}</div>
          <div>
            Extracted assets found: {String(results.asset_usage_summary?.extracted_assets_count ?? 0)}
          </div>
          <div>
            Asset mappings resolved: {String(results.asset_usage_summary?.asset_map_resolved ?? 0)} / {String(results.asset_usage_summary?.asset_map_total ?? 0)}
          </div>
          <div>
            Slides using real source figures: {String(results.asset_usage_summary?.slides_using_real_source_figures ?? 0)}
          </div>
          <div>Risk summary: {JSON.stringify(results.final_risk_summary)}</div>

          <div className="panel stack">
            <h3 className="section-title" style={{ margin: 0 }}>Repetition metrics</h3>
            <div className="muted">
              Combines exact duplication and semantic near-duplicate detection to catch paraphrased repetition.
            </div>
            <RepetitionLevelSection title="Bullets" summary={results.repetition_metrics?.bullet} />
            <RepetitionLevelSection title="Slides" summary={results.repetition_metrics?.slide} />
            <CitationRepetitionSection summary={results.repetition_metrics?.citation} />
            <div className="muted">
              Similarity thresholds: bullets {formatNumber(results.repetition_metrics?.semantic_similarity_thresholds?.bullet)}, slides {formatNumber(results.repetition_metrics?.semantic_similarity_thresholds?.slide)}, citation reasons {formatNumber(results.repetition_metrics?.semantic_similarity_thresholds?.citation_reason)}
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}

type RepetitionLevelSectionProps = {
  title: string;
  summary?: RepetitionLevelSummary;
};

function RepetitionLevelSection({ title, summary }: RepetitionLevelSectionProps) {
  return (
    <div className="stack" style={{ borderTop: "1px solid #e2e8f0", paddingTop: 8 }}>
      <div style={{ fontWeight: 600 }}>{title}</div>
      <div>Total: {String(summary?.total ?? 0)}</div>
      <div>Unique exact: {String(summary?.unique_exact ?? 0)}</div>
      <div>Exact unique ratio: {formatRatio(summary?.exact_unique_ratio)}</div>
      <div>Exact repeated instances: {String(summary?.exact_repeated_instances ?? 0)}</div>
      <div>Near-duplicate pairs: {String(summary?.near_duplicate_pair_count ?? 0)}</div>
      <div>Near-duplicate clusters: {String(summary?.near_duplicate_cluster_count ?? 0)}</div>
      <div>Max near-duplicate similarity: {formatNumber(summary?.max_near_duplicate_similarity)}</div>
      <RepeatList title="Top exact repeats" items={summary?.top_exact_repeats} />
      <NearDuplicateExampleList title="Near-duplicate examples" items={summary?.near_duplicate_examples} />
    </div>
  );
}

type CitationSectionProps = {
  summary?: CitationRepetitionSummary;
};

function CitationRepetitionSection({ summary }: CitationSectionProps) {
  return (
    <div className="stack" style={{ borderTop: "1px solid #e2e8f0", paddingTop: 8 }}>
      <div style={{ fontWeight: 600 }}>Citations</div>
      <div>Total mentions: {String(summary?.total_mentions ?? 0)}</div>
      <div>Unique labels (exact): {String(summary?.unique_labels_exact ?? 0)}</div>
      <div>Exact unique label ratio: {formatRatio(summary?.exact_unique_label_ratio)}</div>
      <div>Exact repeated label instances: {String(summary?.exact_label_repeated_instances ?? 0)}</div>
      <div>Reason near-duplicate pairs: {String(summary?.reason_near_duplicate_pair_count ?? 0)}</div>
      <div>Reason near-duplicate clusters: {String(summary?.reason_near_duplicate_cluster_count ?? 0)}</div>
      <div>Max reason similarity: {formatNumber(summary?.max_reason_similarity)}</div>
      <RepeatList title="Top repeated labels" items={summary?.top_repeated_labels} />
      <NearDuplicateExampleList title="Near-duplicate reasons" items={summary?.reason_near_duplicate_examples} />
    </div>
  );
}

type RepeatListProps = {
  title: string;
  items?: RepetitionCountItem[];
};

function RepeatList({ title, items }: RepeatListProps) {
  if (!items || items.length === 0) {
    return <div>{title}: none</div>;
  }
  return (
    <div className="stack">
      <div>{title}:</div>
      <ul style={{ margin: 0 }}>
        {items.slice(0, 3).map((item, index) => (
          <li key={`${item.text}-${index}`}>{item.count}x - {item.text}</li>
        ))}
      </ul>
    </div>
  );
}

type NearDuplicateExampleListProps = {
  title: string;
  items?: RepetitionExample[];
};

function NearDuplicateExampleList({ title, items }: NearDuplicateExampleListProps) {
  if (!items || items.length === 0) {
    return <div>{title}: none</div>;
  }
  return (
    <div className="stack">
      <div>{title}:</div>
      <ul style={{ margin: 0 }}>
        {items.slice(0, 2).map((item, index) => (
          <li key={`${item.text_a}-${item.text_b}-${index}`}>
            ({formatNumber(item.similarity)}) {item.text_a} vs {item.text_b}
          </li>
        ))}
      </ul>
    </div>
  );
}

function formatRatio(value: number | undefined): string {
  if (typeof value !== "number") return "n/a";
  return `${(value * 100).toFixed(1)}%`;
}

function formatNumber(value: number | undefined): string {
  if (typeof value !== "number") return "n/a";
  return value.toFixed(2);
}
