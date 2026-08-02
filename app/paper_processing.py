from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz


@dataclass(frozen=True)
class SentenceSpan:
    text: str
    page_number: int
    rects: list[list[float]]


@dataclass(frozen=True)
class ExtractedPaper:
    title: str
    full_text: str
    pages: list[dict[str, Any]]
    sentence_spans: list[SentenceSpan]


def slugify(value: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return clean or "paper"


def normalize_text(value: str) -> str:
    value = value.replace("\x00", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", value).strip()


def clean_pdf_text(value: str) -> str:
    return str(value).replace("\x00", " ")


def file_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def split_sentences(text: str) -> list[str]:
    normalized = normalize_text(text)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(\[])", normalized)
    return [part.strip() for part in parts if len(part.strip()) >= 45]


def word_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).replace("\u00ad", "")
    return re.sub(r"[^\w]+", "", normalized.casefold(), flags=re.UNICODE)


def phrase_word_keys(value: str) -> list[str]:
    return [key for word in normalize_text(value).split() if (key := word_key(word))]


def merge_word_rects(words: list[tuple[float, float, float, float, int, int, int]]) -> list[list[float]]:
    if not words:
        return []

    lines: dict[tuple[int, int], list[tuple[float, float, float, float, int, int, int]]] = {}
    for word in words:
        lines.setdefault((word[4], word[5]), []).append(word)

    rects: list[list[float]] = []
    for line_words in sorted(lines.values(), key=lambda items: min((item[4], item[5], item[6]) for item in items)):
        x0 = min(word[0] for word in line_words)
        y0 = min(word[1] for word in line_words)
        x1 = max(word[2] for word in line_words)
        y1 = max(word[3] for word in line_words)
        rects.append([round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)])
    return rects


def merge_rect_lines(rects: list[fitz.Rect]) -> list[list[float]]:
    if not rects:
        return []

    sorted_rects = sorted(rects, key=lambda rect: (round((rect.y0 + rect.y1) / 2, 1), rect.x0))
    lines: list[list[fitz.Rect]] = []
    for rect in sorted_rects:
        center_y = (rect.y0 + rect.y1) / 2
        for line in lines:
            line_center_y = sum((item.y0 + item.y1) / 2 for item in line) / len(line)
            if abs(center_y - line_center_y) <= 3:
                line.append(rect)
                break
        else:
            lines.append([rect])

    merged: list[list[float]] = []
    for line in lines:
        x0 = min(rect.x0 for rect in line)
        y0 = min(rect.y0 for rect in line)
        x1 = max(rect.x1 for rect in line)
        y1 = max(rect.y1 for rect in line)
        merged.append([round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)])
    return merged


def find_phrase_word_rects(page: fitz.Page, phrase: str) -> list[list[float]]:
    phrase_keys = phrase_word_keys(phrase)
    if not phrase_keys:
        return []

    page_words = sorted(page.get_text("words"), key=lambda word: (word[5], word[6], word[7]))
    indexed_words: list[tuple[str, tuple[float, float, float, float, int, int, int]]] = []
    for word in page_words:
        key = word_key(str(word[4]))
        if key:
            indexed_words.append(
                (
                    key,
                    (
                        float(word[0]),
                        float(word[1]),
                        float(word[2]),
                        float(word[3]),
                        int(word[5]),
                        int(word[6]),
                        int(word[7]),
                    ),
                )
            )

    for start in range(len(indexed_words)):
        page_index = start
        phrase_index = 0
        matched_words = []
        while page_index < len(indexed_words) and phrase_index < len(phrase_keys):
            key, word = indexed_words[page_index]
            if key == phrase_keys[phrase_index]:
                matched_words.append(word)
                page_index += 1
                phrase_index += 1
                continue
            if page_index + 1 < len(indexed_words) and key + indexed_words[page_index + 1][0] == phrase_keys[phrase_index]:
                matched_words.extend((word, indexed_words[page_index + 1][1]))
                page_index += 2
                phrase_index += 1
                continue
            break
        if phrase_index == len(phrase_keys):
            return merge_word_rects(matched_words)
    return []


def choose_title(pdf_path: Path, doc: fitz.Document, full_text: str) -> str:
    metadata_title = normalize_text(doc.metadata.get("title", ""))
    if metadata_title and len(metadata_title) > 8 and metadata_title.lower() != "untitled":
        return metadata_title[:220]

    for line in full_text.splitlines():
        candidate = normalize_text(line)
        if 20 <= len(candidate) <= 220 and not candidate.lower().startswith(("arxiv:", "abstract")):
            return candidate

    return pdf_path.stem


