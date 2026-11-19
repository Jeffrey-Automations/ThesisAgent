"""Metadata from flattened PDF front matter (``progress.md`` #32).

pypdf often returns a whole first page as one line. The strings below are
the start of what it returned for three arXiv papers (2209.15001,
2309.01692, and an energy-gated attention preprint), where the abstract
came back empty, co-authors were lost, and one title was not found, plus the
synthetic page where an abstract fragment became an author.
"""

from __future__ import annotations

import pytest

from thesisagents.intelligence.pdf_metadata import extract_metadata

HASSANI = (
    "Dilated Neighborhood Attention Transformer Ali Hassani1, Humphrey Shi1,2 "
    "1SHI Lab @ U of Oregon & UIUC, 2Picsart AI Research (PAIR) NA / DiNA (dilation = 1) "
    "Figure 1. An illustration of a single pixel's attention span. "
    "Abstract Transformers are quickly becoming one of the most heavily applied deep "
    "learning architectures across modalities, domains, and tasks. 1. Introduction More text."
)
LAI = (
    "Mask-Attention-Free Transformer for 3D Instance Segmentation Xin Lai1 Yuhui Yuan3 "
    "Ruihang Chu1 Yukang Chen1 Han Hu3 Jiaya Jia1,2* 1The Chinese University of Hong Kong "
    "2SmartMore 3Microsoft Research Asia Abstract Recently, transformer-based methods have "
    "dominated 3D instance segmentation, where mask attention is commonly involved. "
    "1. Introduction More text."
)
ZERIS = (
    "Energy-Gated Attention and Wavelet Positional Encoding: Complementary Inductive Biases "
    "for Transformer Attention Athanasios Zeris iD 0009-0002-6907-2400∗ Abstract Standard "
    "transformer attention computes pairwise token similarity but treats all tokens as "
    "equally salient. 1 Introduction More text."
)
SYNTHETIC = (
    "Sparse Attention for Long Documents Ada Lovelace, Alan Turing Abstract We study "
    "sparse attention for long documents and show it scales."
)


@pytest.mark.parametrize(
    ("text", "title", "authors", "abstract_start"),
    [
        (HASSANI, "Dilated Neighborhood Attention Transformer",
         ("Ali Hassani", "Humphrey Shi"), "Transformers are quickly becoming"),
        (LAI, "Mask-Attention-Free Transformer for 3D Instance Segmentation",
         ("Xin Lai", "Yuhui Yuan", "Ruihang Chu", "Yukang Chen", "Han Hu", "Jiaya Jia"),
         "Recently, transformer-based methods"),
        (ZERIS, "Energy-Gated Attention and Wavelet Positional Encoding: Complementary "
         "Inductive Biases for Transformer Attention", ("Athanasios Zeris",),
         "Standard transformer attention"),
        (SYNTHETIC, "Sparse Attention for Long Documents", ("Ada Lovelace", "Alan Turing"),
         "We study sparse attention"),
    ],
    ids=["hassani", "lai", "zeris", "synthetic"],
)
def test_flattened_front_matter(text, title, authors, abstract_start):
    meta = extract_metadata(text)
    assert meta.title == title
    assert meta.authors == authors
    assert (meta.abstract or "").startswith(abstract_start)


def test_a_title_starting_abstract_is_not_taken_for_the_abstract():
    """'Abstract Interpretation …' is Title Case, not prose, so it is no anchor."""
    text = (
        "Abstract Interpretation for Neural Network Verification At Scale Ada Lovelace1, "
        "Alan Turing2 1University of Somewhere Abstract We verify neural networks with "
        "abstract interpretation and show that it scales to large models in practice."
    )
    meta = extract_metadata(text)
    assert meta.title == "Abstract Interpretation for Neural Network Verification At Scale"
    assert (meta.abstract or "").startswith("We verify neural networks")


def test_a_caption_starting_abstract_is_not_taken_for_the_abstract():
    text = (
        "Ranking Mobile Apps by Review Signals Ada Lovelace1 1University of Somewhere "
        "Figure 1. Abstract Apps Store Rankings Over Time For Ten Popular Categories In Asia "
        "And Europe Shown Here"
    )
    assert extract_metadata(text).abstract is None
