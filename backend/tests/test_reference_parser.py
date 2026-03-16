"""Regression tests for bibliography extraction heuristics."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.reference_parser import ReferenceParser


class ReferenceParserTests(unittest.TestCase):
    def test_splits_unnumbered_wrapped_references(self) -> None:
        text = """
References
Acemoglu, Daron and Pascual Restrepo, "Robots and Jobs," Journal of Political Economy,
2020, 128 (6), 2188-2244.
Autor, David H, David Dorn, and Gordon H Hanson, "The China syndrome,"
American Economic Review, 2013, 103 (6), 2121-2168.
""".strip()

        parser = ReferenceParser()
        result = parser.extract_references(text)

        self.assertEqual(result.count, 2)
        self.assertTrue(any("line-based bibliography heuristics" in warning for warning in result.warnings))
        self.assertIn("Acemoglu", result.references_raw[0])
        self.assertIn("Autor", result.references_raw[1])

    def test_splits_numbered_entries_even_when_each_chunk_contains_wrapped_lines(self) -> None:
        text = """
References
[1] Eloundou, Tyna, Sam Manning, Pamela Mishkin, and Daniel Rock,
"Gpts are gpts," arXiv preprint arXiv:2303.10130, 2023.
[2] Tomlinson, K., Jaffe, S., Wang, W., Counts, S., and Suri, S.,
"Working with AI," arXiv preprint arXiv:2507.07935, 2025.
""".strip()

        parser = ReferenceParser()
        result = parser.extract_references(text)

        self.assertEqual(result.count, 2)
        self.assertIn("2303.10130", result.references_raw[0])
        self.assertIn("2507.07935", result.references_raw[1])

    def test_does_not_split_numbered_entry_at_capitalized_continuation_line(self) -> None:
        text = """
References
[1] Kaiming He, Xiangyu Zhang, Shaoqing Ren, and Jian Sun. Deep residual learning for image recognition.
In Proceedings of the IEEE Conference on Computer Vision and Pattern
Recognition, pages 770-778, 2016.
[2] Alex Graves. Generating sequences with recurrent neural networks. arXiv preprint arXiv:1308.0850, 2013.
""".strip()

        parser = ReferenceParser()
        result = parser.extract_references(text)

        self.assertEqual(result.count, 2)
        self.assertIn("Recognition, pages 770-778, 2016", result.references_raw[0])

    def test_trims_attention_visualization_tail_after_references(self) -> None:
        text = """
References
[1] Foo Author. Great Paper. arXiv preprint arXiv:1234.56789, 2012.
[2] Bar Author. Better Paper. CoRR, abs/1409.0473, 2014.

Attention Visualizations
Figure 3: Example attention map
""".strip()

        parser = ReferenceParser()
        result = parser.extract_references(text)

        self.assertEqual(result.count, 2)
        self.assertFalse(any("Attention Visualizations" in item for item in result.references_raw))
        self.assertTrue(any("Trimmed non-reference appendix/visualization text" in warning for warning in result.warnings))


if __name__ == "__main__":
    unittest.main()
