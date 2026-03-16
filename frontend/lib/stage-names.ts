const STAGE_NAMES: Record<string, string> = {
  A0: "Intake and Job Spec",
  A1: "Paper Parsing",
  A2: "Section Analysis",
  A3: "Artifact Extraction",
  A4: "Reference Retrieval",
  A5: "Reference Summarization",
  A6: "Presentation Planning",
  A7: "Speaker Notes",
  A8: "Visual Generation",
  A9: "Reveal Build",
  A10: "PPTX Build",
  A11: "Audit and Repair",
};

export function getStageName(stageId: string): string {
  return STAGE_NAMES[stageId] || "Unknown stage";
}

export function formatStageLabel(stageId: string): string {
  const stageName = getStageName(stageId);
  return stageName === "Unknown stage" ? stageId : `${stageId} - ${stageName}`;
}
