from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import re
from pathlib import Path
from typing import Any, Callable

import fitz

from .paper_processing import ExtractedPaper, normalize_text

PAGE_IMAGE_ZOOM = 1.6
FIGURE_IMAGE_ZOOM = 2.4
FIGURE_TYPES = {"figure", "table", "plot", "diagram", "screenshot", "equation", "other"}
VISUAL_PREPARATION_VERSION = 2
VISUAL_CUE_RE = re.compile(
    r"\b(?:fig(?:ure)?\.?|tables?|algorithms?|schemes?|diagrams?|plots?)\s*(?:s?\d+|[ivxlcdm]+|[a-z])\b",
    re.IGNORECASE,
)


def int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def figure_directory(figures_dir: Path, paper_id: str) -> Path:
    safe_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", paper_id)
    return figures_dir / safe_id


def page_text_has_visual_cue(text: str) -> bool:
    return bool(VISUAL_CUE_RE.search(normalize_text(text)))


def page_has_pdf_visuals(page: fitz.Page) -> bool:
    page_area = max(float(page.rect.width * page.rect.height), 1.0)
    if page.get_images(full=True):
        return True

    try:
        if page.find_tables().tables:
            return True
    except (AttributeError, RuntimeError, ValueError):
        pass

    try:
        drawings = page.get_drawings()
    except RuntimeError:
        return False

    for drawing in drawings:
        rect = drawing.get("rect")
        if rect and float(rect.width * rect.height) >= page_area * 0.02:
            return True
    return len(drawings) >= 12


def _percent_box(rect: fitz.Rect, page_rect: fitz.Rect) -> list[float]:
    return [
        round(100 * (rect.x0 - page_rect.x0) / page_rect.width, 2),
        round(100 * (rect.y0 - page_rect.y0) / page_rect.height, 2),
        round(100 * (rect.x1 - page_rect.x0) / page_rect.width, 2),
        round(100 * (rect.y1 - page_rect.y0) / page_rect.height, 2),
    ]


def prepare_visuals(
    pdf_path: Path,
    extracted: ExtractedPaper,
    figures_dir: Path,
    paper_id: str,
) -> list[dict[str, Any]]:
    """Conservatively prepare actual pixels for every substantive visual page."""
    paper_dir = figure_directory(figures_dir, paper_id)
    version_file = paper_dir / ".visual-preparation-version"
    cached_version = version_file.read_text(encoding="utf-8").strip() if version_file.exists() else ""
    if paper_dir.exists() and cached_version != str(VISUAL_PREPARATION_VERSION):
        import shutil
        shutil.rmtree(paper_dir, ignore_errors=True)
    paper_dir.mkdir(parents=True, exist_ok=True)
    version_file.write_text(str(VISUAL_PREPARATION_VERSION), encoding="utf-8")
    page_text = {int(item.get("page_number", 0)): str(item.get("text", "")) for item in extracted.pages}
    visuals: list[dict[str, Any]] = []
    doc = fitz.open(pdf_path)
    try:
        for page_index, page in enumerate(doc):
            page_number = page_index + 1
            cue = page_text_has_visual_cue(page_text.get(page_number, ""))
            regions: list[fitz.Rect] = []
            page_area = max(page.rect.width * page.rect.height, 1)
            for block in page.get_text("dict").get("blocks", []):
                if block.get("type") == 1 and block.get("bbox"):
                    rect = fitz.Rect(block["bbox"])
                    area_ratio = rect.width * rect.height / page_area
                    in_page_furniture = (rect.y1 <= page.rect.y0 + page.rect.height * 0.08 or rect.y0 >= page.rect.y0 + page.rect.height * 0.92) and area_ratio < 0.05
                    # Tiny images and small header/footer marks are publisher furniture, not evidence.
                    if area_ratio >= 0.005 and not in_page_furniture:
                        regions.append(rect)
            try:
                regions.extend(table.bbox for table in page.find_tables().tables)
            except (AttributeError, RuntimeError, ValueError):
                pass
            try:
                drawing_rects = [fitz.Rect(item["rect"]) for item in page.get_drawings() if item.get("rect")]
            except RuntimeError:
                drawing_rects = []
            content_drawings = [
                rect
                for rect in drawing_rects
                if not (
                    min(rect.width, rect.height) <= 2
                    and (rect.y1 <= page.rect.y0 + page.rect.height * 0.08 or rect.y0 >= page.rect.y0 + page.rect.height * 0.92)
                )
            ]
            if content_drawings and cue:
                union = fitz.Rect(content_drawings[0])
                for rect in content_drawings[1:]:
                    union |= rect
                if union.width * union.height >= page_area * 0.02:
                    regions.append(union)
            if not regions and cue:
                regions = [page.rect]
            if not regions:
                continue

            # Disconnected regions and cue-only pages need the complete page as context.
            include_full_page = len(regions) != 1 or regions[0] == page.rect
            for region_index, region in enumerate(regions, start=1):
                expanded = fitz.Rect(region.x0 - 18, region.y0 - 36, region.x1 + 18, region.y1 + 72) & page.rect
                visual_id = f"p{page_number}-{region_index}"
                crop_file = f"{visual_id}.jpg"
                bbox_pct = _percent_box(region, page.rect)
                crop_bbox_pct = _percent_box(expanded, page.rect)
                crop_path = paper_dir / crop_file
                if not crop_path.exists():
                    crop_figure_image(pdf_path, page_number, crop_bbox_pct, crop_path)
                page_file = None
                if include_full_page:
                    page_file = f"page-{page_number}.jpg"
                    page_path = paper_dir / page_file
                    if not page_path.exists():
                        render_page_image(pdf_path, page_number, page_path)
                visuals.append(
                    {
                        "id": visual_id,
                        "preparation_version": VISUAL_PREPARATION_VERSION,
                        "page_number": page_number,
                        "bbox_pct": bbox_pct,
                        "crop_bbox_pct": crop_bbox_pct,
                        "rects": [[round(value, 2) for value in region]],
                        "image_file": crop_file,
                        "image_path": str(paper_dir / crop_file),
                        "page_image_path": str(paper_dir / page_file) if page_file else None,
                        "nearby_text": normalize_text(page_text.get(page_number, ""))[:2000],
                    }
                )
    finally:
        doc.close()
    return visuals


