"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { cancelRun, getRunResults, getRunStatus, recoverRunA11, retryRun, type RunStatusResponse } from "../lib/api";
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

  const isCompleted = useMemo(() => {
    if (!status) return false;
    return status.status === "completed" || status.status === "completed_with_warnings";
  }, [status]);

  const isTerminal = useMemo(() => {
    if (!status) return false;
    return ["completed", "completed_with_warnings", "failed", "cancelled"].includes(status.status);
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
    return status.status === "failed";
  }, [status]);

  useEffect(() => {
    let cancelled = false;

    async function loadRevealAvailability() {
      if (!isCompleted) {
        setHasRevealOutput(false);
        return;
      }

      try {
        const results = await getRunResults(runId);
        if (!cancelled) {
          setHasRevealOutput(Boolean(results.reveal_path));
        }
      } catch {
        if (!cancelled) {
          setHasRevealOutput(false);
        }
      }
    }

    loadRevealAvailability();

    return () => {
      cancelled = true;
    };
  }, [isCompleted, runId]);

  function handleOpenReveal() {
    const revealUrl = `${process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000"}/runs/${runId}/reveal/index.html`;
    window.open(revealUrl, "_blank", "noopener,noreferrer");
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

  const summary = status?.job_summary;

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
        </div>
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

      <div className="top-links">
        {canCancel ? (
          <button className="btn-secondary" type="button" disabled={isCancelling} onClick={handleCancel}>
            {isCancelling ? "Requesting cancel..." : "Stop run"}
          </button>
        ) : null}
        <button className="btn-secondary" type="button" disabled={!isCompleted || !hasRevealOutput} onClick={handleOpenReveal}>
          Open Reveal
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
      </div>

      <div className="panel stack">
        <h3 className="section-title">Action hints</h3>
        {canCancel ? <div className="muted">Stop run: Requests a safe stop at the next stage boundary.</div> : null}
        {isCompleted ? (
          <div className="muted">
            Open Reveal: Opens the HTML slide deck generated for this run.
            {!hasRevealOutput ? " (Unavailable because no Reveal output was generated.)" : ""}
          </div>
        ) : (
          <div className="muted">Open Reveal: Available after the run completes and Reveal output exists.</div>
        )}
        {canRecoverA11 ? (
          <div className="muted">Recover from A11: Re-runs only the final audit/repair stage for this failed run.</div>
        ) : null}
        {canRetry ? (
          <div className="muted">Retry run: Starts a new run using the same source file and prior parameters.</div>
        ) : null}
      </div>

      <div className="panel stack">
        <h3 className="section-title">Warnings</h3>
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

      {actionMessage ? <div className="success">{actionMessage}</div> : null}

      {isCompleted && !hasRevealOutput ? <div className="muted">Reveal output was not generated for this run.</div> : null}

      {error ? <div className="error">{error}</div> : null}

      {isCompleted ? (
        <div className="top-links">
          <Link href={`/results/${runId}`}>View results</Link>
          <Link href={`/inspect/${runId}`}>Inspect run</Link>
        </div>
      ) : null}
    </div>
  );
}
