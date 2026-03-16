---
title: Paper2Slides Project Handoff (2026-03-16)
description: Ready-to-paste context for starting a new chat without losing project state
author: GitHub Copilot
ms.date: 2026-03-16
ms.topic: reference
keywords:
  - paper2slides
  - handoff
  - workflow
  - retrieval
estimated_reading_time: 6
---

## Copy-Paste Starter for a New Chat

```text
Project: paper2slides
Goal: Convert an academic paper PDF into faithful presentation outputs (Reveal + PPTX) with citations and safety audit.

Current focus:
1) Improve reference retrieval recall while keeping strict grounding (retrieved means local PDF exists).
2) Keep citation policy conservative and source-grounded.
3) Preserve UI control for max_slides_per_reference.

Most recent validated result:
- Same-paper comparison improved retrieval from 24/42 to 29/42 after deterministic recovery + broader provider search/retries.

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

1. Real workflow execution (Azure OpenAI mode) runs end-to-end.
2. Reference retrieval hardening has been implemented and tested.
3. Reference integrity policy is active:
- A reference marked retrieved must have a verifiable local PDF artifact.
- Otherwise it is downgraded to not_found.
4. Deterministic post-A4 recovery is active:
- Unresolved references are retried with provider-based PDF retrieval.
- Successful downloads are promoted to retrieved.
5. Broader retrieval search is active:
- Higher arXiv/OpenAlex attempts and candidate breadth.
- OpenAlex fetch now retries with longer timeout.
6. Targeted retrieval integrity tests pass:
- backend/tests/test_workflow_reference_integrity.py -> 14 passed.

## Most Recent Measured Impact

Same source paper comparison:
- Baseline run: backend/runs/safety-1706-03762v7_20260314_001226
  - total 42
  - retrieved 24
  - not_found 18
- Latest run: backend/runs/safety-1706-03762v7_20260316_154445
  - total 42
  - retrieved 29
  - not_found 13

Delta:
- retrieved +5
- not_found -5

## Recent Changes of Interest

Backend:
- backend/app/orchestrator/workflow.py
  - Added deterministic recovery pass after A4 coverage guard.
  - Increased provider search breadth constants.
  - Added OpenAlex retrying fetch behavior.
- backend/tests/test_workflow_reference_integrity.py
  - Added tests for deterministic recovery success/failure paths.

Frontend:
- frontend/components/job-form.tsx
- frontend/lib/api.ts

Note:
- Workspace currently contains many other modified/untracked files not all related to retrieval work.

## Known Issues / Risks

1. PPTX build can fail in some runs due missing template package path:
- python-pptx template error reported in latest run warnings.
2. Bibliography parsing quality is still a bottleneck on messy references sections.
3. Coverage guard can synthesize missing entries when A4 batch output is incomplete; this preserves coverage but quality still depends on downstream retrieval success.

## Pending / Suggested Next Steps

1. Fix PPTX template/runtime issue so A10 is consistently healthy.
2. Improve bibliography detection and split heuristics for difficult references pages.
3. Add one metrics summary artifact per run (precision/recall-oriented retrieval telemetry).
4. Optional: run the same benchmark paper multiple times to check stability and variance of retrieval counts.

## Useful Commands

Run full workflow from repo root:

```powershell
Push-Location backend; & "C:/Users/ricastro/OneDrive - Microsoft/paper2slides/.venv/Scripts/python.exe" -m app.orchestrator.workflow --pdf "runs/safety-1706-03762v7_20260314_001226/source_paper/1706.03762v7.pdf"; Pop-Location
```

Run targeted retrieval tests:

```powershell
Set-Location backend; & "C:/Users/ricastro/OneDrive - Microsoft/paper2slides/.venv/Scripts/python.exe" -m pytest tests/test_workflow_reference_integrity.py -q
```

## Definition of Done for the Next Chat

A good next checkpoint should include:
1. Stable retrieval improvement confirmed on at least one benchmark run.
2. PPTX stage passing without template failures.
3. Clear report of total references, retrieved, not_found, and why unresolved references remain.
