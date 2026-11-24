"""Build a small, valid one-page PDF resume, with no extra libraries."""


def _escape(text):
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def resume_pdf(name, headline, lines):
    """A one-page A4 PDF with a name, a headline and a few lines of text.

    Only plain ASCII text in the built-in Helvetica font. The cross-reference
    table holds the real byte offset of each object, so PDF readers open it
    without having to repair it.
    """
    text = [f"BT /F1 20 Tf 72 770 Td ({_escape(name)}) Tj ET"]
    text.append(f"BT /F1 12 Tf 72 745 Td ({_escape(headline)}) Tj ET")
    y = 710
    for line in lines:
        text.append(f"BT /F1 11 Tf 72 {y} Td ({_escape(line)}) Tj ET")
        y -= 18
    stream = "\n".join(text).encode("ascii")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
    ]

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref_at = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\n" % (len(objects) + 1)
    out += b"startxref\n%d\n%%%%EOF\n" % xref_at
    return bytes(out)
