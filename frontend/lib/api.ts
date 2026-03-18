const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

export type SubmitJobInput = {
  pdfFile?: File;
  sourceUrl?: string;
  presentationStyle: string;
  audience: string;
  language: string;
  outputFormats: string[];
  repairOnAudit: boolean;
  advancedOptions?: {
    target_slide_count?: number;
    target_duration_minutes?: number;
    max_reference_citations_per_slide?: number;
    max_slides_per_reference?: number;
    llm_temperature?: number;
    deterministic_mode?: boolean;
    image_gen_enabled?: boolean;
    image_gen_max_images_per_run?: number;
    visual_policy?: string;
  };
};

export type JobSubmissionResponse = {
  run_id: string;
  status: string;
  status_url: string;
  results_url: string;
};

export type RunStatusResponse = {
  run_id: string;
  source_pdf_name?: string | null;
  status: string;
  current_stage: string;
  completed_stages: string[];
  warnings: string[];
  stage_warnings?: Array<{
    stage: string;
    warnings: string[];
  }>;
  warning_count: number;
  key_artifact_paths: Record<string, string>;
  checkpoint_state: Record<string, unknown>;
  audit_findings_count?: number | null;
  stage_count: number;
  fallback_stage_count: number;
  total_duration_ms?: number | null;
  job_summary?: Record<string, unknown>;
  retrieval_summary?: {
    total_references?: number;
    retrieved_count?: number;
    ambiguous_count?: number;
    not_found_count?: number;
    retrieved_requires_local_pdf?: boolean;
    grounding_note?: string;
  };
};

export type RunActionResponse = {
  run_id: string;
  status: string;
  message?: string;
  audit_report_path?: string;
  deck_risk_level?: string;
  unresolved_high_severity_findings_count?: number;
};

export type RunResultsResponse = {
  run_id: string;
  reveal_path?: string | null;
  pptx_path?: string | null;
  notes_path?: string | null;
  audit_report_path?: string | null;
  final_risk_summary: Record<string, unknown>;
  asset_usage_summary?: {
    extracted_assets_count?: number;
    asset_map_resolved?: number;
    asset_map_total?: number;
    slides_using_real_source_figures?: number;
  };
  repetition_metrics?: {
    semantic_similarity_thresholds?: {
      bullet?: number;
      slide?: number;
      citation_reason?: number;
    };
    bullet?: RepetitionLevelSummary;
    slide?: RepetitionLevelSummary;
    citation?: CitationRepetitionSummary;
  };
};

export type RepetitionExample = {
  text_a: string;
  text_b: string;
  similarity: number;
};

export type RepetitionCountItem = {
  text: string;
  count: number;
};

export type RepetitionLevelSummary = {
  total?: number;
  unique_exact?: number;
  exact_unique_ratio?: number;
  exact_repeated_instances?: number;
  near_duplicate_pair_count?: number;
  near_duplicate_cluster_count?: number;
  max_near_duplicate_similarity?: number;
  top_exact_repeats?: RepetitionCountItem[];
  near_duplicate_examples?: RepetitionExample[];
};

export type CitationRepetitionSummary = {
  total_mentions?: number;
  unique_labels_exact?: number;
  exact_unique_label_ratio?: number;
  exact_label_repeated_instances?: number;
  top_repeated_labels?: RepetitionCountItem[];
  reason_near_duplicate_pair_count?: number;
  reason_near_duplicate_cluster_count?: number;
  max_reason_similarity?: number;
  reason_near_duplicate_examples?: RepetitionExample[];
};

export type StageInspection = {
  stage: string;
  status: string;
  started_at?: string | null;
  finished_at?: string | null;
  duration_ms?: number | null;
  input_artifacts: string[];
  output_artifacts: string[];
  warnings: string[];
  fallback_used: boolean;
  fallback_reason?: string | null;
};

export type RunInspectionResponse = {
  run_id: string;
  status: string;
  current_stage: string;
  llm_mode?: string | null;
  llm_mode_reason?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  duration_ms?: number | null;
  warning_count: number;
  error_count: number;
  completed_stages: string[];
  stages: StageInspection[];
  quality_signals: Record<string, unknown>;
  artifacts: Record<string, string>;
  extracted_assets_summary?: Record<string, unknown>;
  asset_map_summary?: Record<string, unknown>;
  warnings: string[];
  errors: string[];
};

export type RunAssetEntry = {
  asset_id: string;
  relative_path: string;
  page_number: number | null;
  extraction_method: string;
  width: number | null;
  height: number | null;
  notes: string[];
  download_url?: string | null;
};

export type RunAssetsResponse = {
  run_id: string;
  assets: RunAssetEntry[];
  warnings: string[];
  count: number;
};

