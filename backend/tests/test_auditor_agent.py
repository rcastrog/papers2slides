"""Smoke test for AuditorAgent with mocked LLM output."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.agents.auditor_agent import AuditorAgent
from app.models.audit_report import AuditReport
from app.services.llm_client import LLMClient
from app.services.prompt_loader import PromptLoader


class FakeTransport:
    def complete(self, system_prompt: str, input_payload: dict, model: str | None = None) -> str:
        _ = (system_prompt, input_payload, model)
        return json.dumps(
            {
                "audit_status": "completed_with_warnings",
                "deck_risk_level": "medium",
                "slide_audits": [
                    {
                        "slide_number": 1,
                        "slide_title": "Intro",
                        "overall_support": "weakly_supported",
                        "findings": [
                            {
                                "severity": "high",
                                "category": "unsupported_claim",
                                "description": "Unsupported statement.",
                                "evidence_basis": [
                                    {
                                        "source_type": "presentation_plan",
                                        "source_id": "s1",
                                        "note": "Needs citation",
                                    }
                                ],
                                "recommended_fix": "Simplify claim",
                            }
                        ],
                        "required_action": "revise_slide",
                    }
                ],
                "deck_level_findings": [],
                "repair_priority": [{"priority_order": 1, "slide_number": 1, "reason": "Fix high risk"}],
                "global_warnings": [],
            }
        )


class FakeTransportDeckAlias:
    def complete(self, system_prompt: str, input_payload: dict, model: str | None = None) -> str:
        _ = (system_prompt, input_payload, model)
        return json.dumps(
            {
                "audit_status": "completed_with_warnings",
                "deck_risk_level": "medium",
                "slide_audits": [],
                "deck_level_findings": [
                    {
                        "severity": "medium",
                        "category": "generated_visual_overreach",
                        "description": "Visual provenance is weak.",
                        "recommended_fix": "Clarify conceptual provenance.",
                    }
                ],
                "repair_priority": [],
                "global_warnings": [],
            }
        )


class FakeTransportArtifactFidelityAlias:
    def complete(self, system_prompt: str, input_payload: dict, model: str | None = None) -> str:
        _ = (system_prompt, input_payload, model)
        return json.dumps(
            {
                "audit_status": "completed_with_warnings",
                "deck_risk_level": "medium",
                "slide_audits": [],
                "deck_level_findings": [
                    {
                        "severity": "medium",
                        "category": "artifact_fidelity",
                        "description": "Source artifact readability is limited.",
                        "recommended_fix": "Add clarifying caption.",
                    }
                ],
                "repair_priority": [],
                "global_warnings": [],
            }
        )


class FakeTransportEvidenceSourceAlias:
    def complete(self, system_prompt: str, input_payload: dict, model: str | None = None) -> str:
        _ = (system_prompt, input_payload, model)
        return json.dumps(
            {
                "audit_status": "completed_with_warnings",
                "deck_risk_level": "medium",
                "slide_audits": [
                    {
                        "slide_number": 1,
                        "slide_title": "Intro",
                        "overall_support": "weakly_supported",
                        "findings": [
                            {
                                "severity": "medium",
                                "category": "generated_visual_overreach",
                                "description": "Visual overstates certainty.",
                                "evidence_basis": [
                                    {
                                        "source_type": "generated_visual",
                                        "source_id": "GV01",
                                        "note": "Needs provenance label",
                                    }
                                ],
                                "recommended_fix": "Mark conceptual",
                            }
                        ],
                        "required_action": "revise_visual",
                    }
                ],
                "deck_level_findings": [],
                "repair_priority": [],
                "global_warnings": [],
            }
        )


class FakeTransportGlobalWarningObject:
    def complete(self, system_prompt: str, input_payload: dict, model: str | None = None) -> str:
        _ = (system_prompt, input_payload, model)
        return json.dumps(
            {
                "audit_status": "completed_with_warnings",
                "deck_risk_level": "medium",
                "slide_audits": [],
                "deck_level_findings": [],
                "repair_priority": [],
                "global_warnings": [
                    {
                        "severity": "medium",
                        "description": "PPTX build failed in this attempt.",
                    }
                ],
            }
        )


class AuditorAgentSmokeTest(unittest.TestCase):
    def test_run_returns_validated_audit_report(self) -> None:
        llm_client = LLMClient(transport=FakeTransport())
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = AuditorAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        result = agent.run({"presentation_plan": {"slides": []}})

        self.assertIsInstance(result, AuditReport)
        self.assertEqual(result.deck_risk_level, "medium")

    def test_run_normalizes_deck_level_category_alias(self) -> None:
        llm_client = LLMClient(transport=FakeTransportDeckAlias())
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = AuditorAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        result = agent.run({"presentation_plan": {"slides": []}})

        self.assertEqual(result.deck_level_findings[0].category, "provenance_consistency")

    def test_run_normalizes_artifact_fidelity_category_alias(self) -> None:
        llm_client = LLMClient(transport=FakeTransportArtifactFidelityAlias())
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = AuditorAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        result = agent.run({"presentation_plan": {"slides": []}})

        self.assertEqual(result.deck_level_findings[0].category, "provenance_consistency")

    def test_run_normalizes_evidence_source_type_alias(self) -> None:
        llm_client = LLMClient(transport=FakeTransportEvidenceSourceAlias())
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = AuditorAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        result = agent.run({"presentation_plan": {"slides": []}})

        source_type = result.slide_audits[0].findings[0].evidence_basis[0].source_type
        self.assertEqual(source_type, "render_output")

    def test_run_normalizes_global_warning_objects(self) -> None:
        llm_client = LLMClient(transport=FakeTransportGlobalWarningObject())
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = AuditorAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        result = agent.run({"presentation_plan": {"slides": []}})

        self.assertEqual(result.global_warnings[0], "[medium] PPTX build failed in this attempt.")


if __name__ == "__main__":
    unittest.main()
