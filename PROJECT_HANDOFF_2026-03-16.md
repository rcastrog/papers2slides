---
title: Paper2Slides Project Handoff (2026-03-18)
description: Ready-to-paste context for starting a new chat without losing project state
author: GitHub Copilot
ms.date: 2026-03-18
ms.topic: reference
keywords:
  - paper2slides
  - handoff
  - workflow
  - retrieval
  - audit
  - ui
estimated_reading_time: 7
---

## Copy-Paste Starter for a New Chat

```text
Project: paper2slides
Goal: Convert an academic paper PDF into faithful presentation outputs (Reveal + PPTX) with citations and safety audit.

Current focus:
1) Keep citation policy strict and prevent post-repair citation loss.
2) Improve run-status usability (clear warning explanation, repetitive-content summary, quick output actions).
3) Continue retrieval reliability work while preserving strict grounding (retrieved means local PDF exists).

Latest shipped commit on main:
- 4075c6e16ecaf6380b77eaae5b88b77406ad9b9d

Please continue from PROJECT_HANDOFF_2026-03-16.md and prioritize unresolved items.
```

## Project Objective

paper2slides is a multi-agent pipeline that transforms a source paper into presentation artifacts.

End-to-end stages run through A0-A11:
- Intake and parse
- Section and artifact analysis
- Reference retrieval and reference summaries
- Presentation planning, notes, visuals
- Reveal/PPTX rendering
- Final audit and optional repairs

Primary quality principle:
- Fidelity over fluency. Avoid unsupported claims and keep traceable evidence.

## Current Architecture Snapshot

Key backend folders:
- backend/app/orchestrator: workflow and stage orchestration
- backend/app/agents: stage agents (A0-A11 and repair agents)
- backend/app/services: parser, retrieval helpers, LLM client, file and utility services
- backend/app/renderers: Reveal and PPTX renderers
- backend/app/models: Pydantic contracts
- backend/tests: integrity and workflow tests

Key frontend folders:
- frontend/components: job form UI
- frontend/lib: API client wiring

## What Is Working

1. Real workflow execution (Azure OpenAI mode) runs end to end.
2. Retrieval hardening remains in place and preserves strict retrieved/not_found semantics.
3. Repair-on-audit now defaults to enabled across UI and backend defaults.
4. Citation repair logic now adds or preserves reference_paper citations on citation_issue slides.
5. Run Status now shows:
   - AI-style warning summary
   - Repetitiveness summary
   - Open Deck action in addition to Open Reveal
6. Frontend build and targeted backend audit tests pass after recent changes.

## Most Recent Measured Impact

Retrieval baseline remains useful for benchmarking:

- Baseline run: backend/runs/safety-1706-03762v7_20260314_001226
  - total 42
  - retrieved 24
  - not_found 18
- Improved run: backend/runs/safety-1706-03762v7_20260316_154445
  - total 42
  - retrieved 29
  - not_found 13

Delta remains:

- retrieved +5
- not_found -5

## Recent Changes of Interest

Backend:

- backend/app/orchestrator/workflow.py
  - Citation repair now enforces reference_paper insertion on citation_issue slides.
  - Added text-pattern extraction for author/year mentions when repairing citations.
  - Default repair_on_audit is now true in workflow entry points and CLI default.
- backend/app/api/routes/jobs.py
  - Multipart and workflow-launch defaults now assume repair_on_audit=true when omitted.
- backend/app/api/routes/runs.py
  - Retry fallback now defaults repair_on_audit to true when missing from metadata.
- backend/app/api/schemas.py
  - JobSubmissionRequest default repair_on_audit set to true.
- backend/tests/test_workflow_audit_guard.py
  - Added regression test for citation repair insertion behavior.

Frontend:

- frontend/components/job-form.tsx
  - Run repair-on-audit checkbox default set to on.
- frontend/components/run-status.tsx
  - Added warnings explanation summary.
  - Added repetitiveness summary from repetition metrics.
  - Moved action controls and action hints to bottom.
  - Added Open Deck button.
- frontend/lib/api.ts
  - Existing wiring reused for repetition metrics and run status data.

Git status note:

- Latest feature commit has been pushed to main: 4075c6e.
- Some local untracked files may still exist in workspace depending on machine state.

## Known Issues / Risks

1. Citation guard failures can still appear in difficult runs if external-work mentions are generated without robust mapped reference support.
2. Bibliography parsing quality remains a bottleneck on messy references pages.
3. Coverage guard synthesis in A4 preserves reference IDs but does not guarantee retrievability.
4. Local development frequently hits port 8000 conflicts when launching backend.

## Pending / Suggested Next Steps

1. Validate citation-repair fix with a fresh end-to-end run on the previously problematic paper and verify A11 no longer fails for slide-level external-reference guard.
2. Add explicit telemetry artifact for citation guard outcomes before/after repair.
3. Improve bibliography parsing and split heuristics for difficult references sections.
4. Add a quick health command or script for freeing/diagnosing port 8000 during local development.

## Useful Commands

Run full workflow from repo root:

```powershell
Push-Location backend; & "C:/Users/ricastro/OneDrive - Microsoft/paper2slides/.venv/Scripts/python.exe" -m app.orchestrator.workflow --pdf "runs/safety-1706-03762v7_20260314_001226/source_paper/1706.03762v7.pdf"; Pop-Location
```

Run targeted retrieval tests:

```powershell
Set-Location backend; & "C:/Users/ricastro/OneDrive - Microsoft/paper2slides/.venv/Scripts/python.exe" -m pytest tests/test_workflow_reference_integrity.py -q
```

Run targeted citation/audit tests:

```powershell
Set-Location backend; & "C:/Users/ricastro/OneDrive - Microsoft/paper2slides/.venv/Scripts/python.exe" -m pytest tests/test_workflow_audit_guard.py -q
```

Build frontend:

```powershell
Set-Location frontend; npm run build
```

## Definition of Done for the Next Chat

A good next checkpoint should include:

1. One fresh benchmark run showing audit status completed or completed_with_warnings without high-severity citation guard failures.
2. Clear report of total references, retrieved, not_found, and reasons for unresolved references.
3. Confirmation that Run Status warning and repetitiveness summaries match artifact truth for that run.
