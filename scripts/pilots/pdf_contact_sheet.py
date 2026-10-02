"""Render a selected PDF page range as a labeled visual inspection sheet.

Optional pilot dependencies: PyMuPDF (fitz) and Pillow. The output is a derived
inspection image, not source evidence or a replacement for reading the PDF.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import fitz
from PIL import Image, ImageDraw


def make_contact_sheet(
    source: Path, output: Path, start_page: int, end_page: int, columns: int
) -> None:
    if start_page < 1 or end_page < start_page or columns < 1:
        raise ValueError("invalid page range or column count")
    cell_width, cell_height = 240, 340
    with fitz.open(source) as document:
        if end_page > len(document):
            raise ValueError(f"end_page exceeds PDF page count ({len(document)})")
        count = end_page - start_page + 1
        rows = (count + columns - 1) // columns
        sheet = Image.new("RGB", (cell_width * columns, cell_height * rows), "white")
        draw = ImageDraw.Draw(sheet)
        for position, page_number in enumerate(range(start_page, end_page + 1)):
            page = document[page_number - 1]
            pixels = page.get_pixmap(
                matrix=fitz.Matrix(0.6, 0.6), colorspace=fitz.csRGB, alpha=False
            )
            thumbnail = Image.frombytes(
                "RGB", (pixels.width, pixels.height), pixels.samples
            )
            thumbnail.thumbnail((cell_width - 12, cell_height - 34))
            x = (position % columns) * cell_width + (cell_width - thumbnail.width) // 2
            y = (position // columns) * cell_height + 24
            sheet.paste(thumbnail, (x, y))
            draw.text((x, y - 18), f"PDF page {page_number}", fill="black")
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("start_page", type=int)
    parser.add_argument("end_page", type=int)
    parser.add_argument("--columns", type=int, default=4)
    args = parser.parse_args()
    make_contact_sheet(
        args.source, args.output, args.start_page, args.end_page, args.columns
    )


if __name__ == "__main__":
    main()
