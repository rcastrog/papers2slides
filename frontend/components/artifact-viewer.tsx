import type { ArtifactPayloadResponse } from "../lib/api";

type ArtifactViewerProps = {
  payload: ArtifactPayloadResponse | null;
  error: string | null;
  filterText: string;
};

export function ArtifactViewer({ payload, error, filterText }: ArtifactViewerProps) {
  if (error) {
    return <div className="error">{error}</div>;
  }

  if (!payload) {
    return <div className="muted">Select an artifact to inspect.</div>;
  }

  if (payload.content_kind === "binary") {
    return <div>Binary artifact. Use the download endpoint for this file.</div>;
  }

  const body = payload.content_kind === "json" ? JSON.stringify(payload.content, null, 2) : String(payload.content ?? "");
  const normalizedFilter = filterText.trim().toLowerCase();
  const filteredBody =
    normalizedFilter.length === 0
      ? body
      : body
          .split("\n")
          .filter((line) => line.toLowerCase().includes(normalizedFilter))
          .join("\n");
  const emptyAfterFilter = normalizedFilter.length > 0 && filteredBody.trim().length === 0;

  return (
    <div className="stack">
      <div className="muted">
        <strong>{payload.artifact_key}</strong>
        <div style={{ fontSize: 12 }}>{payload.relative_path}</div>
      </div>
      <pre
        style={{
          overflowX: "auto",
          maxHeight: 500,
        }}
      >
        {emptyAfterFilter ? "No lines matched the current filter." : filteredBody}
      </pre>
    </div>
  );
}
