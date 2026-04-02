"""Container adapters for the OrbitBrief parser runtime."""

from .base import BaseAdapter
from .docx import DocxAdapter, parse_docx
from .email_export import EmailExportAdapter, parse_email_export
from .md import MarkdownAdapter, parse_markdown
from .pdf_ocr import PdfOcrAdapter, parse_pdf_ocr
from .pdf_text import PdfTextAdapter, parse_pdf_text
from .txt import TxtAdapter, parse_txt

ADAPTER_REGISTRY = {
    "txt": TxtAdapter,
    "md": MarkdownAdapter,
    "docx": DocxAdapter,
    "email_export": EmailExportAdapter,
    "pdf_text": PdfTextAdapter,
    "pdf_ocr": PdfOcrAdapter,
}

__all__ = [
    "ADAPTER_REGISTRY",
    "BaseAdapter",
    "TxtAdapter",
    "MarkdownAdapter",
    "DocxAdapter",
    "EmailExportAdapter",
    "PdfTextAdapter",
    "PdfOcrAdapter",
    "parse_txt",
    "parse_markdown",
    "parse_docx",
    "parse_email_export",
    "parse_pdf_text",
    "parse_pdf_ocr",
]
