---
title: paper2slides
description: Multi-agent pipeline that converts academic papers into grounded Reveal and PPTX presentations with audit and repair.
ms.date: 2026-03-18
ms.topic: overview
---

## Overview

paper2slides converts a source paper PDF into presentation outputs while prioritizing grounding, citation fidelity, and auditability.

Primary outputs:

* Reveal deck
* PPTX deck
* Structured audit artifacts
* Run/status artifacts for inspection and retry

## Pipeline

Workflow stages run sequentially from A0 to A11:

* A0 Intake
* A1 Parse
* A2 Section analysis
* A3 Artifact extraction
* A4 Reference retrieval
* A5 Reference summary
* A6 Presentation planning
* A7 Speaker notes
* A8 Visual generation planning
* A9 Reveal render
* A10 PPTX build
* A11 Audit and optional repair cycle

## Current Focus Areas

* Keep citation policy strict and prevent post-repair citation loss
* Improve run-status usability and warning explainability
* Improve retrieval reliability while preserving strict grounding semantics

Strict grounding rule:

* A reference is counted as retrieved only when a local PDF artifact exists and is verified in the run.

## Latest Implemented Improvements

### Citation integrity

* Post-repair reference-paper citations are now canonicalized to retrieved reference labels when robust author/year token evidence exists.
* Non-retrieved reference citations and reference-summary supports are still removed before render.
* External-reference citation guard behavior remains strict.

### Run-status usability

* Run status now includes retrieval summary (total, retrieved, not_found, ambiguous) and grounding note.
* Warning panel includes clearer actionable explanations.
* Repetition panel now surfaces top repeated content examples in addition to counts.
* Quick output actions are grouped in a dedicated section.

### Retrieval reliability in deterministic mode

* Fixed deterministic mock sequencing drift by aligning fake responses with parser-selected A2 section windows.
* Disabled A4 batched retrieval only in mocked mode to preserve deterministic response ordering.
* Real-mode batching remains unchanged.

## Validation Snapshot

Recent focused validation passed:

* backend tests for citation guard and reference integrity
* backend run routes tests
* frontend production build

Deterministic benchmark run:

* Run ID: safety-1706-03762v7_20260318_164505
* Status: completed_with_warnings
* Audit: completed_with_warnings
* Unresolved high-severity findings: 0
* Citation guard high-severity findings: 0
* Retrieval summary: total 42, retrieved 25, not_found 17, ambiguous 0

## Run Commands

From repository root:

```powershell
Push-Location backend; & "../.venv/Scripts/python.exe" -m app.orchestrator.workflow --pdf "runs/safety-1706-03762v7_20260314_001226/source_paper/1706.03762v7.pdf"; Pop-Location
```

Deterministic mode run:

```powershell
Push-Location backend; $env:USE_MOCK_LLM='true'; & "../.venv/Scripts/python.exe" -m app.orchestrator.workflow --pdf "runs/safety-1706-03762v7_20260314_001226/source_paper/1706.03762v7.pdf"; Pop-Location
```

Frontend build:

```powershell
Set-Location frontend; if (Test-Path .next) { Remove-Item -Recurse -Force .next }; npm run build
```