export type VisualResolutionRow = {
  slide_number: number;
  slide_title: string;
  requested_asset_id: string;
  source_origin: string;
  resolved_path: string | null;
  fallback_used: boolean;
  provenance_note: string;
};

export type AssetMapEntryResponse = {
  artifact_id: string;
  page_numbers: number[];
  candidate_asset_ids: string[];
  selected_asset_id: string | null;
  resolved_path: string | null;
  resolution_status: "resolved" | "unresolved" | "ambiguous";
  confidence: string;
  decision_reason: string;
  warnings: string[];
  matching_signals: Record<string, unknown>;
};

export type AssetMapResponse = {
  run_id: string;
  entries: AssetMapEntryResponse[];
  warnings: string[];
  entry_count: number;
  resolved_count: number;
  unresolved_count: number;
  ambiguous_count: number;
  visual_resolution: VisualResolutionRow[];
};

export type ArtifactPayloadResponse = {
  artifact_key: string;
  relative_path: string;
  content_kind: "json" | "text" | "binary";
  content: unknown;
};

export async function submitJob(input: SubmitJobInput): Promise<JobSubmissionResponse> {
  const formData = new FormData();
  if (input.pdfFile) {
    formData.append("pdf_file", input.pdfFile);
  }
  if (input.sourceUrl) {
    formData.append("source_url", input.sourceUrl);
  }
  formData.append("presentation_style", input.presentationStyle);
  formData.append("audience", input.audience);
  formData.append("language", input.language);
  formData.append("output_formats", input.outputFormats.join(","));
  formData.append("repair_on_audit", String(input.repairOnAudit));
  if (input.advancedOptions) {
    formData.append("advanced_options", JSON.stringify(input.advancedOptions));
  }

  const response = await fetch(`${API_BASE_URL}/jobs`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`submitJob failed (${response.status}): ${text}`);
  }

  return (await response.json()) as JobSubmissionResponse;
}

export async function getRunStatus(runId: string): Promise<RunStatusResponse> {
  const response = await fetch(`${API_BASE_URL}/runs/${runId}`, { cache: "no-store" });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`getRunStatus failed (${response.status}): ${text}`);
  }
  return (await response.json()) as RunStatusResponse;
}

export async function getRunResults(runId: string): Promise<RunResultsResponse> {
  const response = await fetch(`${API_BASE_URL}/runs/${runId}/results`, { cache: "no-store" });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`getRunResults failed (${response.status}): ${text}`);
  }
  return (await response.json()) as RunResultsResponse;
}

export async function getRunInspection(runId: string): Promise<RunInspectionResponse> {
  const response = await fetch(`${API_BASE_URL}/runs/${runId}/inspect`, { cache: "no-store" });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`getRunInspection failed (${response.status}): ${text}`);
  }
  return (await response.json()) as RunInspectionResponse;
}

export async function getArtifactPayload(runId: string, artifactKey: string): Promise<ArtifactPayloadResponse> {
  const response = await fetch(`${API_BASE_URL}/runs/${runId}/artifacts/${artifactKey}`, { cache: "no-store" });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`getArtifactPayload failed (${response.status}): ${text}`);
  }
  return (await response.json()) as ArtifactPayloadResponse;
}

export async function getRunAssets(runId: string): Promise<RunAssetsResponse> {
  const response = await fetch(`${API_BASE_URL}/runs/${runId}/assets`, { cache: "no-store" });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`getRunAssets failed (${response.status}): ${text}`);
  }
  return (await response.json()) as RunAssetsResponse;
}

export async function getRunAssetMap(runId: string): Promise<AssetMapResponse> {
  const response = await fetch(`${API_BASE_URL}/runs/${runId}/asset-map`, { cache: "no-store" });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`getRunAssetMap failed (${response.status}): ${text}`);
  }
  return (await response.json()) as AssetMapResponse;
}

export async function cancelRun(runId: string): Promise<RunActionResponse> {
  const response = await fetch(`${API_BASE_URL}/runs/${runId}/cancel`, { method: "POST" });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`cancelRun failed (${response.status}): ${text}`);
  }
  return (await response.json()) as RunActionResponse;
}

export async function recoverRunA11(runId: string): Promise<RunActionResponse> {
  const response = await fetch(`${API_BASE_URL}/runs/${runId}/recover-a11`, { method: "POST" });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`recoverRunA11 failed (${response.status}): ${text}`);
  }
  return (await response.json()) as RunActionResponse;
}

export async function retryRun(runId: string): Promise<JobSubmissionResponse> {
  const response = await fetch(`${API_BASE_URL}/runs/${runId}/retry`, { method: "POST" });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`retryRun failed (${response.status}): ${text}`);
  }
  return (await response.json()) as JobSubmissionResponse;
}