def extract_page_text(page: fitz.Page) -> str:
    parts = []
    for block in page.get_text("blocks"):
        if len(block) >= 7 and block[6] != 0:
            continue
        text = clean_pdf_text(block[4]).strip()
        if text:
            parts.append(text)
    return "\n".join(parts)


def extract_pdf(pdf_path: Path) -> ExtractedPaper:
    doc = fitz.open(pdf_path)
    pages: list[dict[str, Any]] = []
    sentence_spans: list[SentenceSpan] = []
    full_text_parts: list[str] = []

    for page_index, page in enumerate(doc):
        page_number = page_index + 1
        page_text = extract_page_text(page)

        for block in page.get_text("blocks"):
            if len(block) >= 7 and block[6] != 0:
                continue
            block_text = normalize_text(clean_pdf_text(block[4]))
            if not block_text:
                continue

            block_rect = [[round(float(value), 2) for value in block[:4]]]
            for sentence in split_sentences(block_text):
                sentence_spans.append(SentenceSpan(sentence, page_number, find_phrase_word_rects(page, sentence) or block_rect))

        full_text_parts.append(page_text)
        pages.append(
            {
                "page_number": page_number,
                "width": round(float(page.rect.width), 2),
                "height": round(float(page.rect.height), 2),
                "text": page_text,
            }
        )

    full_text = "\n\n".join(full_text_parts)
    title = choose_title(pdf_path, doc, full_text)
    doc.close()
    return ExtractedPaper(title, full_text, pages, sentence_spans)


def score_match(snippet: str, candidate: str) -> float:
    snippet_words = token_set(snippet)
    candidate_words = token_set(candidate)
    if not snippet_words or not candidate_words:
        return 0.0
    return len(snippet_words & candidate_words) / len(snippet_words)


def token_set(value: str) -> set[str]:
    tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9-]{2,}", value.lower())
    normalized = set()
    for token in tokens:
        if token.endswith("ies") and len(token) > 4:
            normalized.add(f"{token[:-3]}y")
        elif token.endswith("s") and len(token) > 4:
            normalized.add(token[:-1])
        else:
            normalized.add(token)
    return normalized


