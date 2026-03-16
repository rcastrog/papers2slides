"use client";

import type { RunAssetsResponse } from "../lib/api";

type AssetBrowserProps = {
  runId: string;
  data: RunAssetsResponse | null;
  error: string | null;
};

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

export function AssetBrowser({ runId, data, error }: AssetBrowserProps) {
  if (error) {
    return <div className="error">{error}</div>;
  }

  if (!data) {
    return <div>Loading extracted assets...</div>;
  }

  if (data.assets.length === 0) {
    return <div className="muted">No extracted source assets found.</div>;
  }

  return (
    <div className="stack">
      <div>Extracted assets: {data.count}</div>
      <div style={{ display: "grid", gap: 8, gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
        {data.assets.map((asset) => {
          const previewUrl = asset.download_url ? `${API_BASE_URL}${asset.download_url}` : null;
          return (
            <article
              key={asset.asset_id}
              style={{
                border: "1px solid rgba(148, 163, 184, 0.28)",
                borderRadius: 12,
                padding: 10,
                display: "grid",
                gap: 6,
                background: "linear-gradient(160deg, rgba(20, 35, 61, 0.86), rgba(12, 22, 40, 0.88))",
              }}
            >
              <strong>{asset.asset_id}</strong>
              {previewUrl ? (
                <img
                  src={previewUrl}
                  alt={asset.asset_id}
                  style={{
                    width: "100%",
                    height: 140,
                    objectFit: "contain",
                    background: "rgba(5, 11, 21, 0.85)",
                    border: "1px solid rgba(148, 163, 184, 0.22)",
                    borderRadius: 8,
                  }}
                  onError={(event) => {
                    (event.currentTarget as HTMLImageElement).style.display = "none";
                  }}
                />
              ) : null}
              <div>Page: {asset.page_number ?? "n/a"}</div>
              <div>Method: {asset.extraction_method}</div>
              <div>
                Size: {asset.width ?? "?"} x {asset.height ?? "?"}
              </div>
              <div className="muted" style={{ fontSize: 12 }}>{asset.relative_path}</div>
              {asset.notes.length > 0 ? <div style={{ fontSize: 12 }}>Notes: {asset.notes.join(" | ")}</div> : null}
              {previewUrl ? (
                <a href={previewUrl} target="_blank" rel="noreferrer">
                  Open asset
                </a>
              ) : null}
            </article>
          );
        })}
      </div>
      {data.warnings.length > 0 ? <div className="warning">Warnings: {data.warnings.join(" | ")}</div> : null}
      <div className="muted" style={{ fontSize: 12 }}>Run: {runId}</div>
    </div>
  );
}
