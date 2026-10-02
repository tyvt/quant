"""Screen for visually repeated PDF pages without treating similarity as version proof.

Optional pilot dependencies: PyMuPDF (fitz) and Pillow. This prints read-only
diagnostics; it does not alter either source document or publish a snapshot.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path

import fitz
import PIL
from PIL import Image, ImageChops, ImageStat


def _render_fingerprint(page: fitz.Page) -> Image.Image:
    pixels = page.get_pixmap(
        matrix=fitz.Matrix(0.75, 0.75), colorspace=fitz.csGRAY, alpha=False
    )
    image = Image.frombytes("L", (pixels.width, pixels.height), pixels.samples)
    return image.resize((128, 128), Image.Resampling.LANCZOS)


def _distance(left: Image.Image, right: Image.Image) -> float:
    return ImageStat.Stat(ImageChops.difference(left, right)).mean[0] / 255.0


def compare(original_path: Path, candidate_path: Path, threshold: float) -> dict:
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("threshold must be finite and between 0 and 1")
    original_raw = original_path.read_bytes()
    candidate_raw = candidate_path.read_bytes()
    with fitz.open(stream=original_raw, filetype="pdf") as original, fitz.open(
        stream=candidate_raw, filetype="pdf"
    ) as candidate:
        if not len(original) or not len(candidate):
            raise ValueError("cannot compare empty PDFs")
        original_images = [_render_fingerprint(page) for page in original]
        candidate_images = [_render_fingerprint(page) for page in candidate]
        original_texts = [page.get_text() for page in original]
        candidate_texts = [page.get_text() for page in candidate]

    matches = []
    close_candidate_pages = set()
    for index, original_image in enumerate(original_images):
        ranked = sorted(
            (
                (_distance(original_image, candidate_image), candidate_index)
                for candidate_index, candidate_image in enumerate(candidate_images)
            ),
            key=lambda item: (item[0], item[1]),
        )
        best_score, best_index = ranked[0]
        second_score = ranked[1][0] if len(ranked) > 1 else None
        passing_pages = sorted(
            candidate_index + 1 for score, candidate_index in ranked if score <= threshold
        )
        close_candidate_pages.update(passing_pages)
        same_index_distance = (
            _distance(original_image, candidate_images[index])
            if index < len(candidate_images) else None
        )
        original_numbers = re.findall(r"[+-]?\d[\d,]*(?:\.\d+)?", original_texts[index])
        candidate_numbers = (
            re.findall(r"[+-]?\d[\d,]*(?:\.\d+)?", candidate_texts[index])
            if index < len(candidate_texts) else []
        )
        matches.append(
            {
                "original_page": index + 1,
                "candidate_page": best_index + 1,
                "distance": round(best_score, 6),
                "second_distance": round(second_score, 6) if second_score is not None else None,
                "passes_threshold": best_score <= threshold,
                "close_candidate_pages": passing_pages,
                "ambiguous_close_match": len(passing_pages) > 1,
                "same_index_distance": (
                    round(same_index_distance, 6) if same_index_distance is not None else None
                ),
                "same_index_passes_threshold": (
                    same_index_distance <= threshold if same_index_distance is not None else None
                ),
                "original_extractable_text_characters": len(original_texts[index].strip()),
                "same_index_candidate_extractable_text_characters": (
                    len(candidate_texts[index].strip()) if index < len(candidate_texts) else None
                ),
                "same_index_extracted_numbers_equal": (
                    original_numbers == candidate_numbers
                    if original_numbers and candidate_numbers else None
                ),
            }
        )

    # Decisions use unrounded scores; six-decimal display must not promote a miss.
    close_matches = [match for match in matches if match["passes_threshold"]]
    same_index_matches = [match for match in matches if match["same_index_distance"] is not None]
    return {
        "original_path": str(original_path),
        "candidate_path": str(candidate_path),
        "original_sha256": hashlib.sha256(original_raw).hexdigest(),
        "candidate_sha256": hashlib.sha256(candidate_raw).hexdigest(),
        "tool_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "dependencies": {"pymupdf": fitz.VersionBind, "pillow": PIL.__version__},
        "original_pages": len(original_images),
        "candidate_pages": len(candidate_images),
        "rendering": "grayscale at 0.75x, resized to 128x128; mean absolute pixel difference / 255",
        "threshold": threshold,
        "threshold_kind": "empirical_screening_only_not_a_universal_standard",
        "identity_proven": False,
        "numeric_identity_proven": False,
        "text_screening_warning": "Ordered extracted-number equality does not prove labels, units, scope, image-only numbers, or numeric identity; absent numbers remain null, never equal.",
        "warning": "Visual similarity is not page equality, value equality, or a legal version/replacement relationship; inspect both high- and low-distance critical pages against source evidence.",
        "close_match_count": len(close_matches),
        "same_number_close_match_count": sum(
            match["original_page"] == match["candidate_page"] for match in close_matches
        ),
        "max_close_distance": max(
            (match["distance"] for match in close_matches), default=None
        ),
        "same_index_close_count": sum(
            match["same_index_passes_threshold"] for match in same_index_matches
        ),
        "same_index_max_distance": max(
            (match["same_index_distance"] for match in same_index_matches), default=None
        ),
        "same_index_outliers": [
            {"page": match["original_page"], "distance": match["same_index_distance"]}
            for match in same_index_matches if not match["same_index_passes_threshold"]
        ],
        "unmatched_original_pages": [
            match for match in matches if not match["passes_threshold"]
        ],
        "candidate_pages_without_close_original_match": [
            index + 1 for index in range(len(candidate_images))
            if index + 1 not in close_candidate_pages
        ],
        "ambiguous_original_pages": [
            match["original_page"] for match in matches if match["ambiguous_close_match"]
        ],
        "page_matches": matches,
        "candidate_text_inventory": [
            {"page": index + 1, "extractable_text_characters": len(text.strip())}
            for index, text in enumerate(candidate_texts)
        ],
        "first_ten_matches": matches[:10],
        "last_ten_matches": matches[-10:],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.04,
        help="Empirical screening cutoff for this pilot, not a universal PDF standard",
    )
    args = parser.parse_args()
    if not math.isfinite(args.threshold) or not 0 <= args.threshold <= 1:
        parser.error("threshold must be between 0 and 1")
    print(
        json.dumps(
            compare(args.original, args.candidate, args.threshold),
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
