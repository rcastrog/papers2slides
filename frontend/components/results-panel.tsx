"use client";

import { useEffect, useState } from "react";

import { getRunResults, type RunResultsResponse } from "../lib/api";

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
        </>
      ) : null}
    </div>
  );
}
