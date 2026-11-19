"""``--pdf`` mode: turn local PDF files into the papers of a run.

No search and no download happens in this mode. The work is done by
:func:`thesisagents.core.local_pdf.build_local_collection`, which the GUI
also calls; this module only maps the CLI flags onto it (``--pdf`` names
the file or folder, ``--title`` / ``--authors`` / ``--year`` / ``--venue`` /
``--doi`` / ``--arxiv-id`` override the PDF's own metadata). Kept out of
``cli.py`` so that module stays about the order of the stages.
"""

from __future__ import annotations

import argparse

from thesisagents.core.exceptions import ThesisAgentsError
from thesisagents.core.local_pdf import (
    LocalPdfOverrides,
    build_local_collection,
    resolve_pdf_inputs,
)
from thesisagents.core.models import PaperCollection


def build_from_local_pdf(args: argparse.Namespace) -> PaperCollection:
    """Build the run's collection from ``args.pdf`` (one ``.pdf`` or a folder).

    The override flags apply only when exactly one PDF is read, see
    :class:`~thesisagents.core.local_pdf.LocalPdfOverrides`. The PDFs are
    copied into ``{args.out}/pdfs/``.
    """
    pdf_paths = resolve_pdf_inputs(args.pdf)
    if not pdf_paths:
        raise ThesisAgentsError(f"--pdf found no PDFs at {args.pdf!r}")
    overrides = LocalPdfOverrides(
        title=getattr(args, "title", None),
        authors=getattr(args, "authors", None),
        year=getattr(args, "year", None),
        venue=getattr(args, "venue", None),
        doi=getattr(args, "doi", None),
        arxiv_id=getattr(args, "arxiv_id", None),
    )
    return build_local_collection(pdf_paths, args.out, overrides)
