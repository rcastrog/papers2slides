"use client";

import type { CSSProperties } from "react";

import type { AssetMapResponse } from "../lib/api";

type AssetMapPanelProps = {
  data: AssetMapResponse | null;
  error: string | null;
};

export function AssetMapPanel({ data, error }: AssetMapPanelProps) {
  if (error) {
    return <div className="error">{error}</div>;
  }

  if (!data) {
    return <div>Loading asset-map decisions...</div>;
  }

  return (
    <div className="stack">
      <div>
        Resolved: {data.resolved_count} / {data.entry_count} | Ambiguous: {data.ambiguous_count} | Unresolved: {data.unresolved_count}
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th style={cellHead}>Artifact</th>
              <th style={cellHead}>Status</th>
              <th style={cellHead}>Selected</th>
              <th style={cellHead}>Reason</th>
              <th style={cellHead}>Confidence</th>
            </tr>
          </thead>
          <tbody>
            {data.entries.map((entry) => (
              <tr key={entry.artifact_id}>
                <td style={cellBody}>{entry.artifact_id}</td>
                <td style={cellBody}>{entry.resolution_status}</td>
                <td style={cellBody}>{entry.selected_asset_id || "-"}</td>
                <td style={cellBody}>{entry.decision_reason || "-"}</td>
                <td style={cellBody}>{entry.confidence || "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div style={{ display: "grid", gap: 6 }}>
        <h4 style={{ margin: 0 }}>Planned visual resolution</h4>
        {data.visual_resolution.length === 0 ? (
          <div className="muted">No visual resolution records found.</div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th style={cellHead}>Slide</th>
                  <th style={cellHead}>Requested</th>
                  <th style={cellHead}>Source</th>
                  <th style={cellHead}>Resolved</th>
                  <th style={cellHead}>Fallback</th>
                </tr>
              </thead>
              <tbody>
                {data.visual_resolution.map((item) => (
                  <tr key={`${item.slide_number}-${item.requested_asset_id}`}>
                    <td style={cellBody}>{item.slide_number}</td>
                    <td style={cellBody}>{item.requested_asset_id}</td>
                    <td style={cellBody}>{item.source_origin}</td>
                    <td style={cellBody}>{item.resolved_path || "-"}</td>
                    <td style={cellBody}>{item.fallback_used ? "yes" : "no"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {data.warnings.length > 0 ? <div className="warning">Warnings: {data.warnings.join(" | ")}</div> : null}
    </div>
  );
}

const cellHead: CSSProperties = {
  textAlign: "left",
  padding: "8px 10px",
  borderBottom: "1px solid rgba(148, 163, 184, 0.28)",
  fontSize: 12,
  color: "#8eb2de",
};

const cellBody: CSSProperties = {
  padding: "8px 10px",
  borderBottom: "1px solid rgba(148, 163, 184, 0.14)",
  fontSize: 13,
  color: "#dce8ff",
};
