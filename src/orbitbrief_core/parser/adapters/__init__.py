"""Container adapters for the OrbitBrief parser runtime."""

from .base import BaseAdapter
from .cad_image import CadImageAdapter, parse_cad_image
from .cad_pdf import CadPdfAdapter, parse_cad_pdf
from .docx import DocxAdapter, parse_docx
from .email_export import EmailExportAdapter, parse_email_export
from .md import MarkdownAdapter, parse_markdown
from .pdf_ocr import PdfOcrAdapter, parse_pdf_ocr
from .pdf_text import PdfTextAdapter, parse_pdf_text
from .site_schematic_image import SiteSchematicImageAdapter, parse_site_schematic_image
from .site_schematic_pdf import SiteSchematicPdfAdapter, parse_site_schematic_pdf
from .spreadsheet import SpreadsheetAdapter
from .txt import TxtAdapter, parse_txt

ADAPTER_REGISTRY = {
    "txt": TxtAdapter,
    "cad_sheet": CadPdfAdapter,
    "schematic": CadImageAdapter,
    "floorplan": CadImageAdapter,
    "drawing_packet": CadPdfAdapter,
    "site_schematic_pdf": SiteSchematicPdfAdapter,
    "site_schematic_image": SiteSchematicImageAdapter,
    "md": MarkdownAdapter,
    "docx": DocxAdapter,
    "email_export": EmailExportAdapter,
    "pdf_text": PdfTextAdapter,
    "pdf_ocr": PdfOcrAdapter,
    "xlsx": SpreadsheetAdapter,
    "csv": SpreadsheetAdapter,
}

__all__ = [
    "ADAPTER_REGISTRY",
    "BaseAdapter",
    "TxtAdapter",
    "CadPdfAdapter",
    "CadImageAdapter",
    "MarkdownAdapter",
    "DocxAdapter",
    "EmailExportAdapter",
    "PdfTextAdapter",
    "PdfOcrAdapter",
    "SiteSchematicPdfAdapter",
    "SiteSchematicImageAdapter",
    "SpreadsheetAdapter",
    "parse_txt",
    "parse_cad_pdf",
    "parse_cad_image",
    "parse_markdown",
    "parse_docx",
    "parse_email_export",
    "parse_pdf_text",
    "parse_pdf_ocr",
    "parse_site_schematic_pdf",
    "parse_site_schematic_image",
]