def search_phrases(snippet: str) -> list[str]:
    normalized = normalize_text(snippet)
    if not normalized:
        return []

    phrases = [normalized[:180]]
    words = normalized.split()
    for size in (16, 12, 9):
        if len(words) < size:
            continue
        starts = {0, max(0, len(words) // 3), max(0, len(words) // 2)}
        for start in starts:
            phrase = " ".join(words[start : start + size])
            if len(phrase) >= 40:
                phrases.append(phrase)

    unique: list[str] = []
    for phrase in phrases:
        if phrase not in unique:
            unique.append(phrase)
    return unique


def find_exact_rects(
    pdf_path: Path,
    snippet: str,
    preferred_page_number: int | None = None,
) -> tuple[int | None, list[list[float]]]:
    phrases = search_phrases(snippet)
    if not phrases:
        return None, []

    doc = fitz.open(pdf_path)
    try:
        page_indexes = list(range(len(doc)))
        if preferred_page_number and 1 <= preferred_page_number <= len(doc):
            preferred_index = preferred_page_number - 1
            page_indexes = [preferred_index, *[index for index in page_indexes if index != preferred_index]]

        for page_index in page_indexes:
            page = doc[page_index]
            full_rects = find_phrase_word_rects(page, snippet)
            if full_rects:
                return page_index + 1, full_rects

            for phrase in phrases:
                word_rects = find_phrase_word_rects(page, phrase)
                if word_rects:
                    return page_index + 1, word_rects

                rects = page.search_for(phrase)
                if rects:
                    return page_index + 1, merge_rect_lines(rects[:24])
    finally:
        doc.close()

    return None, []


def process_narrative_sections(
    pdf_path: Path,
    sections: list[dict[str, Any]],
    source_text: str,
    figures: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Ground hidden Highlight sources without changing synthesized narrative content."""
    figures_by_id = {str(item.get("id")): item for item in figures or [] if item.get("id")}
    processed_sections: list[dict[str, Any]] = []

    for section in sections:
        if not isinstance(section, dict):
            continue
        processed_highlights = []
        for item in section.get("highlights", []):
            if not isinstance(item, dict):
                continue
            source = item.get("source") if isinstance(item.get("source"), dict) else {}
            source_type = str(source.get("type", ""))
            page_number = None
            rects: list[list[float]] = []

            if source_type == "text":
                anchor = normalize_text(str(source.get("anchor", "")))
                try:
                    page_hint = int(source.get("page_hint")) if source.get("page_hint") else None
                except (TypeError, ValueError):
                    page_hint = None
                page_number, rects = find_exact_rects(pdf_path, anchor, page_hint)
            elif source_type == "figure":
                figure = figures_by_id.get(str(source.get("visual_id", "")))
                if figure:
                    page_number = figure.get("page_number")
                    rects = [list(rect) for rect in figure.get("rects", [])]
                    if not rects and figure.get("bbox_pct"):
                        source["bbox_pct"] = figure.get("bbox_pct")

            # Legacy quotation-shaped records remain readable only for in-memory callers;
            # the analysis version invalidates persisted legacy data.
            text = normalize_text(str(item.get("text") or item.get("snippet") or ""))
            processed = {
                **item,
                "text": text,
                "label": sanitize_label(str(item.get("label", "important"))),
                "source": source,
                "page_number": page_number,
                "rects": rects,
                "navigation_available": bool(page_number and (rects or source.get("bbox_pct"))),
            }
            processed.pop("snippet", None)
            processed.pop("reason", None)
            processed.pop("comment", None)
            processed_highlights.append(processed)
        if processed_highlights:
            processed_sections.append(
                {
                    "heading": normalize_text(str(section.get("heading", "Narrative")))[:160] or "Narrative",
                    "highlights": processed_highlights,
                }
            )

    return {"narrative_sections": processed_sections}


def ground_highlights(
    pdf_path: Path,
    highlights: list[dict[str, str]],
    sentence_spans: list[SentenceSpan],
) -> list[dict[str, Any]]:
    grounded: list[dict[str, Any]] = []

    for item in highlights:
        snippet = normalize_text(item.get("snippet", ""))
        page_number, rects = find_exact_rects(pdf_path, snippet)

        best_span: SentenceSpan | None = None
        best_score = 0.0
        if not rects:
            for span in sentence_spans:
                score = score_match(snippet, span.text)
                if snippet and snippet.lower() in span.text.lower():
                    score = 1.0
                if score > best_score:
                    best_span = span
                    best_score = score

        if not rects and best_span and best_score >= 0.38:
            page_number = best_span.page_number
            rects = best_span.rects

        grounded.append(
            {
                "label": sanitize_label(item.get("label", "important")),
                "snippet": snippet,
                "reason": normalize_text(item.get("reason", "")),
                "comment": normalize_text(item.get("comment", "")),
                "page_number": page_number,
                "rects": rects,
            }
        )

    return sort_highlights(grounded)


def sort_highlights(highlights: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(highlights, key=highlight_position)


def highlight_position(highlight: dict[str, Any]) -> tuple[int, float, float]:
    page_number = highlight.get("page_number") or 9999
    rects = highlight.get("rects") or []
    if not rects:
        return int(page_number), 9999.0, 9999.0
    first_rect = sorted(rects, key=lambda rect: (rect[1], rect[0]))[0]
    return int(page_number), float(first_rect[1]), float(first_rect[0])


def sanitize_label(label: str) -> str:
    normalized = re.sub(r"[^a-z]+", "", label.lower())
    aliases = {
        "goal": "problem",
        "objective": "problem",
        "task": "problem",
        "contribution": "novelty",
        "novel": "novelty",
        "new": "novelty",
        "approach": "solution",
        "intervention": "solution",
        "finding": "result",
        "results": "result",
        "evidence": "result",
        "benchmark": "benchmarking",
        "benchmarks": "benchmarking",
        "evaluation": "benchmarking",
        "comparison": "benchmarking",
        "methods": "method",
        "mechanism": "method",
        "caveat": "tradeoff",
        "constraint": "tradeoff",
        "catch": "tradeoff",
        "tradeoffs": "tradeoff",
        "compute": "hyperparams",
        "computing": "hyperparams",
        "hyperparameter": "hyperparams",
        "hyperparameters": "hyperparams",
        "hardware": "hyperparams",
        "runtime": "hyperparams",
        "trainingcost": "hyperparams",
        "modelsize": "hyperparams",
        "resources": "hyperparams",
        "memory": "hyperparams",
        "budget": "hyperparams",
        "environment": "hyperparams",
        "ablationstudy": "ablation",
        "ablations": "ablation",
        "failures": "failure",
        "failuremode": "failure",
        "failuremodes": "failure",
    }
    normalized = aliases.get(normalized, normalized)
    allowed = {
        "problem",
        "solution",
        "novelty",
        "method",
        "benchmarking",
        "result",
        "ablation",
        "hyperparams",
        "tradeoff",
        "limitation",
        "failure",
    }
    if normalized in allowed:
        return normalized
    return "problem"


def public_page_sizes(pages: list[dict[str, Any]]) -> list[dict[str, float | int]]:
    return [
        {
            "page_number": page["page_number"],
            "width": page["width"],
            "height": page["height"],
        }
        for page in pages
    ]
