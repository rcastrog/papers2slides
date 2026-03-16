"""Smoke test for SectionAnalysisAgent with mocked LLM output."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.agents.section_analysis_agent import SectionAnalysisAgent
from app.models.section_analysis import SectionAnalysisResult
from app.services.llm_client import LLMClient
from app.services.prompt_loader import PromptLoader


class FakeTransport:
    """Returns deterministic A2 JSON payload for smoke testing."""

    def complete(self, system_prompt: str, input_payload: dict, model: str | None = None) -> str:
        _ = (system_prompt, input_payload, model)
        payload = {
            "section_id": "S02",
            "section_title": "Method",
            "section_role": ["method_explanation"],
            "summary": "Describes the method pipeline.",
            "key_claims": [
                {
                    "claim": "The method improves robustness.",
                    "support_level_within_section": "moderate",
                    "notes": "Supported by the design rationale.",
                }
            ],
            "important_details": ["Includes three processing stages."],
            "concepts_needing_explanation": [
                {
                    "concept": "latent bottleneck",
                    "reason": "jargon",
                    "importance": "medium",
                }
            ],
            "evidence_or_arguments": [
                {
                    "type": "reasoning",
                    "description": "Explains why each stage is needed.",
                }
            ],
            "limitations_or_cautions": ["Ablation details are in another section."],
            "candidate_visualizable_ideas": [
                {
                    "idea": "Three-stage processing diagram",
                    "visual_type_hint": "process_diagram",
                    "source_support": "direct",
                }
            ],
            "presentation_relevance": {
                "importance_for_final_deck": "high",
                "why_it_matters": "Core technical contribution.",
                "likely_slide_use": ["main_content"],
            },
            "uncertainty_flags": [],
            "confidence": "high",
        }
        return json.dumps(payload)


class FakeTransportNonCanonicalRoles:
    """Returns deterministic A2 JSON payload using role label aliases."""

    def complete(self, system_prompt: str, input_payload: dict, model: str | None = None) -> str:
        _ = (system_prompt, input_payload, model)
        payload = {
            "section_id": "S04",
            "section_title": "Results",
            "section_role": [
                "experiment/result interpretation",
                "limitations/discussion",
                "conclusion/takeaways",
            ],
            "summary": "Interprets experiments and outlines caveats.",
            "key_claims": [
                {
                    "claim": "The approach improves accuracy.",
                    "support_level_within_section": "strong",
                    "notes": "Backed by benchmark results.",
                }
            ],
            "important_details": ["Two benchmark datasets are reported."],
            "concepts_needing_explanation": [
                {
                    "concept": "calibration error",
                    "reason": "jargon",
                    "importance": "medium",
                }
            ],
            "evidence_or_arguments": [
                {
                    "type": "experiment",
                    "description": "Compares against baselines.",
                }
            ],
            "limitations_or_cautions": ["Small sample size for one task."],
            "candidate_visualizable_ideas": [
                {
                    "idea": "Baseline comparison chart",
                    "visual_type_hint": "comparison_table",
                    "source_support": "direct",
                }
            ],
            "presentation_relevance": {
                "importance_for_final_deck": "high",
                "why_it_matters": "Contains the headline outcomes.",
                "likely_slide_use": ["main_content"],
            },
            "uncertainty_flags": [],
            "confidence": "high",
        }
        return json.dumps(payload)


class FakeTransportAdministrativeRole:
    """Returns deterministic A2 JSON payload with administrative role label."""

    def complete(self, system_prompt: str, input_payload: dict, model: str | None = None) -> str:
        _ = (system_prompt, input_payload, model)
        payload = {
            "section_id": "S00",
            "section_title": "Front Matter",
            "section_role": ["administrative"],
            "summary": "Contains metadata and framing context.",
            "key_claims": [
                {
                    "claim": "No scientific claim is introduced.",
                    "support_level_within_section": "moderate",
                    "notes": "Acts as opening context.",
                }
            ],
            "important_details": ["Includes publication metadata."],
            "concepts_needing_explanation": [],
            "evidence_or_arguments": [],
            "limitations_or_cautions": [],
            "candidate_visualizable_ideas": [],
            "presentation_relevance": {
                "importance_for_final_deck": "low",
                "why_it_matters": "Helps orient the audience.",
                "likely_slide_use": ["supporting_context"],
            },
            "uncertainty_flags": [],
            "confidence": "high",
        }
        return json.dumps(payload)


class FakeTransportEmptyLikelySlideUse:
    """Returns deterministic A2 payload with empty likely_slide_use list."""

    def complete(self, system_prompt: str, input_payload: dict, model: str | None = None) -> str:
        _ = (system_prompt, input_payload, model)
        payload = {
            "section_id": "S05",
            "section_title": "Appendix",
            "section_role": ["framing_background"],
            "summary": "Contains supporting details.",
            "key_claims": [
                {
                    "claim": "Details are supplementary.",
                    "support_level_within_section": "weak",
                    "notes": "Not central to the deck narrative.",
                }
            ],
            "important_details": [],
            "concepts_needing_explanation": [],
            "evidence_or_arguments": [],
            "limitations_or_cautions": [],
            "candidate_visualizable_ideas": [],
            "presentation_relevance": {
                "importance_for_final_deck": "low",
                "why_it_matters": "Can support Q&A.",
                "likely_slide_use": [],
            },
            "uncertainty_flags": [],
            "confidence": "high",
        }
        return json.dumps(payload)


class FakeTransportEmptySectionRole:
    """Returns deterministic A2 payload with empty section_role list."""

    def complete(self, system_prompt: str, input_payload: dict, model: str | None = None) -> str:
        _ = (system_prompt, input_payload, model)
        payload = {
            "section_id": "S06",
            "section_title": "Supplement",
            "section_role": [],
            "summary": "Supplemental context section.",
            "key_claims": [
                {
                    "claim": "No standalone claim.",
                    "support_level_within_section": "weak",
                    "notes": "Contextual only.",
                }
            ],
            "important_details": [],
            "concepts_needing_explanation": [],
            "evidence_or_arguments": [],
            "limitations_or_cautions": [],
            "candidate_visualizable_ideas": [],
            "presentation_relevance": {
                "importance_for_final_deck": "low",
                "why_it_matters": "Optional context.",
                "likely_slide_use": ["supporting_context"],
            },
            "uncertainty_flags": [],
            "confidence": "medium",
        }
        return json.dumps(payload)


class FakeTransportVisualTypeHintAliases:
    """Returns deterministic A2 payload with non-canonical visual_type_hint labels."""

    def complete(self, system_prompt: str, input_payload: dict, model: str | None = None) -> str:
        _ = (system_prompt, input_payload, model)
        payload = {
            "section_id": "S07",
            "section_title": "Results",
            "section_role": ["experiment_result_interpretation"],
            "summary": "Contains chart-like findings.",
            "key_claims": [
                {
                    "claim": "The trend lines diverge after treatment.",
                    "support_level_within_section": "moderate",
                    "notes": "Backed by a figure in the section.",
                }
            ],
            "important_details": [],
            "concepts_needing_explanation": [],
            "evidence_or_arguments": [],
            "limitations_or_cautions": [],
            "candidate_visualizable_ideas": [
                {
                    "idea": "Summarize category deltas",
                    "visual_type_hint": "bar_chart",
                    "source_support": "direct",
                },
                {
                    "idea": "Show trend over time",
                    "visual_type_hint": "line_chart",
                    "source_support": "direct",
                },
            ],
            "presentation_relevance": {
                "importance_for_final_deck": "medium",
                "why_it_matters": "Provides visual summary options.",
                "likely_slide_use": ["main_content"],
            },
            "uncertainty_flags": [],
            "confidence": "medium",
        }
        return json.dumps(payload)


class FakeTransportEvidenceTypeAliases:
    """Returns deterministic A2 payload with non-canonical evidence type labels."""

    def complete(self, system_prompt: str, input_payload: dict, model: str | None = None) -> str:
        _ = (system_prompt, input_payload, model)
        payload = {
            "section_id": "S08",
            "section_title": "Method",
            "section_role": ["method_explanation"],
            "summary": "Method details with evidence descriptors.",
            "key_claims": [
                {
                    "claim": "The method pipeline is justified.",
                    "support_level_within_section": "moderate",
                    "notes": "Design rationale is provided.",
                }
            ],
            "important_details": [],
            "concepts_needing_explanation": [],
            "evidence_or_arguments": [
                {
                    "type": "visualization",
                    "description": "Describes the method step-by-step.",
                }
            ],
            "limitations_or_cautions": [],
            "candidate_visualizable_ideas": [
                {
                    "idea": "Unknown visual kind from model",
                    "visual_type_hint": "heatmap",
                    "source_support": "direct",
                }
            ],
            "presentation_relevance": {
                "importance_for_final_deck": "medium",
                "why_it_matters": "Clarifies implementation choices.",
                "likely_slide_use": ["main_content"],
            },
            "uncertainty_flags": [],
            "confidence": "medium",
        }
        return json.dumps(payload)


class SectionAnalysisAgentSmokeTest(unittest.TestCase):
    def test_run_returns_validated_section_analysis_result(self) -> None:
        llm_client = LLMClient(transport=FakeTransport())
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = SectionAnalysisAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        sample_input = {
            "section": {
                "section_id": "S02",
                "section_title": "Method",
                "text": "Method text...",
            }
        }

        result = agent.run(sample_input)

        self.assertIsInstance(result, SectionAnalysisResult)
        self.assertEqual(result.section_id, "S02")
        self.assertEqual(result.section_role, ["method_explanation"])

    def test_run_normalizes_section_role_aliases(self) -> None:
        llm_client = LLMClient(transport=FakeTransportNonCanonicalRoles())
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = SectionAnalysisAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        sample_input = {
            "section": {
                "section_id": "S04",
                "section_title": "Results",
                "text": "Results text...",
            }
        }

        result = agent.run(sample_input)

        self.assertEqual(
            result.section_role,
            [
                "experiment_result_interpretation",
                "limitations_discussion",
                "conclusion_takeaways",
            ],
        )

    def test_run_normalizes_administrative_section_role(self) -> None:
        llm_client = LLMClient(transport=FakeTransportAdministrativeRole())
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = SectionAnalysisAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        sample_input = {
            "section": {
                "section_id": "S00",
                "section_title": "Front Matter",
                "text": "Front matter text...",
            }
        }

        result = agent.run(sample_input)

        self.assertEqual(result.section_role, ["framing_background"])

    def test_run_normalizes_empty_likely_slide_use(self) -> None:
        llm_client = LLMClient(transport=FakeTransportEmptyLikelySlideUse())
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = SectionAnalysisAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        sample_input = {
            "section": {
                "section_id": "S05",
                "section_title": "Appendix",
                "text": "Appendix text...",
            }
        }

        result = agent.run(sample_input)

        self.assertEqual(result.presentation_relevance.likely_slide_use, ["supporting_context"])

    def test_run_normalizes_empty_section_role(self) -> None:
        llm_client = LLMClient(transport=FakeTransportEmptySectionRole())
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = SectionAnalysisAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        sample_input = {
            "section": {
                "section_id": "S06",
                "section_title": "Supplement",
                "text": "Supplement text...",
            }
        }

        result = agent.run(sample_input)

        self.assertEqual(result.section_role, ["framing_background"])

    def test_run_normalizes_visual_type_hint_aliases(self) -> None:
        llm_client = LLMClient(transport=FakeTransportVisualTypeHintAliases())
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = SectionAnalysisAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        sample_input = {
            "section": {
                "section_id": "S07",
                "section_title": "Results",
                "text": "Results text...",
            }
        }

        result = agent.run(sample_input)

        self.assertEqual(result.candidate_visualizable_ideas[0].visual_type_hint, "other")
        self.assertEqual(result.candidate_visualizable_ideas[1].visual_type_hint, "other")

    def test_run_normalizes_evidence_type_aliases(self) -> None:
        llm_client = LLMClient(transport=FakeTransportEvidenceTypeAliases())
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = SectionAnalysisAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        sample_input = {
            "section": {
                "section_id": "S08",
                "section_title": "Method",
                "text": "Method text...",
            }
        }

        result = agent.run(sample_input)

        self.assertEqual(result.evidence_or_arguments[0].type, "other")
        self.assertEqual(result.candidate_visualizable_ideas[0].visual_type_hint, "other")


if __name__ == "__main__":
    unittest.main()
