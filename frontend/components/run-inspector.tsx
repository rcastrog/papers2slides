"use client";

import { useEffect, useMemo, useState } from "react";

import {
  getArtifactPayload,
  getRunAssetMap,
  getRunAssets,
  getRunInspection,
  type AssetMapResponse,
  type ArtifactPayloadResponse,
  type RunAssetsResponse,
  type RunInspectionResponse,
  type StageInspection,
} from "../lib/api";
import { formatStageLabel } from "../lib/stage-names";
import { AssetBrowser } from "./asset-browser";
import { AssetMapPanel } from "./asset-map-panel";
import { ArtifactViewer } from "./artifact-viewer";
import { StageList } from "./stage-list";

type RunInspectorProps = {
  runId: string;
};

export function RunInspector({ runId }: RunInspectorProps) {
  const [inspection, setInspection] = useState<RunInspectionResponse | null>(null);
  const [artifactPayload, setArtifactPayload] = useState<ArtifactPayloadResponse | null>(null);
  const [assetsData, setAssetsData] = useState<RunAssetsResponse | null>(null);
  const [assetMapData, setAssetMapData] = useState<AssetMapResponse | null>(null);
  const [selectedStage, setSelectedStage] = useState<string | null>(null);
  const [compareStageA, setCompareStageA] = useState<string>("");
  const [compareStageB, setCompareStageB] = useState<string>("");
  const [selectedArtifact, setSelectedArtifact] = useState<string>("");
  const [artifactFilterText, setArtifactFilterText] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [artifactError, setArtifactError] = useState<string | null>(null);
  const [assetsError, setAssetsError] = useState<string | null>(null);
  const [assetMapError, setAssetMapError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const payload = await getRunInspection(runId);
        const [loadedAssets, loadedAssetMap] = await Promise.all([getRunAssets(runId), getRunAssetMap(runId)]);
        if (cancelled) {
          return;
        }
        setInspection(payload);
        setAssetsData(loadedAssets);
        setAssetMapData(loadedAssetMap);
        setError(null);
        setAssetsError(null);
        setAssetMapError(null);

        if (payload.stages.length > 0) {
          setSelectedStage((current) => current || payload.stages[0].stage);
          setCompareStageA((current) => current || payload.stages[0].stage);
          setCompareStageB((current) => {
            if (current) {
              return current;
            }
            return payload.stages.length > 1 ? payload.stages[1].stage : payload.stages[0].stage;
          });
        }

        const keys = Object.keys(payload.artifacts);
        if (keys.length > 0) {
          setSelectedArtifact((current) => current || keys[0]);
        }
      } catch (loadError) {
        if (!cancelled) {
          const message = loadError instanceof Error ? loadError.message : "Failed to load run inspection";
          setError(message);
        }
      }
    }

    load();
    const timer = setInterval(load, 4000);

    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [runId]);

  useEffect(() => {
    let cancelled = false;

    async function loadArtifact() {
      if (!selectedArtifact) {
        setArtifactPayload(null);
        return;
      }

      try {
        const payload = await getArtifactPayload(runId, selectedArtifact);
        if (!cancelled) {
          setArtifactPayload(payload);
          setArtifactError(null);
        }
      } catch (loadError) {
        if (!cancelled) {
          const message = loadError instanceof Error ? loadError.message : "Failed to load artifact";
          setArtifactError(message);
        }
      }
    }

    loadArtifact();

    return () => {
      cancelled = true;
    };
  }, [runId, selectedArtifact]);

  const activeStage = useMemo<StageInspection | null>(() => {
    if (!inspection || !selectedStage) {
      return null;
    }
    return inspection.stages.find((item) => item.stage === selectedStage) || null;
  }, [inspection, selectedStage]);

  const compareStageAData = useMemo<StageInspection | null>(() => {
    if (!inspection || !compareStageA) {
      return null;
    }
    return inspection.stages.find((item) => item.stage === compareStageA) || null;
  }, [inspection, compareStageA]);

  const compareStageBData = useMemo<StageInspection | null>(() => {
    if (!inspection || !compareStageB) {
      return null;
    }
    return inspection.stages.find((item) => item.stage === compareStageB) || null;
  }, [inspection, compareStageB]);

  return (
    <div className="card" style={{ display: "grid", gap: 14 }}>
      <h2 style={{ margin: 0 }}>Run inspector</h2>

      {error ? <div className="error">{error}</div> : null}

      {!inspection ? <div className="muted">Loading inspection data...</div> : null}

      {inspection ? (
        <>
          <div className="status-grid">
            <div>Status: {inspection.status}</div>
            <div>Current stage: {formatStageLabel(inspection.current_stage)}</div>
            <div>Duration: {inspection.duration_ms != null ? `${inspection.duration_ms} ms` : "n/a"}</div>
            <div>Warnings / errors: {inspection.warning_count} / {inspection.error_count}</div>
            <div>Fallback stages: {String(inspection.quality_signals.fallback_stage_count ?? 0)}</div>
          </div>

          <div className="split-layout">
            <div className="stack">
              <h3 style={{ margin: 0 }}>Stages</h3>
              <StageList stages={inspection.stages} selectedStage={selectedStage} onSelectStage={setSelectedStage} />
            </div>

            <div className="stack">
              <h3 style={{ margin: 0 }}>Stage details</h3>
              {!activeStage ? (
                <div className="muted">Select a stage from the list.</div>
              ) : (
                <div className="status-grid">
                  <div>Started: {activeStage.started_at || "n/a"}</div>
                  <div>Finished: {activeStage.finished_at || "n/a"}</div>
                  <div>Inputs: {activeStage.input_artifacts.join(", ") || "none"}</div>
                  <div>Outputs: {activeStage.output_artifacts.join(", ") || "none"}</div>
                  <div>Warnings: {activeStage.warnings.join(" | ") || "none"}</div>
                </div>
              )}
            </div>
          </div>

          <div className="stack">
            <h3 style={{ margin: 0 }}>Stage comparison</h3>
            <div className="top-links">
              <label style={{ display: "grid", gap: 4 }}>
                <span>Stage A</span>
                <select value={compareStageA} onChange={(event) => setCompareStageA(event.target.value)}>
                  {inspection.stages.map((stage) => (
                    <option key={`a-${stage.stage}`} value={stage.stage}>
                      {formatStageLabel(stage.stage)}
                    </option>
                  ))}
                </select>
              </label>
              <label style={{ display: "grid", gap: 4 }}>
                <span>Stage B</span>
                <select value={compareStageB} onChange={(event) => setCompareStageB(event.target.value)}>
                  {inspection.stages.map((stage) => (
                    <option key={`b-${stage.stage}`} value={stage.stage}>
                      {formatStageLabel(stage.stage)}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <div className="two-up">
              <div className="panel">
                <h4 style={{ margin: "0 0 8px 0" }}>{compareStageAData?.stage ? formatStageLabel(compareStageAData.stage) : "n/a"}</h4>
                <div>Status: {compareStageAData?.status || "n/a"}</div>
                <div>Duration: {compareStageAData?.duration_ms != null ? `${compareStageAData.duration_ms} ms` : "n/a"}</div>
                <div>Fallback: {compareStageAData?.fallback_used ? compareStageAData.fallback_reason || "yes" : "no"}</div>
                <div>Inputs: {compareStageAData?.input_artifacts.join(", ") || "none"}</div>
                <div>Outputs: {compareStageAData?.output_artifacts.join(", ") || "none"}</div>
              </div>
              <div className="panel">
                <h4 style={{ margin: "0 0 8px 0" }}>{compareStageBData?.stage ? formatStageLabel(compareStageBData.stage) : "n/a"}</h4>
                <div>Status: {compareStageBData?.status || "n/a"}</div>
                <div>Duration: {compareStageBData?.duration_ms != null ? `${compareStageBData.duration_ms} ms` : "n/a"}</div>
                <div>Fallback: {compareStageBData?.fallback_used ? compareStageBData.fallback_reason || "yes" : "no"}</div>
                <div>Inputs: {compareStageBData?.input_artifacts.join(", ") || "none"}</div>
                <div>Outputs: {compareStageBData?.output_artifacts.join(", ") || "none"}</div>
              </div>
            </div>
          </div>

          <div className="stack">
            <h3 style={{ margin: 0 }}>Artifact browser</h3>
            <input
              value={artifactFilterText}
              onChange={(event) => setArtifactFilterText(event.target.value)}
              placeholder="Filter artifact lines (case-insensitive)"
            />
            <select value={selectedArtifact} onChange={(event) => setSelectedArtifact(event.target.value)}>
              {Object.keys(inspection.artifacts).map((key) => (
                <option key={key} value={key}>
                  {key} ({inspection.artifacts[key]})
                </option>
              ))}
            </select>
            <ArtifactViewer payload={artifactPayload} error={artifactError} filterText={artifactFilterText} />
          </div>

          <div className="stack">
            <h3 style={{ margin: 0 }}>Extracted assets</h3>
            <AssetBrowser runId={runId} data={assetsData} error={assetsError} />
          </div>

          <div className="stack">
            <h3 style={{ margin: 0 }}>Asset map</h3>
            <AssetMapPanel data={assetMapData} error={assetMapError} />
          </div>

          <div className="stack">
            <h3 style={{ margin: 0 }}>Quality signals</h3>
            <pre>
              {JSON.stringify(inspection.quality_signals, null, 2)}
            </pre>
          </div>
        </>
      ) : null}
    </div>
  );
}