def visual_candidate_pages(pdf_path: Path, pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    text_candidates = {
        int(page.get("page_number", 0))
        for page in pages
        if page_text_has_visual_cue(str(page.get("text", "")))
    }
    structural_candidates: set[int] = set()

    try:
        doc = fitz.open(pdf_path)
    except (RuntimeError, fitz.FileDataError, fitz.EmptyFileError):
        doc = None

    if doc:
        try:
            for page in pages:
                page_number = int(page.get("page_number", 0))
                if 1 <= page_number <= len(doc) and page_has_pdf_visuals(doc[page_number - 1]):
                    structural_candidates.add(page_number)
        finally:
            doc.close()

    candidate_numbers = text_candidates | structural_candidates
    return [page for page in pages if int(page.get("page_number", 0)) in candidate_numbers]


def render_page_image(pdf_path: Path, page_number: int, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_number - 1]
        pixmap = page.get_pixmap(matrix=fitz.Matrix(PAGE_IMAGE_ZOOM, PAGE_IMAGE_ZOOM), alpha=False)
        pixmap.save(output_path)
    finally:
        doc.close()


def crop_figure_image(pdf_path: Path, page_number: int, bbox_pct: list[float], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_number - 1]
        page_rect = page.rect
        x0, y0, x1, y1 = bbox_pct
        clip = fitz.Rect(
            page_rect.x0 + page_rect.width * x0 / 100,
            page_rect.y0 + page_rect.height * y0 / 100,
            page_rect.x0 + page_rect.width * x1 / 100,
            page_rect.y0 + page_rect.height * y1 / 100,
        ) & page_rect
        if clip.is_empty or clip.width < 8 or clip.height < 8:
            clip = page_rect
        pixmap = page.get_pixmap(matrix=fitz.Matrix(FIGURE_IMAGE_ZOOM, FIGURE_IMAGE_ZOOM), clip=clip, alpha=False)
        pixmap.save(output_path)
    finally:
        doc.close()


def ensure_figure_images(
    pdf_path: Path,
    figures_dir: Path,
    paper_id: str,
    figures: list[dict[str, Any]],
) -> None:
    if not figures or not pdf_path.exists():
        return

    paper_dir = figure_directory(figures_dir, paper_id)
    for figure in figures:
        image_file = Path(str(figure.get("image_file", ""))).name
        if not image_file:
            continue

        try:
            page_number = int(figure.get("page_number") or 0)
        except (TypeError, ValueError):
            continue
        if page_number < 1:
            continue

        image_path = paper_dir / image_file
        if image_path.exists():
            continue

        try:
            crop_figure_image(pdf_path, page_number, coerce_bbox_pct(figure.get("bbox_pct")), image_path)
        except (IndexError, RuntimeError, ValueError, fitz.FileDataError, fitz.EmptyFileError):
            continue


def coerce_bbox_pct(value: Any) -> list[float]:
    if not isinstance(value, list) or len(value) != 4:
        return [0.0, 0.0, 100.0, 100.0]

    numbers = []
    for item in value:
        try:
            numbers.append(float(item))
        except (TypeError, ValueError):
            return [0.0, 0.0, 100.0, 100.0]

    x0, y0, x1, y1 = numbers
    x0, x1 = sorted((max(0.0, min(100.0, x0)), max(0.0, min(100.0, x1))))
    y0, y1 = sorted((max(0.0, min(100.0, y0)), max(0.0, min(100.0, y1))))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return [0.0, 0.0, 100.0, 100.0]
    return [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)]


def sanitize_figure_type(value: Any) -> str:
    normalized = re.sub(r"[^a-z]+", "", str(value).lower())
    return normalized if normalized in FIGURE_TYPES else "other"
