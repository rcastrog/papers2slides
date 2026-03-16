"""Minimal arXiv client abstraction used by workflow reference retrieval."""

from __future__ import annotations

import re
import importlib
from typing import Any


_ARXIV_ID_PATTERN = re.compile(r"(?:arxiv:)?([0-9]{4}\.[0-9]{4,5}(?:v\d+)?)", re.IGNORECASE)


class ArxivClient:
	"""Small swappable API for arXiv lookup with conservative failure handling."""

	def __init__(self, *, num_retries: int = 1) -> None:
		self._arxiv_module: Any | None = None
		self._client: Any | None = None
		try:
			self._arxiv_module = importlib.import_module("arxiv")
			self._client = self._arxiv_module.Client(page_size=10, delay_seconds=0.5, num_retries=max(0, num_retries))
		except Exception:
			self._arxiv_module = None
			self._client = None

	def search(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
		"""Return candidate records for a title or free-text query."""
		cleaned_query = (query or "").strip()
		if not cleaned_query or self._client is None or self._arxiv_module is None:
			return []

		search = self._arxiv_module.Search(
			query=cleaned_query,
			max_results=max(1, min(int(max_results or 1), 10)),
			sort_by=self._arxiv_module.SortCriterion.Relevance,
		)

		try:
			return [self._to_record(result) for result in self._client.results(search)]
		except Exception:
			return []

	def get_by_id(self, arxiv_id: str) -> dict[str, Any] | None:
		"""Return one candidate record for a concrete arXiv identifier."""
		normalized_id = self.extract_arxiv_id(arxiv_id)
		if not normalized_id or self._client is None or self._arxiv_module is None:
			return None

		search = self._arxiv_module.Search(id_list=[normalized_id], max_results=1)
		try:
			for result in self._client.results(search):
				return self._to_record(result)
		except Exception:
			return None
		return None

	@staticmethod
	def extract_arxiv_id(text: str | None) -> str:
		"""Extract normalized arXiv identifier from free text or URL."""
		if not text:
			return ""
		match = _ARXIV_ID_PATTERN.search(str(text))
		if not match:
			return ""
		return match.group(1)

	def _to_record(self, result: Any) -> dict[str, Any]:
		entry_id = str(getattr(result, "entry_id", "") or "")
		extracted_id = self.extract_arxiv_id(entry_id)
		if not extracted_id:
			extracted_id = self.extract_arxiv_id(getattr(result, "pdf_url", ""))

		published = getattr(result, "published", None)
		year = str(getattr(published, "year", "")) if published is not None else ""

		return {
			"title": str(getattr(result, "title", "") or "").strip(),
			"authors": [str(getattr(author, "name", "")).strip() for author in getattr(result, "authors", []) if str(getattr(author, "name", "")).strip()],
			"year": year,
			"source": "arxiv",
			"url": entry_id,
			"pdf_url": str(getattr(result, "pdf_url", "") or ""),
			"arxiv_id": extracted_id,
		}
