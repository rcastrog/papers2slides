"""Tests for conceptual visual SVG materialization quality guards."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.utils.conceptual_visual_factory import render_conceptual_svg


class ConceptualVisualFactoryTests(unittest.TestCase):
    def test_concept_map_avoids_double_escaped_entities_and_verbose_clauses(self) -> None:
        generated = SimpleNamespace(
            visual_id="GV01",
            visual_kind="concept_map",
            slide_title="Why Study AI's Labor Market Impacts?",
            visual_purpose="Illustrate AI's labor market context.",
            visual_spec=SimpleNamespace(
                main_elements=[
                    "Central node: 'AI's Labor Market Impacts'",
                    "Branch 1: 'Theoretical Capabilities' with sub-nodes like 'Task Automation Potential'",
                    "Branch 2: 'Real-World Applications' with sub-nodes like 'Observed Usage'",
                ],
                labels_or_text=[
                    "Central node: 'AI's Labor Market Impacts'",
                    "Branch 1: 'Theoretical Capabilities'",
                    "Branch 2: 'Real-World Applications'",
                    "Sub-nodes: 'Task Automation Potential', 'Observed Usage', 'Workforce Trends'",
                ],
            ),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            target = render_conceptual_svg(generated=generated, assets_dir=Path(tmpdir))
            svg = target.read_text(encoding="utf-8")

        self.assertIn("AI&#x27;s Labor Market Impacts", svg)
        self.assertNotIn("&amp;#x27;", svg)
        self.assertNotIn("with sub-nodes", svg)


if __name__ == "__main__":
    unittest.main()
