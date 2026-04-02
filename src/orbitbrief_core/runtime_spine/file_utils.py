from __future__ import annotations

from io import BytesIO


def _pdf_obj(num: int, body: str) -> bytes:
    return f"{num} 0 obj\n{body}\nendobj\n".encode("latin-1")


def synthetic_minimal_pdf(text: str) -> bytes:
    """Return a tiny but valid single-page PDF containing visible text.

    This is used by tests/smoke paths that need a syntactically valid PDF without
    depending on an external renderer.
    """
    safe = (
        text.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .replace("\r", " ")
        .replace("\n", " ")
    )[:500]
    stream = f"BT /F1 12 Tf 36 100 Td ({safe}) Tj ET"
    objects: list[bytes] = []
    objects.append(_pdf_obj(1, "<< /Type /Catalog /Pages 2 0 R >>"))
    objects.append(_pdf_obj(2, "<< /Type /Pages /Kids [3 0 R] /Count 1 >>"))
    objects.append(
        _pdf_obj(
            3,
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 144] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        )
    )
    objects.append(_pdf_obj(4, f"<< /Length {len(stream.encode('latin-1'))} >>\nstream\n{stream}\nendstream"))
    objects.append(_pdf_obj(5, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"))

    buf = BytesIO()
    buf.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for obj in objects:
        offsets.append(buf.tell())
        buf.write(obj)
    xref_start = buf.tell()
    buf.write(f"xref\n0 {len(offsets)}\n".encode("latin-1"))
    buf.write(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        buf.write(f"{off:010d} 00000 n \n".encode("latin-1"))
    buf.write(
        (
            f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
            f"startxref\n{xref_start}\n%%EOF\n"
        ).encode("latin-1")
    )
    return buf.getvalue()
