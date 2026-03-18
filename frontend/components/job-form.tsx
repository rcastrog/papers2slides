"use client";

import { useState } from "react";
import type { ChangeEvent, FormEvent } from "react";
import { useRouter } from "next/navigation";

import { submitJob } from "../lib/api";

export function JobForm() {
  const router = useRouter();
  const [pdfFile, setPdfFile] = useState<File | undefined>(undefined);
  const [sourceUrl, setSourceUrl] = useState("");
  const [presentationStyle, setPresentationStyle] = useState("journal_club");
  const [audience, setAudience] = useState("research_specialists");
  const [language, setLanguage] = useState("en");
  const [repairOnAudit, setRepairOnAudit] = useState(true);
  const [targetSlideCount, setTargetSlideCount] = useState(12);
  const [targetDurationMinutes, setTargetDurationMinutes] = useState(20);
  const [maxReferenceCitationsPerSlide, setMaxReferenceCitationsPerSlide] = useState(4);
  const [maxSlidesPerReference, setMaxSlidesPerReference] = useState(3);
  const [llmTemperature, setLlmTemperature] = useState(0);
  const [deterministicMode, setDeterministicMode] = useState(true);
  const [disableGeneratedImages, setDisableGeneratedImages] = useState(true);
  const [imageGenMaxImagesPerRun, setImageGenMaxImagesPerRun] = useState(3);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    const outputFormats: string[] = ["reveal", "pptx"];

    if (!pdfFile && !sourceUrl.trim()) {
      setError("Please provide either a PDF upload or a source URL.");
      return;
    }

    setIsSubmitting(true);
    try {
      const result = await submitJob({
        pdfFile,
        sourceUrl: sourceUrl.trim() || undefined,
        presentationStyle,
        audience,
        language,
        outputFormats,
        repairOnAudit,
        advancedOptions: {
          target_slide_count: targetSlideCount,
          target_duration_minutes: targetDurationMinutes,
          max_reference_citations_per_slide: maxReferenceCitationsPerSlide,
          max_slides_per_reference: maxSlidesPerReference,
          llm_temperature: llmTemperature,
          deterministic_mode: deterministicMode,
          image_gen_enabled: !disableGeneratedImages,
          image_gen_max_images_per_run: imageGenMaxImagesPerRun,
          visual_policy: "conservative",
        },
      });
      router.push(`/run/${result.run_id}`);
    } catch (submitError) {
      const message = submitError instanceof Error ? submitError.message : "Job submission failed";
      setError(message);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <form className="card form-grid job-shell" onSubmit={handleSubmit}>
      <div className="job-header">
        <h2 style={{ margin: 0 }}>Submit Paper Job</h2>
        <p className="muted" style={{ margin: 0 }}>Configure once, review on the right, then launch the run.</p>
      </div>

      <div className="job-layout">
        <div className="job-main stack">
          <section className="panel stack">
            <h3 className="section-title">Source and Profile</h3>
            <div className="field-grid">
              <label className="field field-span-2">
                <span className="field-label">PDF upload</span>
                <input
                  type="file"
                  accept="application/pdf"
                  onChange={(event: ChangeEvent<HTMLInputElement>) => setPdfFile(event.target.files?.[0] ?? undefined)}
                />
              </label>

              <label className="field field-span-2">
                <span className="field-label">Source URL (optional alternative)</span>
                <input
                  type="url"
                  value={sourceUrl}
                  onChange={(event: ChangeEvent<HTMLInputElement>) => setSourceUrl(event.target.value)}
                  placeholder="https://.../paper.pdf"
                />
              </label>

              <label className="field">
                <span className="field-label">Presentation style</span>
                <select
                  value={presentationStyle}
                  onChange={(event: ChangeEvent<HTMLSelectElement>) => setPresentationStyle(event.target.value)}
                >
                  <option value="journal_club">journal_club</option>
                  <option value="teaching">teaching</option>
                  <option value="executive_friendly">executive_friendly</option>
                  <option value="technical_summary">technical_summary</option>
                </select>
              </label>

              <label className="field">
                <span className="field-label">Audience</span>
                <select value={audience} onChange={(event: ChangeEvent<HTMLSelectElement>) => setAudience(event.target.value)}>
                  <option value="research_specialists">research_specialists</option>
                  <option value="technical_adjacent">technical_adjacent</option>
                  <option value="students">students</option>
                  <option value="executive_nontechnical">executive_nontechnical</option>
                </select>
              </label>

              <label className="field">
                <span className="field-label">Language</span>
                <select value={language} onChange={(event: ChangeEvent<HTMLSelectElement>) => setLanguage(event.target.value)}>
                  <option value="en">en</option>
                  <option value="es">es</option>
                </select>
              </label>

              <div className="field">
                <span className="field-label">Output formats</span>
                <div className="checkbox-group">
                  <div className="muted">Reveal and PPTX are always generated for each run.</div>
                </div>
              </div>
            </div>
          </section>

          <section className="panel stack">
            <h3 className="section-title">Run Controls</h3>
            <div className="field-grid">
              <label className="field">
                <span className="field-label">Target slide count</span>
                <input
                  type="number"
                  min={1}
                  max={40}
                  value={targetSlideCount}
                  onChange={(event: ChangeEvent<HTMLInputElement>) => setTargetSlideCount(Number(event.target.value) || 12)}
                />
              </label>

              <label className="field">
                <span className="field-label">Target duration (minutes)</span>
                <input
                  type="number"
                  min={5}
                  max={120}
                  value={targetDurationMinutes}
                  onChange={(event: ChangeEvent<HTMLInputElement>) => setTargetDurationMinutes(Number(event.target.value) || 20)}
                />
              </label>

              <label className="field">
                <span className="field-label">Max citations per slide</span>
                <input
                  type="number"
                  min={1}
                  max={8}
                  value={maxReferenceCitationsPerSlide}
                  onChange={(event: ChangeEvent<HTMLInputElement>) => setMaxReferenceCitationsPerSlide(Number(event.target.value) || 4)}
                />
              </label>

              <label className="field">
                <span className="field-label">Max slides per reference</span>
                <input
                  type="number"
                  min={1}
                  max={10}
                  value={maxSlidesPerReference}
                  onChange={(event: ChangeEvent<HTMLInputElement>) => setMaxSlidesPerReference(Number(event.target.value) || 3)}
                />
              </label>

              <label className="field">
                <span className="field-label">LLM temperature</span>
                <input
                  type="number"
                  min={0}
                  max={1}
                  step={0.1}
                  value={llmTemperature}
                  onChange={(event: ChangeEvent<HTMLInputElement>) => setLlmTemperature(Number(event.target.value) || 0)}
                />
              </label>
            </div>

            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={repairOnAudit}
                onChange={(event: ChangeEvent<HTMLInputElement>) => setRepairOnAudit(event.target.checked)}
              /> Run repair-on-audit
            </label>

            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={deterministicMode}
                onChange={(event: ChangeEvent<HTMLInputElement>) => setDeterministicMode(event.target.checked)}
              /> Prefer deterministic run behavior
            </label>
          </section>
        </div>

        <aside className="job-side stack">
          <section className="panel stack">
            <h3 className="section-title">Image Policy</h3>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={disableGeneratedImages}
                onChange={(event: ChangeEvent<HTMLInputElement>) => setDisableGeneratedImages(event.target.checked)}
              /> Disable generated images (use only source-paper extracted artifacts)
            </label>

            <div className="field-grid">
              <label className="field">
                <span className="field-label">Generated image cap per run</span>
                <input
                  type="number"
                  min={0}
                  max={8}
                  value={imageGenMaxImagesPerRun}
                  disabled={disableGeneratedImages}
                  onChange={(event: ChangeEvent<HTMLInputElement>) => setImageGenMaxImagesPerRun(Number(event.target.value) || 0)}
                />
              </label>
            </div>
          </section>

          <section className="panel stack summary-panel">
            <h3 className="section-title">Run Summary</h3>
            <div className="summary-grid">
              <div className="summary-row"><span>Slides</span><strong>{targetSlideCount}</strong></div>
              <div className="summary-row"><span>Duration</span><strong>{targetDurationMinutes} min</strong></div>
              <div className="summary-row"><span>Audience</span><strong>{audience}</strong></div>
              <div className="summary-row"><span>Language</span><strong>{language}</strong></div>
              <div className="summary-row"><span>Formats</span><strong>Reveal, PPTX</strong></div>
              <div className="summary-row"><span>Image mode</span><strong>{disableGeneratedImages ? "Source-only" : "Mixed"}</strong></div>
            </div>

            {error ? <div className="error">{error}</div> : null}

            <button type="submit" disabled={isSubmitting} className="btn-primary">
              {isSubmitting ? "Submitting..." : "Start job"}
            </button>
          </section>
        </aside>
      </div>
    </form>
  );
}
