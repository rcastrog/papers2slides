"""Schema serialization tests for slide evidence DTOs."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.schemas import ClaimEvidence, SlideEvidence, SlideEvidenceResponse


class SlideEvidenceSchemasTests(unittest.TestCase):
    def test_slide_evidence_response_serializes_with_optional_fields(self) -> None:
        payload = SlideEvidenceResponse(
            run_id="run_20260319",
            run_status="completed",
            slides=[
                SlideEvidence(
                    slide_number=1,
                    slide_id="slide-1",
                    slide_title="Results",
                    claim_count=1,
                    no_evidence_claim_count=0,
                    confidence_flags=["medium confidence"],
                    quality_flags=["overall_support:supported"],
                    claims=[
                        ClaimEvidence(
                            claim_id="slide-1-claim-1",
                            claim_text="Model improves retrieval quality.",
                            confidence_flag="medium",
                            quality_flags=["overall_support:supported"],
                            citation_labels=["Smith, 2024"],
                            citation_links=["https://arxiv.org/abs/2401.00001"],
                            source_snippets=["Section 3 reports quality gains."],
                            support_ids=["section-3"],
                            no_evidence=False,
                        )
                    ],
                )
            ],
            warnings=[],
        )

        model_dump = payload.model_dump()
        self.assertEqual(model_dump["run_id"], "run_20260319")
        self.assertEqual(model_dump["slides"][0]["slide_id"], "slide-1")
        self.assertEqual(model_dump["slides"][0]["claims"][0]["confidence_flag"], "medium")
        self.assertFalse(model_dump["slides"][0]["claims"][0]["no_evidence"])


if __name__ == "__main__":
    unittest.main()
