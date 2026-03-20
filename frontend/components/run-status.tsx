"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import {
  cancelRun,
  getRunResults,
  getRunStatus,
  getSlideEvidence,
  recoverRunA11,
  regenerateSlide,
  retryRun,
  type RunStatusResponse,
  type SlideEvidenceResponse,
} from "../lib/api";
import { formatStageLabel } from "../lib/stage-names";

type RunStatusProps = {
  runId: string;
};

export function RunStatus({ runId }: RunStatusProps) {
  const [status, setStatus] = useState<RunStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [isCancelling, setIsCancelling] = useState(false);
  const [isRecovering, setIsRecovering] = useState(false);
  const [isRetrying, setIsRetrying] = useState(false);
  const [hasRevealOutput, setHasRevealOutput] = useState(false);
  const [hasPptxOutput, setHasPptxOutput] = useState(false);
  const [repetitionMetrics, setRepetitionMetrics] = useState<Record<string, unknown> | null>(null);
  const [qualityGate, setQualityGate] = useState<Record<string, unknown> | null>(null);
  const [evidence, setEvidence] = useState<SlideEvidenceResponse | null>(null);
  const [isEvidenceLoading, setIsEvidenceLoading] = useState(false);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);
  const [regeneratingSlideId, setRegeneratingSlideId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      try {
        const nextStatus = await getRunStatus(runId);
        if (!cancelled) {
          setStatus(nextStatus);
          setError(null);
        }
      } catch (pollError) {
        if (!cancelled) {
          const message = pollError instanceof Error ? pollError.message : "Failed to load run status";
          setError(message);
        }
      }
    }

    poll();
    const timer = setInterval(poll, 3000);

    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [runId]);

  const isResultsAvailable = useMemo(() => {
    if (!status) return false;
    return status.status === "completed" || status.status === "completed_with_warnings" || status.status === "failed_with_quality_gate";
  }, [status]);

  const isTerminal = useMemo(() => {
    if (!status) return false;
    return ["completed", "completed_with_warnings", "failed", "failed_with_quality_gate", "cancelled"].includes(status.status);
  }, [status]);

  const isEvidenceEligible = useMemo(() => {
    if (!status) return false;
    return status.status === "completed" || status.status === "completed_with_warnings";
  }, [status]);

  const canCancel = useMemo(() => {
    if (!status) return false;
    return ["queued", "running", "cancel_requested"].includes(status.status);
  }, [status]);

  const canRecoverA11 = useMemo(() => {
    if (!status) return false;
    return status.status === "failed" && status.current_stage === "A11";
  }, [status]);

  const canRetry = useMemo(() => {
    if (!status) return false;
    return status.status === "failed" || status.status === "failed_with_quality_gate";
  }, [status]);

  useEffect(() => {
    let cancelled = false;

    async function loadOutputAvailability() {
      if (!isResultsAvailable) {
        setHasRevealOutput(false);
        setHasPptxOutput(false);
        setRepetitionMetrics(null);
        setQualityGate(null);
        return;
      }

      try {
        const results = await getRunResults(runId);
        if (!cancelled) {
          setHasRevealOutput(Boolean(results.reveal_path));
          setHasPptxOutput(Boolean(results.pptx_path));
          setRepetitionMetrics((results.repetition_metrics as Record<string, unknown> | undefined) ?? null);
          setQualityGate((results.quality_gate as Record<string, unknown> | undefined) ?? null);
        }
      } catch {
        if (!cancelled) {
          setHasRevealOutput(false);
          setHasPptxOutput(false);
          setRepetitionMetrics(null);
          setQualityGate(null);
        }
      }
    }

    loadOutputAvailability();

    return () => {
      cancelled = true;
    };
  }, [isResultsAvailable, runId]);

  useEffect(() => {
    let cancelled = false;

    async function loadEvidence() {
      if (!isEvidenceEligible) {
        setEvidence(null);
        setEvidenceError(null);
        setIsEvidenceLoading(false);
        return;
      }

      setIsEvidenceLoading(true);
      setEvidenceError(null);
      try {
        const payload = await getSlideEvidence(runId);
        if (!cancelled) {
          setEvidence(payload);
          setEvidenceError(null);
        }
      } catch (loadError) {
        if (!cancelled) {
          const message = loadError instanceof Error ? loadError.message : "Failed to load slide evidence";
          setEvidence(null);
          setEvidenceError(message);
        }
      } finally {
        if (!cancelled) {
          setIsEvidenceLoading(false);
        }
      }
    }

    loadEvidence();

    return () => {
      cancelled = true;
    };
  }, [isEvidenceEligible, runId]);

  function handleOpenReveal() {
    const revealUrl = `${process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000"}/runs/${runId}/reveal/index.html`;
    window.open(revealUrl, "_blank", "noopener,noreferrer");
  }

  function handleOpenDeck() {
    const deckUrl = `${process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000"}/runs/${runId}/download/pptx`;
    window.open(deckUrl, "_blank", "noopener,noreferrer");
  }

  async function handleCancel() {
    setIsCancelling(true);
    setError(null);
    setActionMessage(null);
    try {
      const result = await cancelRun(runId);
      setActionMessage(result.message || `Run status: ${result.status}`);
      const refreshed = await getRunStatus(runId);
      setStatus(refreshed);
    } catch (cancelError) {
      const message = cancelError instanceof Error ? cancelError.message : "Failed to cancel run";
      setError(message);
    } finally {
      setIsCancelling(false);
    }
  }

  async function handleRecoverA11() {
    setIsRecovering(true);
    setError(null);
    setActionMessage(null);
    try {
      const result = await recoverRunA11(runId);
      setActionMessage(`A11 recovery completed: ${result.status}`);
      const refreshed = await getRunStatus(runId);
      setStatus(refreshed);
    } catch (recoverError) {
      const message = recoverError instanceof Error ? recoverError.message : "Failed to recover run";
      setError(message);
    } finally {
      setIsRecovering(false);
    }
  }

  async function handleRetryRun() {
    setIsRetrying(true);
    setError(null);
    setActionMessage(null);
    try {
      const result = await retryRun(runId);
      setActionMessage(`Retry started: ${result.run_id}`);
      window.location.assign(`/run/${result.run_id}`);
    } catch (retryError) {
      const message = retryError instanceof Error ? retryError.message : "Failed to retry run";
      setError(message);
    } finally {
      setIsRetrying(false);
    }
  }

  async function handleRegenerateSlide(slideId: string) {
    setRegeneratingSlideId(slideId);
    setError(null);
    setActionMessage(null);
    try {
      const idempotencyKey = buildSlideRegenerationIdempotencyKey(runId, slideId);
      const result = await regenerateSlide(runId, slideId, idempotencyKey);
      setActionMessage(`Slide regenerated: ${result.slide_id}`);
      const refreshedEvidence = await getSlideEvidence(runId);
      setEvidence(refreshedEvidence);
      setEvidenceError(null);
      const refreshedStatus = await getRunStatus(runId);
      setStatus(refreshedStatus);
    } catch (regenerateError) {
      const message = regenerateError instanceof Error ? regenerateError.message : "Failed to regenerate slide";
      setError(message);
    } finally {
      setRegeneratingSlideId(null);
    }
  }

  const summary = status?.job_summary;
  const warningSummary = useMemo(() => buildWarningsSummary(status), [status]);
  const warningInsights = useMemo(() => buildWarningInsights(status), [status]);
  const repetitionSummary = useMemo(() => buildRepetitionSummary(repetitionMetrics), [repetitionMetrics]);
  const repetitionHighlights = useMemo(() => buildRepetitionHighlights(repetitionMetrics), [repetitionMetrics]);
  const qualityGateIssues = useMemo(() => buildQualityGateIssues(qualityGate), [qualityGate]);
  const retrievalSummary = status?.retrieval_summary;

  return (
    <div className="card stack">
      <h2 style={{ margin: 0 }}>Run status</h2>

      <div className="panel stack">
        <h3 className="section-title">General</h3>
        <div className="status-grid">
          <div>Run ID: {runId}</div>
          <div>Source PDF: {status?.source_pdf_name || "unknown"}</div>
          <div>Status: {status?.status ?? "loading"}</div>
          <div>Current stage: {status?.current_stage ? formatStageLabel(status.current_stage) : "unknown"}</div>
          <div>
          Completed stages: {status?.completed_stages?.length ? status.completed_stages.map((stageId) => formatStageLabel(stageId)).join(", ") : "none"}
          </div>
          <div>Recorded stages: {status?.stage_count ?? 0}</div>
          <div>Fallback stages: {status?.fallback_stage_count ?? 0}</div>
          <div>Total duration: {status?.total_duration_ms != null ? `${status.total_duration_ms} ms` : "n/a"}</div>
          <div>Warnings count: {status?.warning_count ?? 0}</div>
          <div>Audit findings count: {status?.audit_findings_count ?? "n/a"}</div>
          <div>
            Retrieval: {String(retrievalSummary?.retrieved_count ?? 0)} / {String(retrievalSummary?.total_references ?? 0)} verified
          </div>
          <div>
            Retrieval unresolved: {String(retrievalSummary?.not_found_count ?? 0)} (ambiguous: {String(retrievalSummary?.ambiguous_count ?? 0)})
          </div>
        </div>
        {retrievalSummary?.grounding_note ? (
          <div className="muted" style={{ overflowWrap: "anywhere" }}>
            {String(retrievalSummary.grounding_note)}
          </div>
        ) : null}
      </div>

      <div className="two-up">
        <div className="panel stack">
          <h3 className="section-title">Run Status</h3>
          <div className="status-grid">
            <div>Source PDF: {status?.source_pdf_name || "unknown"}</div>
            <div>Status: {status?.status ?? "loading"}</div>
            <div>Current stage: {status?.current_stage ? formatStageLabel(status.current_stage) : "unknown"}</div>
            <div>Recorded stages: {status?.stage_count ?? 0}</div>
            <div>Fallback stages: {status?.fallback_stage_count ?? 0}</div>
            <div>Total duration: {status?.total_duration_ms != null ? `${status.total_duration_ms} ms` : "n/a"}</div>
            <div>Warnings count: {status?.warning_count ?? 0}</div>
          </div>
        </div>

        <div className="panel stack">
          <h3 className="section-title">Job Summary</h3>
          {summary && Object.keys(summary).length > 0 ? (
          <div className="status-grid">
            <div>Style: {String(summary.presentation_style ?? "n/a")}</div>
            <div>Audience: {String(summary.target_audience ?? "n/a")}</div>
            <div>Language: {String(summary.language ?? "n/a")}</div>
            <div>Target slides: {String(summary.target_slide_count ?? "n/a")}</div>
            <div>Target duration: {String(summary.target_duration_minutes ?? "n/a")} min</div>
            <div>Repair on audit: {String(Boolean(summary.repair_on_audit))}</div>
          </div>
          ) : (
            <div className="muted">Job summary not available yet.</div>
          )}
        </div>
      </div>

      {!isTerminal ? <div className="muted">Polling every 3s until completion...</div> : null}

      {status?.status === "failed_with_quality_gate" ? (
        <div className="error" style={{ overflowWrap: "anywhere" }}>
          Quality gate failed. Presentations were still generated for inspection.
          {qualityGateIssues.length > 0 ? ` Reasons: ${qualityGateIssues.join(" | ")}` : ""}
        </div>
      ) : null}

      <div className="panel stack">
        <h3 className="section-title">Warnings</h3>
        <div className="muted" style={{ overflowWrap: "anywhere" }}>
          AI summary: {warningSummary}
        </div>
        {warningInsights.length > 0 ? (
          <ul style={{ margin: 0, paddingLeft: 20 }}>
            {warningInsights.map((insight, index) => (
              <li key={`insight-${index}`} style={{ marginBottom: 6, overflowWrap: "anywhere" }}>
                {insight}
              </li>
            ))}
          </ul>
        ) : null}
        <div className="muted" style={{ overflowWrap: "anywhere" }}>
          Repetitiveness summary: {repetitionSummary}
        </div>
        {repetitionHighlights.length > 0 ? (
          <ul style={{ margin: 0, paddingLeft: 20 }}>
            {repetitionHighlights.map((item, index) => (
              <li key={`repeat-${index}`} style={{ marginBottom: 6, overflowWrap: "anywhere" }}>
                {item}
              </li>
            ))}
          </ul>
        ) : null}
        {status?.stage_warnings && status.stage_warnings.length > 0 ? (
          <ul style={{ margin: 0, paddingLeft: 20 }}>
            {status.stage_warnings.map((group, groupIndex) => (
              <li key={`${group.stage}-${groupIndex}`} style={{ marginBottom: 8, overflowWrap: "anywhere" }}>
                {group.stage === "run_global" ? "Run-level" : formatStageLabel(group.stage)}
                <ul style={{ margin: "6px 0 0 0", paddingLeft: 20 }}>
                  {group.warnings.map((warning, warningIndex) => (
                    <li key={`${group.stage}-${warningIndex}`} style={{ marginBottom: 6, overflowWrap: "anywhere" }}>
                      {warning}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        ) : status?.warnings && status.warnings.length > 0 ? (
          <ul style={{ margin: 0, paddingLeft: 20 }}>
            {status.warnings.map((warning, index) => (
              <li key={`${warning}-${index}`} style={{ marginBottom: 6, overflowWrap: "anywhere" }}>
                {warning}
              </li>
            ))}
          </ul>
        ) : (
          <div className="muted">No warnings recorded for this run.</div>
        )}
      </div>

      <div className="panel stack">
        <h3 className="section-title">Slide Evidence Inspector</h3>
        {!isEvidenceEligible ? <div className="muted">Slide evidence is available when the run reaches a completed state.</div> : null}
        {isEvidenceEligible && isEvidenceLoading ? <div className="muted">Loading slide evidence...</div> : null}
        {isEvidenceEligible && evidenceError ? (
          <div className="error" style={{ overflowWrap: "anywhere" }}>
            {evidenceError}
          </div>
        ) : null}
        {isEvidenceEligible && !isEvidenceLoading && !evidenceError && evidence?.warnings?.length ? (
          <ul style={{ margin: 0, paddingLeft: 20 }}>
            {evidence.warnings.map((warning, index) => (
              <li key={`evidence-warning-${index}`} className="muted" style={{ marginBottom: 6, overflowWrap: "anywhere" }}>
                {warning}
              </li>
            ))}
          </ul>
        ) : null}
        {isEvidenceEligible && !isEvidenceLoading && !evidenceError && evidence?.slides?.length ? (
          <div className="stack">
            {evidence.slides.map((slide) => (
              <div key={slide.slide_id} className="panel stack" style={{ padding: 12 }}>
                <div className="status-grid">
                  <div>
                    <strong>Slide {slide.slide_number}</strong>: {slide.slide_title || "Untitled slide"}
                  </div>
                  <div>
                    Claims: {slide.claim_count} · No-evidence claims: {slide.no_evidence_claim_count}
                  </div>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                    {slide.confidence_flags.map((flag) => (
                      <span
                        key={`${slide.slide_id}-confidence-${flag}`}
                        style={{
                          border: "1px solid var(--border-strong)",
                          borderRadius: 999,
                          padding: "2px 8px",
                          fontSize: 12,
                        }}
                      >
                        confidence: {flag}
                      </span>
                    ))}
                    {slide.quality_flags.map((flag) => (
                      <span
                        key={`${slide.slide_id}-quality-${flag}`}
                        style={{
                          border: "1px solid var(--border-strong)",
                          borderRadius: 999,
                          padding: "2px 8px",
                          fontSize: 12,
                        }}
                      >
                        quality: {flag}
                      </span>
                    ))}
                    {!slide.confidence_flags.length && !slide.quality_flags.length ? (
                      <span className="muted" style={{ fontSize: 12 }}>
                        No confidence or quality flags.
                      </span>
                    ) : null}
                  </div>
                </div>

                <details>
                  <summary style={{ cursor: "pointer" }}>Claims ({slide.claims.length})</summary>
                  <div className="stack" style={{ marginTop: 10 }}>
                    {slide.claims.length ? (
                      slide.claims.map((claim) => (
                        <div key={claim.claim_id} className="panel stack" style={{ padding: 10 }}>
                          <div style={{ overflowWrap: "anywhere" }}>{claim.claim_text}</div>
                          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                            {claim.confidence_flag ? (
                              <span
                                style={{
                                  border: "1px solid var(--border-strong)",
                                  borderRadius: 999,
                                  padding: "2px 8px",
                                  fontSize: 12,
                                }}
                              >
                                confidence: {claim.confidence_flag}
                              </span>
                            ) : null}
                            {claim.no_evidence ? (
                              <span
                                style={{
                                  border: "1px solid var(--border-strong)",
                                  borderRadius: 999,
                                  padding: "2px 8px",
                                  fontSize: 12,
                                }}
                              >
                                no evidence
                              </span>
                            ) : null}
                            {claim.quality_flags.map((flag) => (
                              <span
                                key={`${claim.claim_id}-quality-${flag}`}
                                style={{
                                  border: "1px solid var(--border-strong)",
                                  borderRadius: 999,
                                  padding: "2px 8px",
                                  fontSize: 12,
                                }}
                              >
                                {flag}
                              </span>
                            ))}
                          </div>
                          <div className="status-grid">
                            <div>
                              Citation labels: {claim.citation_labels.length ? claim.citation_labels.join(", ") : "none"}
                            </div>
                            <div>
                              Citation links: {claim.citation_links.length ? (
                                <span>
                                  {claim.citation_links.map((link, index) => (
                                    <span key={`${claim.claim_id}-link-${index}`}>
                                      <a href={link} target="_blank" rel="noopener noreferrer">
                                        Source {index + 1}
                                      </a>
                                      {index < claim.citation_links.length - 1 ? " · " : ""}
                                    </span>
                                  ))}
                                </span>
                              ) : (
                                "none"
                              )}
                            </div>
                          </div>
                          {claim.source_snippets.length ? (
                            <ul style={{ margin: 0, paddingLeft: 20 }}>
                              {claim.source_snippets.map((snippet, index) => (
                                <li key={`${claim.claim_id}-snippet-${index}`} style={{ marginBottom: 6, overflowWrap: "anywhere" }}>
                                  {snippet}
                                </li>
                              ))}
                            </ul>
                          ) : (
                            <div className="muted">No source snippet available for this claim.</div>
                          )}
                        </div>
                      ))
                    ) : (
                      <div className="muted">No claims available for this slide.</div>
                    )}
                  </div>
                </details>

                <div>
                  <button
                    className="btn-secondary"
                    type="button"
                    disabled={Boolean(regeneratingSlideId)}
                    onClick={() => handleRegenerateSlide(slide.slide_id)}
                  >
                    {regeneratingSlideId === slide.slide_id ? "Regenerating..." : "Regenerate slide"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        ) : null}
        {isEvidenceEligible && !isEvidenceLoading && !evidenceError && !evidence?.slides?.length ? (
          <div className="muted">No slide evidence available for this run.</div>
        ) : null}
      </div>

      {actionMessage ? <div className="success">{actionMessage}</div> : null}

      {isResultsAvailable && !hasRevealOutput ? <div className="muted">Reveal output was not generated for this run.</div> : null}
      {isResultsAvailable && !hasPptxOutput ? <div className="muted">PPTX output was not generated for this run.</div> : null}

      {error ? <div className="error">{error}</div> : null}

      <div className="panel stack">
        <h3 className="section-title">Quick output actions</h3>
        <div className="top-links">
          {canCancel ? (
            <button className="btn-secondary" type="button" disabled={isCancelling} onClick={handleCancel}>
              {isCancelling ? "Requesting cancel..." : "Stop run"}
            </button>
          ) : null}
          <button className="btn-secondary" type="button" disabled={!isResultsAvailable || !hasRevealOutput} onClick={handleOpenReveal}>
            Open Reveal
          </button>
          <button className="btn-secondary" type="button" disabled={!isResultsAvailable || !hasPptxOutput} onClick={handleOpenDeck}>
            Open Deck
          </button>
          {canRecoverA11 ? (
            <button className="btn-secondary" type="button" disabled={isRecovering} onClick={handleRecoverA11}>
              {isRecovering ? "Recovering..." : "Recover from A11"}
            </button>
          ) : null}
          {canRetry ? (
            <button className="btn-secondary" type="button" disabled={isRetrying} onClick={handleRetryRun}>
              {isRetrying ? "Starting retry..." : "Retry run"}
            </button>
          ) : null}
          {isResultsAvailable ? <Link href={`/results/${runId}`}>View results</Link> : null}
          {isResultsAvailable ? <Link href={`/inspect/${runId}`}>Inspect run</Link> : null}
        </div>
      </div>

      <div className="panel stack">
        <h3 className="section-title">Action hints</h3>
        {canCancel ? <div className="muted">Stop run: Requests a safe stop at the next stage boundary.</div> : null}
        {isResultsAvailable ? (
          <div className="muted">
            Open Reveal: Opens the HTML slide deck generated for this run.
            {!hasRevealOutput ? " (Unavailable because no Reveal output was generated.)" : ""}
          </div>
        ) : (
          <div className="muted">Open Reveal: Available after the run completes and Reveal output exists.</div>
        )}
        {isResultsAvailable ? (
          <div className="muted">
            Open Deck: Opens the repaired PPTX deck file for editing.
            {!hasPptxOutput ? " (Unavailable because no PPTX output was generated.)" : ""}
          </div>
        ) : (
          <div className="muted">Open Deck: Available after the run completes and PPTX output exists.</div>
        )}
        {canRecoverA11 ? (
          <div className="muted">Recover from A11: Re-runs only the final audit/repair stage for this failed run.</div>
        ) : null}
        {canRetry ? (
          <div className="muted">Retry run: Starts a new run using the same source file and prior parameters.</div>
        ) : null}
      </div>

    </div>
  );
}

function buildWarningsSummary(status: RunStatusResponse | null): string {
  if (!status) {
    return "Waiting for run status data.";
  }

  const grouped = status.stage_warnings ?? [];
  const warnings = grouped.flatMap((group) => group.warnings);
  const normalizedWarnings = warnings.length > 0 ? warnings : status.warnings;
  if (!normalizedWarnings.length) {
    return "No warnings were recorded in this run.";
  }

  const hasCitationGuard = normalizedWarnings.some((warning) =>
    warning.toLowerCase().includes("external-reference citation guard")
  );
  const hasRetrievalNoise = normalizedWarnings.some((warning) =>
    warning.toLowerCase().includes("reference") &&
    (warning.toLowerCase().includes("retrieval") || warning.toLowerCase().includes("not_found") || warning.toLowerCase().includes("synthesized"))
  );
  const hasVisualFallback = normalizedWarnings.some((warning) => warning.toLowerCase().includes("image generation disabled"));

  const focus: string[] = [];
  if (hasCitationGuard) {
    focus.push("citation compliance is the top blocker and should be fixed first");
  }
  if (hasRetrievalNoise) {
    focus.push("reference retrieval was partially recovered but still incomplete");
  }
  if (hasVisualFallback) {
    focus.push("visuals are deterministic fallbacks rather than generated images");
  }

  const stageCount = grouped.filter((group) => group.stage !== "run_global").length;
  if (!focus.length) {
    return `Warnings were recorded across ${stageCount} stage(s); review run-level items first, then stage warnings in order.`;
  }
  return `Warnings were recorded across ${stageCount} stage(s). Priority focus: ${focus.join("; ")}.`;
}

function buildWarningInsights(status: RunStatusResponse | null): string[] {
  if (!status) {
    return [];
  }

  const grouped = status.stage_warnings ?? [];
  const warnings = grouped.flatMap((group) => group.warnings);
  const normalizedWarnings = warnings.length > 0 ? warnings : status.warnings;
  if (!normalizedWarnings.length) {
    return [];
  }

  const insights: string[] = [];
  const hasCitationGuard = normalizedWarnings.some((warning) =>
    warning.toLowerCase().includes("external-reference citation guard")
  );
  if (hasCitationGuard) {
    insights.push("Citation guard triggered: add at least one retrieved reference-paper citation on each external-work slide.");
  }

  const retrieval = status.retrieval_summary;
  if (retrieval && typeof retrieval.not_found_count === "number" && retrieval.not_found_count > 0) {
    insights.push(
      `Reference retrieval remains incomplete: ${retrieval.not_found_count} reference(s) unresolved and excluded from strict citation grounding.`
    );
  }

  const hasVisualFallback = normalizedWarnings.some((warning) => warning.toLowerCase().includes("image generation disabled"));
  if (hasVisualFallback) {
    insights.push("Visual generation was disabled, so source-first or text-first fallbacks were used.");
  }

  return insights;
}

function buildRepetitionSummary(metrics: Record<string, unknown> | null): string {
  if (!metrics) {
    return "Repetition metrics are not available yet.";
  }

  const bullet = asRecord(metrics.bullet);
  const slide = asRecord(metrics.slide);
  const citation = asRecord(metrics.citation);

  const bulletDupes = asNumber(bullet.exact_repeated_instances);
  const bulletPairs = asNumber(bullet.near_duplicate_pair_count);
  const slideDupes = asNumber(slide.exact_repeated_instances);
  const citationDupes = asNumber(citation.exact_label_repeated_instances);
  const citationReasonPairs = asNumber(citation.reason_near_duplicate_pair_count);

  const segments = [
    `bullets exact repeats: ${bulletDupes}`,
    `bullets near-duplicate pairs: ${bulletPairs}`,
    `slides exact repeats: ${slideDupes}`,
    `citation label repeats: ${citationDupes}`,
    `citation rationale near-duplicates: ${citationReasonPairs}`,
  ];
  return segments.join("; ");
}

function buildRepetitionHighlights(metrics: Record<string, unknown> | null): string[] {
  if (!metrics) {
    return [];
  }

  const highlights: string[] = [];
  const bullet = asRecord(metrics.bullet);
  const slide = asRecord(metrics.slide);

  const topBulletRepeats = asArrayOfRecords(bullet.top_exact_repeats);
  if (topBulletRepeats.length > 0) {
    const first = topBulletRepeats[0];
    const text = String(first.text ?? "").trim();
    const count = asNumber(first.count);
    if (text) {
      highlights.push(`Top repeated bullet (${count}x): ${truncateForSummary(text, 140)}`);
    }
  }

  const topSlideRepeats = asArrayOfRecords(slide.top_exact_repeats);
  if (topSlideRepeats.length > 0) {
    const first = topSlideRepeats[0];
    const text = String(first.text ?? "").trim();
    const count = asNumber(first.count);
    if (text) {
      highlights.push(`Top repeated slide signature (${count}x): ${truncateForSummary(text, 140)}`);
    }
  }

  return highlights;
}

function buildQualityGateIssues(qualityGate: Record<string, unknown> | null): string[] {
  if (!qualityGate) {
    return [];
  }
  const issues = qualityGate.issues;
  if (!Array.isArray(issues)) {
    return [];
  }
  return issues
    .map((item) => String(item || "").trim())
    .filter((item) => item.length > 0);
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function asNumber(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function asArrayOfRecords(value: unknown): Record<string, unknown>[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object"));
}

function truncateForSummary(value: string, maxLength: number): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, maxLength - 1)}...`;
}

function buildSlideRegenerationIdempotencyKey(runId: string, slideId: string): string {
  const randomValue =
    typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${runId}:${slideId}:${randomValue}`;
}
