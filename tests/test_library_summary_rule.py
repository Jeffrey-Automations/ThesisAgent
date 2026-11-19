"""Which summary a library keeps when a paper is added again (``progress.md`` #15).

The rule (``library/store.py::_with_better_summary``): by tier none < flat <
rich, an incoming summary replaces the stored one when it is at least as rich,
never when it is poorer, and a paper added without a summary changes nothing.
"""

from __future__ import annotations

from dataclasses import replace

from thesisagents.core.models import Paper, PaperCollection, PaperSummary, Query
from thesisagents.library import Library

PAPER = Paper(
    source="arxiv", source_id="1706.03762", title="Attention Is All You Need",
    authors=("Ashish Vaswani",), year=2017, venue=None, abstract="Transformers.",
    url="https://arxiv.org/abs/1706.03762", doi="10.48550/arXiv.1706.03762",
)
FLAT = PaperSummary(language="en", motivation=("Recurrence is slow.",), model="flat")
RICH = PaperSummary(language="en", research_question="Can attention replace recurrence?",
                    model="rich")
RICHER_LATER = PaperSummary(language="en", research_question="Does self-attention suffice?",
                            model="rich-2")


def _stored_summary(library: Library) -> PaperSummary | None:
    (paper,) = library.collection().papers
    return paper.summary


def _add(library: Library, summary: PaperSummary | None, source: str = "arxiv") -> None:
    paper = replace(PAPER, summary=summary, source=source)
    library.add_collection(PaperCollection(Query("attention", (source,)), (paper,)))


def test_a_rich_summary_replaces_a_flat_one(tmp_path):
    with Library(tmp_path / "lib.db") as library:
        _add(library, FLAT)
        _add(library, RICH)
        assert _stored_summary(library) == RICH


def test_a_flat_summary_never_replaces_a_rich_one(tmp_path):
    with Library(tmp_path / "lib.db") as library:
        _add(library, RICH)
        _add(library, FLAT)
        assert _stored_summary(library) == RICH


def test_a_newer_summary_of_the_same_tier_wins(tmp_path):
    with Library(tmp_path / "lib.db") as library:
        _add(library, RICH)
        _add(library, RICHER_LATER)
        assert _stored_summary(library) == RICHER_LATER


def test_a_plain_search_result_keeps_the_stored_summary(tmp_path):
    with Library(tmp_path / "lib.db") as library:
        _add(library, RICH)
        _add(library, None)
        assert _stored_summary(library) == RICH


def test_a_summary_from_another_source_is_credited(tmp_path):
    with Library(tmp_path / "lib.db") as library:
        _add(library, FLAT)
        _add(library, RICH, source="openalex")
        (paper,) = library.collection().papers
        assert paper.summary == RICH
        credited = [p for p in paper.provenance if p.field == "summary"]
        assert [(p.source, p.source_id) for p in credited] == [("openalex", "1706.03762")]
