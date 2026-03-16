import type { StageInspection } from "../lib/api";
import { formatStageLabel } from "../lib/stage-names";

type StageListProps = {
  stages: StageInspection[];
  selectedStage: string | null;
  onSelectStage: (stageId: string) => void;
};

export function StageList({ stages, selectedStage, onSelectStage }: StageListProps) {
  if (stages.length === 0) {
    return <div className="muted">No stage metadata is available yet.</div>;
  }

  return (
    <div className="stack">
      {stages.map((stage) => {
        const isActive = selectedStage === stage.stage;
        const statusColor = stage.status === "failed" ? "#f87171" : stage.status === "completed" ? "#4ade80" : "#67e8f9";

        return (
          <button
            key={stage.stage}
            onClick={() => onSelectStage(stage.stage)}
            style={{
              textAlign: "left",
              border: `1px solid ${isActive ? "rgba(45, 212, 191, 0.9)" : "rgba(148, 163, 184, 0.3)"}`,
              borderRadius: 12,
              background: isActive
                ? "linear-gradient(150deg, rgba(18, 43, 67, 0.95), rgba(12, 33, 52, 0.92))"
                : "linear-gradient(150deg, rgba(15, 24, 41, 0.93), rgba(10, 18, 31, 0.88))",
              padding: 11,
              cursor: "pointer",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
              <strong>{formatStageLabel(stage.stage)}</strong>
              <span style={{ color: statusColor }}>{stage.status}</span>
            </div>
            <div className="muted" style={{ fontSize: 12 }}>
              {stage.duration_ms != null ? `${stage.duration_ms} ms` : "timing n/a"}
              {stage.fallback_used ? ` • fallback: ${stage.fallback_reason || "yes"}` : ""}
            </div>
          </button>
        );
      })}
    </div>
  );
}
