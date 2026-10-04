"""Bind each observed field to issuer, version, header and physical geometry."""

from __future__ import annotations

from decimal import Decimal, localcontext
import re

from scripts.parsing.generic_extractor import Page, Word


def compact(value: str) -> str:
    return "".join(value.split())


def union_box(words) -> list[float]:
    return [min(word.box[0] for word in words), min(word.box[1] for word in words),
            max(word.box[2] for word in words), max(word.box[3] for word in words)]


def inside(page: Page, words) -> bool:
    return page.rotation == 0 and all(
        0 <= word.box[0] <= word.box[2] <= page.width
        and 0 <= word.box[1] <= word.box[3] <= page.height for word in words)


def money(raw: str, multiplier: int) -> str | None:
    value = compact(raw).replace("，", ",").replace("−", "-").replace("－", "-")
    if value in ("", "-", "—", "–"):
        return None
    if not re.fullmatch(r"-?(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?", value):
        raise ValueError("not an unambiguous finite money cell")
    # Unit normalization must not round source precision under an ambient context.
    with localcontext() as context:
        context.prec = max(28, len(value) + 12)
        return format(Decimal(value.replace(",", "")) * multiplier, "f")


def note_reference_observation(page: Page, notes, left: float, right: float) -> dict:
    """One complete native token in an explicit note column; never resolve a target.

    Bounded chapter grammar: canonical Chinese integers 1..99. Complex item
    numbers are positive ASCII integers without leading zeroes. No joining,
    whitespace deletion, OCR, arbitrary punctuation or reference lists.
    """
    result = {"raw_text": [word.text for word in notes], "boxes": [list(word.box) for word in notes],
              "syntax_state": "NO_REFERENCE_WORDS", "reference_form": None,
              "note_target_resolved": False, "note_semantics_certified": False}
    if any(word.box[2] >= right for word in notes):
        result["syntax_state"] = "NOTE_AMOUNT_BOUNDARY_AMBIGUOUS"
    elif (not 0 <= left < right <= page.width or not inside(page, notes)
          or any(word.box[0] < left or word not in page.words for word in notes)):
        result["syntax_state"] = "NOTE_GEOMETRY_UNKNOWN"
    elif notes:
        chapter = r"(?:[一二三四五六七八九]|十[一二三四五六七八九]?|[二三四五六七八九]十[一二三四五六七八九]?)"
        forms = ((r"[0-9]+", "SINGLE_UNSIGNED_INTEGER"),
                 (r"[-—–]", "DASH_PLACEHOLDER"),
                 (chapter + r"、[1-9][0-9]*", "CHAPTER_DUNHAO_POSITIVE_ITEM"),
                 (chapter + r"（[1-9][0-9]*）", "CHAPTER_FULLWIDTH_PARENS_POSITIVE_ITEM"),
                 (chapter + r"（[1-9][0-9]*）[1-9][0-9]*", "CHAPTER_FULLWIDTH_PARENS_ITEM_SUFFIX"))
        form = next((name for pattern, name in forms if len(notes) == 1
                     and re.fullmatch(pattern, notes[0].text)), None)
        result["syntax_state"] = "OBSERVED_SINGLE_REFERENCE_SYNTAX" if form else "NOTE_CELL_NOT_UNAMBIGUOUS_REFERENCE"
        result["reference_form"] = form
    return result


def cell(page: Page, words: tuple[Word, ...], row_y: float,
         label_right: float, split: float, multiplier: int, *, amount_left: float | None = None) -> dict:
    observed = [word for word in words if abs(word.y - row_y) <= 2
                and word.box[0] >= label_right]
    note_problem = None
    if amount_left is not None:
        notes = [word for word in observed if word.box[0] < amount_left]
        syntax = note_reference_observation(page, notes, label_right, amount_left)
        if syntax["syntax_state"].startswith("NOTE_"):
            note_problem = syntax["syntax_state"]
        observed = [word for word in observed if word.box[0] >= amount_left]
    columns = [[word for word in observed if (word.box[0] + word.box[2]) / 2 < split],
               [word for word in observed if (word.box[0] + word.box[2]) / 2 >= split]]
    result = {}
    for key, column in zip(("current", "comparative"), columns):
        state, value = "BLANK_NOT_ZERO", None
        if note_problem is not None:
            state = note_problem
        elif len(column) > 1:
            state = "AMBIGUOUS_CELL"
        elif column:
            if not inside(page, column):
                state = "PAGE_EDGE_OR_ROTATION_NOT_OBSERVED"
            elif column[0].box[0] < split < column[0].box[2]:
                state = "COLUMN_EDGE_AMBIGUOUS"
            else:
                try:
                    value = money(column[0].text, multiplier)
                    state = "OBSERVED_NUMERIC" if value is not None else "DASH_NOT_ZERO"
                except ValueError:
                    state = "UNPARSEABLE_CELL"
        result[key] = {"value_cny": value, "state": state,
                       "raw_text": [word.text for word in column],
                       "boxes": [list(word.box) for word in column]}
    return result


def binding(source: dict, page: Page, words, header: dict | None) -> dict:
    return {"security_id": source["security_id"], "issuer": source["issuer"],
            "fiscal_year": source["fiscal_year"], "source_version": source["version"],
            "period_end": f"{source['fiscal_year']}-12-31",
            "statement_scope": "CONSOLIDATED" if header else "AUDIT_TEXT_NOT_CURRENT_GATE",
            "currency": "CNY" if header else None,
            "document_sha256": source["pdf_sha256"], "physical_page": page.number,
            "label_box": union_box(words) if words else None,
            "label_text": [word.text for word in words], "table_header": header,
            "evidence_ref": f"pdf:sha256:{source['pdf_sha256']}:physical-page:{page.number}",
            "diagnostic_available_at": None, "historical_pit_status": "UNKNOWN",
            "pit_admitted": False}
