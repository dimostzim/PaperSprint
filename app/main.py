from __future__ import annotations

import asyncio
import json
import shutil
import uuid
from pathlib import Path
from typing import Any, Literal

import fitz
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.requests import Request

from .ai import (
    ANALYSIS_VERSION,
    ModelCapacityError,
    analyze_paper,
    build_analysis_prompt,
    answer_chat,
    answer_selection_explanation,
    provider_model_options,
    provider_status,
    resolve_text_model,
    model_capacity_tokens,
    model_supports_multimodal,
    validate_analysis_capacity,
    validate_citations,
)
from .citations import CITATION_VERSION, citation_has_context, extract_citations, ground_citation_rects
from .figures import ensure_figure_images, figure_directory, prepare_visuals
from .paper_processing import extract_pdf, file_digest, find_exact_rects, public_page_sizes, slugify
from .web_search import search_web

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
SESSION_DIR = DATA_DIR / "session"
CACHE_DIR = DATA_DIR / "cache"
PAPERS_DIR = SESSION_DIR / "papers"
FIGURES_DIR = SESSION_DIR / "figures"
CACHE_PAPERS_DIR = CACHE_DIR / "papers"
CACHE_RECORDS_DIR = CACHE_DIR / "records"
CACHE_FIGURES_DIR = CACHE_DIR / "figures"
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

shutil.rmtree(SESSION_DIR, ignore_errors=True)
PAPERS_DIR.mkdir(parents=True, exist_ok=True)
FIGURES_DIR.mkdir(parents=True, exist_ok=True)
CACHE_PAPERS_DIR.mkdir(parents=True, exist_ok=True)
CACHE_RECORDS_DIR.mkdir(parents=True, exist_ok=True)
CACHE_FIGURES_DIR.mkdir(parents=True, exist_ok=True)
PAPERS: dict[str, dict[str, Any]] = {}

app = FastAPI(title="PaperSprint")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    use_web: bool = False
    provider: str | None = None
    api_key: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    citation_context: dict[str, Any] | None = None
    figure_context: list[dict[str, Any]] | None = None


class AnalysisRequest(BaseModel):
    provider: str | None = "auto"
    api_key: str | None = None
    model: str | None = None
    reanalyze: bool = False


class SelectionExplainRequest(BaseModel):
    selected_text: str
    page_number: int | None = None
    page_text: str = ""
    provider: str | None = None
    api_key: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None


class ModelsRequest(BaseModel):
    provider: str | None = "auto"
    api_key: str | None = None


class HighlightsUpdateRequest(BaseModel):
    manual_highlights: list[dict[str, Any]] | None = None
    highlights: list[dict[str, Any]] | None = None


def read_paper(paper_id: str) -> dict[str, Any]:
    paper = PAPERS.get(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found.")
    return paper


def write_paper(paper: dict[str, Any]) -> None:
    PAPERS[paper["id"]] = paper


def cache_record_path(digest: str) -> Path:
    return CACHE_RECORDS_DIR / f"{digest}.json"


def cache_pdf_path(digest: str) -> Path:
    return CACHE_PAPERS_DIR / f"{digest}.pdf"


def paper_pdf_path(paper: dict[str, Any]) -> Path:
    stored_pdf = str(paper.get("stored_pdf", ""))
    if not stored_pdf:
        raise HTTPException(status_code=404, detail="PDF file not found.")

    pdf_path = PAPERS_DIR / stored_pdf
    if pdf_path.exists():
        return pdf_path

    digest = str(paper.get("digest", ""))
    if digest:
        cached_pdf = cache_pdf_path(digest)
        if cached_pdf.exists():
            PAPERS_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(cached_pdf, pdf_path)
            return pdf_path

    raise HTTPException(status_code=404, detail="PDF file not found.")


def cache_figures_path(digest: str) -> Path:
    return figure_directory(CACHE_FIGURES_DIR, digest)


def copy_figure_directory(source: Path, target: Path) -> None:
    shutil.rmtree(target, ignore_errors=True)
    if source.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target)


def restore_cached_figures(digest: str, paper_id: str, paper: dict[str, Any], pdf_path: Path | None = None) -> None:
    if not paper.get("figures"):
        paper["figures"] = []
        paper["figure_warnings"] = paper.get("figure_warnings", [])
        paper["figure_provider_used"] = paper.get("figure_provider_used", "unknown")
        paper["figure_analysis_status"] = paper.get("figure_analysis_status", "idle")
        return

    if pdf_path and pdf_path.exists():
        ensure_figure_images(pdf_path, CACHE_FIGURES_DIR, digest, paper.get("figures", []))

    source_figures = cache_figures_path(digest)
    if source_figures.exists():
        copy_figure_directory(source_figures, figure_directory(FIGURES_DIR, paper_id))
        return

    paper["figures"] = []
    paper["figure_warnings"] = []
    paper["figure_provider_used"] = "unknown"
    paper["figure_analysis_status"] = "idle"


def restore_cached_figure_analysis(
    digest: str,
    paper_id: str,
    paper: dict[str, Any],
    pdf_path: Path | None = None,
) -> None:
    record_path = cache_record_path(digest)
    if not record_path.exists():
        return

    cached = json.loads(record_path.read_text(encoding="utf-8"))
    if not cached.get("figures"):
        return

    paper["figures"] = cached.get("figures", [])
    paper["figure_warnings"] = cached.get("figure_warnings", [])
    paper["figure_provider_used"] = cached.get("figure_provider_used", "unknown")
    paper["figure_analysis_status"] = "complete"
    restore_cached_figures(digest, paper_id, paper, pdf_path)


def cache_figure_images(digest: str, paper: dict[str, Any]) -> bool:
    target_figures = cache_figures_path(digest)
    if not paper.get("figures"):
        shutil.rmtree(target_figures, ignore_errors=True)
        return False

    source_figures = figure_directory(FIGURES_DIR, str(paper.get("id", "")))
    if source_figures.exists():
        copy_figure_directory(source_figures, target_figures)
        return True

    return target_figures.exists()


def cached_analysis(digest: str, paper_id: str, filename: str, stored_pdf: str) -> dict[str, Any] | None:
    record_path = cache_record_path(digest)
    source_pdf = cache_pdf_path(digest)
    if not record_path.exists() or not source_pdf.exists():
        return None

    paper = json.loads(record_path.read_text(encoding="utf-8"))
    if paper.get("analysis_version") != ANALYSIS_VERSION:
        return None

    paper.update(
        {
            "id": paper_id,
            "filename": filename,
            "stored_pdf": stored_pdf,
        }
    )
    pdf_path = PAPERS_DIR / stored_pdf
    shutil.copyfile(source_pdf, pdf_path)
    restore_cached_figures(digest, paper_id, paper, pdf_path)
    if paper.get("citation_version") != CITATION_VERSION:
        refresh_paper_citations(paper, pdf_path)
        write_cache_record(paper)
    return paper


def write_cache_record(paper: dict[str, Any]) -> None:
    digest = str(paper.get("digest", ""))
    if digest:
        CACHE_RECORDS_DIR.mkdir(parents=True, exist_ok=True)
        cache_record_path(digest).write_text(json.dumps(paper), encoding="utf-8")


def analyze_citations_for_paper(
    pdf_path: Path,
    extracted: Any,
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> list[dict[str, Any]]:
    citations = extract_citations(extracted)
    if provider:
        try:
            citations = validate_citations(citations, provider, api_key, model, reasoning_effort)
        except Exception:
            pass
    return ground_citation_rects(pdf_path, citations)


def refresh_paper_citations(paper: dict[str, Any], pdf_path: Path) -> None:
    extracted = extract_pdf(pdf_path)
    paper["citations"] = analyze_citations_for_paper(pdf_path, extracted)
    paper["citation_version"] = CITATION_VERSION
    paper["citation_status"] = "complete"
    paper["citation_error"] = ""


def cached_paper_from_record(record_path: Path) -> dict[str, Any] | None:
    digest = record_path.stem
    source_pdf = cache_pdf_path(digest)
    if not source_pdf.exists():
        return None

    record = json.loads(record_path.read_text(encoding="utf-8"))
    paper_id = digest[:12]
    filename = str(record.get("filename") or f"{paper_id}.pdf")
    stored_pdf = f"{paper_id}-{slugify(Path(filename).stem)}.pdf"

    cached = cached_analysis(digest, paper_id, filename, stored_pdf)
    if cached:
        return cached

    if not record.get("figures"):
        return None

    pdf_path = PAPERS_DIR / stored_pdf
    shutil.copyfile(source_pdf, pdf_path)
    paper = build_uploaded_paper_record(pdf_path, paper_id, filename, digest)
    restore_cached_figure_analysis(digest, paper_id, paper, pdf_path)
    return paper


def restore_all_cached_papers() -> int:
    loaded_count = 0
    record_paths = sorted(CACHE_RECORDS_DIR.glob("*.json"), key=lambda path: path.stat().st_mtime)
    for record_path in record_paths:
        try:
            paper = cached_paper_from_record(record_path)
        except (json.JSONDecodeError, OSError, RuntimeError, shutil.Error, fitz.FileDataError, fitz.EmptyFileError):
            continue
        if not paper:
            continue
        write_paper(paper)
        loaded_count += 1
    return loaded_count


def cache_paper(paper: dict[str, Any], pdf_path: Path) -> None:
    digest = str(paper.get("digest", ""))
    if not digest:
        return

    CACHE_PAPERS_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_RECORDS_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(pdf_path, cache_pdf_path(digest))
    cached = dict(paper)
    if not cache_figure_images(digest, cached):
        cached["figures"] = []
        cached["figure_warnings"] = []
        cached["figure_provider_used"] = "unknown"
    cache_record_path(digest).write_text(json.dumps(cached), encoding="utf-8")


def delete_cached_paper(digest: str, paper_id: str) -> None:
    if digest:
        cache_pdf_path(digest).unlink(missing_ok=True)
        cache_record_path(digest).unlink(missing_ok=True)
        shutil.rmtree(cache_figures_path(digest), ignore_errors=True)
        return

    for directory, suffix in ((CACHE_PAPERS_DIR, ".pdf"), (CACHE_RECORDS_DIR, ".json")):
        for path in directory.glob(f"{paper_id}*{suffix}"):
            path.unlink(missing_ok=True)
    shutil.rmtree(figure_directory(CACHE_FIGURES_DIR, paper_id), ignore_errors=True)


def public_figures(paper_id: str, figures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    public_items = []
    for figure in figures:
        figure_id = figure.get("id")
        if not figure_id:
            continue
        public_item = {key: value for key, value in figure.items() if key not in {"image_file", "image_path", "page_image_path"}}
        public_item["image_url"] = f"/api/papers/{paper_id}/figures/{figure_id}/image"
        public_items.append(public_item)
    return public_items


def selected_figure_image_paths(
    paper_id: str,
    paper: dict[str, Any],
    figure_context: list[dict[str, Any]] | None,
) -> list[Path]:
    selected_ids = list(dict.fromkeys(
        str(item.get("id", "")).strip()
        for item in figure_context or []
        if str(item.get("id", "")).strip()
    ))
    if not selected_ids:
        return []

    figures_by_id = {str(item.get("id")): item for item in paper.get("figures", []) if item.get("id")}
    unknown_ids = [figure_id for figure_id in selected_ids if figure_id not in figures_by_id]
    if unknown_ids:
        raise HTTPException(status_code=400, detail="Selected figure is no longer available.")

    paper_dir = figure_directory(FIGURES_DIR, paper_id)
    paths: list[Path] = []
    for figure_id in selected_ids:
        figure = figures_by_id[figure_id]
        image_file = Path(str(figure.get("image_file", ""))).name
        image_path = paper_dir / image_file
        if not image_file or not image_path.exists():
            ensure_figure_images(paper_pdf_path(paper), FIGURES_DIR, paper_id, [figure])
        if not image_file or not image_path.exists():
            raise HTTPException(status_code=409, detail="Selected figure image is unavailable.")
        paths.append(image_path)

        page_image_file = Path(str(figure.get("page_image_path", ""))).name
        page_image_path = paper_dir / page_image_file
        if page_image_file and page_image_path.exists():
            paths.append(page_image_path)

    return list(dict.fromkeys(paths))


def figure_analysis_response(paper_id: str, paper: dict[str, Any]) -> dict[str, Any]:
    return {
        "figures": public_figures(paper_id, paper.get("figures", [])),
        "warnings": paper.get("figure_warnings", []),
        "provider_used": paper.get("figure_provider_used", "unknown"),
        "status": paper.get("figure_analysis_status", "complete" if paper.get("figures") else "idle"),
        "error": paper.get("figure_analysis_error", ""),
        "completed_pages": paper.get("figure_analysis_completed_pages", 0),
        "total_pages": paper.get("figure_analysis_total_pages", 0),
    }


def clean_highlight_record(highlight: dict[str, Any]) -> dict[str, Any] | None:
    snippet = " ".join(str(highlight.get("snippet", "")).split()).strip()
    if not snippet:
        return None

    label = " ".join(str(highlight.get("label", "important")).split()).strip().lower()
    if not label:
        label = "important"
    label = label[:40]

    try:
        page_number = int(highlight["page_number"]) if highlight.get("page_number") else None
    except (TypeError, ValueError):
        page_number = None

    rects = []
    if isinstance(highlight.get("rects"), list):
        for rect in highlight["rects"]:
            if not isinstance(rect, list) or len(rect) != 4:
                continue
            try:
                rects.append([round(float(value), 2) for value in rect])
            except (TypeError, ValueError):
                continue

    requested_id = str(highlight.get("id", ""))[:64]
    manual_id = requested_id if requested_id.startswith("manual-") else f"manual-{uuid.uuid4().hex[:12]}"
    clean: dict[str, Any] = {
        "id": manual_id,
        "source": "manual",
        "label": label,
        "snippet": snippet[:900],
        "reason": " ".join(str(highlight.get("reason", "")).split()).strip()[:240],
        "page_number": page_number,
        "rects": rects,
    }
    comment = " ".join(str(highlight.get("comment", "")).split()).strip()
    if comment:
        clean["comment"] = comment[:700]
    color = str(highlight.get("color", "")).strip()
    if color:
        clean["color"] = color[:24]
    clean["navigation_available"] = bool(page_number and rects)
    return clean


def ground_clean_highlight(
    clean: dict[str, Any],
    raw_highlight: dict[str, Any],
    pdf_path: Path,
) -> dict[str, Any]:
    if not raw_highlight.get("reground") or not pdf_path.exists():
        return clean

    page_number, rects = find_exact_rects(pdf_path, clean["snippet"], clean.get("page_number"))
    if rects:
        clean["page_number"] = page_number
        clean["rects"] = rects
        clean["navigation_available"] = True
    return clean


def flatten_highlight_sequence(paper: dict[str, Any]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    narrative_index = 0
    for section_index, section in enumerate(paper.get("narrative_sections", [])):
        for highlight in section.get("highlights", []):
            flattened.append(
                {
                    **highlight,
                    "origin": "generated",
                    "section_index": section_index,
                    "narrative_index": narrative_index,
                    "navigation_available": bool(highlight.get("page_number") and highlight.get("rects")),
                }
            )
            narrative_index += 1
    return flattened


def public_paper(paper: dict[str, Any], include_details: bool = False) -> dict[str, Any]:
    highlights = flatten_highlight_sequence(paper)
    citations = paper.get("citations", [])
    base = {
        "id": paper["id"],
        "filename": paper["filename"],
        "title": paper["title"],
        "provider_used": paper.get("provider_used", "unknown"),
        "analysis_model": paper.get("analysis_model", ""),
        "analysis_status": paper.get("analysis_status", "complete"),
        "analysis_stage": paper.get("analysis_stage", ""),
        "reanalysis_status": paper.get("reanalysis_status", "idle"),
        "reanalysis_error": paper.get("reanalysis_error", ""),
        "analysis_revision": paper.get("analysis_revision", 0),
        "chat_available": paper.get("analysis_status") == "complete",
        "analysis_error": paper.get("analysis_error", ""),
        "highlight_count": len(highlights),
        "figure_count": len(paper.get("figures", [])),
        "figure_analysis_status": paper.get("figure_analysis_status", "complete" if paper.get("figures") else "idle"),
        "figure_analysis_error": paper.get("figure_analysis_error", ""),
        "figure_analysis_completed_pages": paper.get("figure_analysis_completed_pages", 0),
        "figure_analysis_total_pages": paper.get("figure_analysis_total_pages", 0),
        "citation_count": sum(1 for citation in citations if citation_has_context(citation)),
        "citation_status": paper.get("citation_status", "complete" if citations else "pending"),
        "citation_error": paper.get("citation_error", ""),
    }
    if include_details:
        base.update(
            {
                "narrative_sections": paper.get("narrative_sections", []),
                "manual_highlights": paper.get("manual_highlights", []),
                "highlights": highlights,
                "overlay_highlights": [
                    *highlights,
                    *[
                        {
                            **item,
                            "origin": "manual",
                            "highlightIndex": len(highlights) + index,
                            "navigation_available": bool(item.get("page_number") and item.get("rects")),
                        }
                        for index, item in enumerate(paper.get("manual_highlights", []))
                    ],
                ],
                "figures": public_figures(paper["id"], paper.get("figures", [])),
                "figure_warnings": paper.get("figure_warnings", []),
                "figure_provider_used": paper.get("figure_provider_used", "unknown"),
                "figure_analysis_status": paper.get("figure_analysis_status", "complete" if paper.get("figures") else "idle"),
                "figure_analysis_error": paper.get("figure_analysis_error", ""),
                "figure_analysis_completed_pages": paper.get("figure_analysis_completed_pages", 0),
                "figure_analysis_total_pages": paper.get("figure_analysis_total_pages", 0),
                "citations": paper.get("citations", []),
                "page_sizes": paper.get("page_sizes", []),
            }
        )
    return base


def analyzed_paper_record(
    pdf_path: Path,
    paper_id: str,
    filename: str,
    digest: str,
    extracted: Any,
    analysis: dict[str, Any],
    citations: list[dict[str, Any]],
    citation_status: str,
    analysis_status: str,
    citation_error: str = "",
) -> dict[str, Any]:
    return {
        "id": paper_id,
        "filename": filename,
        "stored_pdf": pdf_path.name,
        "digest": digest,
        "analysis_version": ANALYSIS_VERSION,
        "title": analysis.get("title") or extracted.title,
        "narrative_sections": analysis.get("narrative_sections", []),
        "analysis_text": analysis.get("analysis_text", ""),
        "manual_highlights": [],
        "figures": analysis.get("figures", []),
        "figure_warnings": [],
        "figure_provider_used": analysis.get("provider_used", "unknown"),
        "figure_analysis_status": "complete",
        "figure_analysis_error": "",
        "figure_analysis_completed_pages": 0,
        "figure_analysis_total_pages": 0,
        "citations": citations,
        "citation_version": CITATION_VERSION if citation_status == "complete" else 0,
        "citation_status": citation_status,
        "citation_error": citation_error,
        "provider_used": analysis.get("provider_used", "unknown"),
        "analysis_model": analysis.get("analysis_model", ""),
        "page_sizes": public_page_sizes(extracted.pages),
        "sentences": [
            {
                "text": span.text,
                "page_number": span.page_number,
            }
            for span in extracted.sentence_spans
        ],
        "full_text_chars": len(extracted.full_text),
        "analysis_status": analysis_status,
        "analysis_stage": "complete" if analysis_status == "complete" else "",
        "analysis_error": "",
        "reanalysis_status": "idle",
        "reanalysis_error": "",
        "analysis_revision": 1 if analysis_status == "complete" else 0,
    }



def build_uploaded_paper_record(
    pdf_path: Path,
    paper_id: str,
    filename: str,
    digest: str,
) -> dict[str, Any]:
    extracted = extract_pdf(pdf_path)
    return {
        "id": paper_id,
        "filename": filename,
        "stored_pdf": pdf_path.name,
        "digest": digest,
        "analysis_version": 0,
        "title": extracted.title or Path(filename).stem,
        "narrative_sections": [],
        "manual_highlights": [],
        "figures": [],
        "figure_warnings": [],
        "figure_provider_used": "unknown",
        "figure_analysis_status": "idle",
        "figure_analysis_error": "",
        "figure_analysis_completed_pages": 0,
        "figure_analysis_total_pages": 0,
        "citations": [],
        "citation_version": 0,
        "citation_status": "pending",
        "citation_error": "",
        "provider_used": "not analyzed",
        "analysis_model": "",
        "page_sizes": public_page_sizes(extracted.pages),
        "sentences": [
            {
                "text": span.text,
                "page_number": span.page_number,
            }
            for span in extracted.sentence_spans
        ],
        "full_text_chars": len(extracted.full_text),
        "analysis_status": "ready",
        "analysis_stage": "",
        "analysis_error": "",
        "reanalysis_status": "idle",
        "reanalysis_error": "",
        "analysis_revision": 0,
    }


def finish_paper_analysis(
    pdf_path: Path,
    paper_id: str,
    filename: str,
    provider: str | None,
    digest: str,
    api_key: str | None = None,
    model: str | None = None,
    prepared_extracted: Any | None = None,
    prepared_visuals: list[dict[str, Any]] | None = None,
    is_reanalysis: bool = False,
) -> None:
    try:
        extracted = prepared_extracted or extract_pdf(pdf_path)
        latest = PAPERS.get(paper_id, {})
        latest["analysis_stage"] = "Preparing figures and tables"
        write_paper(latest)
        visuals = prepared_visuals if prepared_visuals is not None else prepare_visuals(pdf_path, extracted, FIGURES_DIR, paper_id)
        latest["analysis_stage"] = "Building the Highlight sequence"
        write_paper(latest)
        analysis = analyze_paper(pdf_path, extracted, provider, api_key, model, "high", visuals)
        latest["analysis_stage"] = "Finalizing source links"
        write_paper(latest)
        analysis["analysis_model"] = resolve_text_model(model)
    except Exception as error:
        pending = PAPERS.get(paper_id)
        if pending:
            if is_reanalysis:
                pending["reanalysis_status"] = "error"
                pending["reanalysis_error"] = str(error)
            else:
                pending["analysis_status"] = "error"
                pending["analysis_error"] = str(error)
            pending["analysis_stage"] = ""
            write_paper(pending)
        return

    existing = PAPERS.get(paper_id, {})
    paper = analyzed_paper_record(
        pdf_path, paper_id, filename, digest, extracted, analysis,
        existing.get("citations", []), existing.get("citation_status", "pending"), "complete",
    )
    paper["manual_highlights"] = existing.get("manual_highlights", [])
    paper["analysis_revision"] = int(existing.get("analysis_revision", 0)) + 1
    paper["reanalysis_status"] = "idle"
    paper["analysis_stage"] = "complete"
    write_paper(paper)
    cache_paper(paper, pdf_path)

    # Citations are useful but cannot block the installed analysis snapshot.
    try:
        citations = analyze_citations_for_paper(pdf_path, extracted, provider, api_key, model, "high")
        latest = PAPERS.get(paper_id)
        if latest and latest.get("analysis_revision") == paper["analysis_revision"]:
            latest["citations"] = citations
            latest["citation_version"] = CITATION_VERSION
            latest["citation_status"] = "complete"
            latest["citation_error"] = ""
            write_paper(latest)
            cache_paper(latest, pdf_path)
    except Exception as error:
        latest = PAPERS.get(paper_id)
        if latest:
            latest["citation_status"] = "error"
            latest["citation_error"] = str(error)
            write_paper(latest)




@app.get("/")
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})




@app.get("/api/settings")
def settings():
    return provider_status()


@app.post("/api/models")
async def list_provider_models(request: ModelsRequest):
    provider = request.provider or "auto"
    if provider not in {"auto", "codex", "openai", "openrouter"}:
        raise HTTPException(status_code=400, detail="Unknown AI provider.")
    models = [
        model
        for model in await asyncio.to_thread(provider_model_options, provider, request.api_key)
        if model_supports_multimodal(model)
    ]
    return {
        "provider": provider,
        "model_options": models,
        "model_capacities": {model: model_capacity_tokens(model) for model in models},
    }


@app.get("/api/papers")
def list_papers():
    return {"papers": [public_paper(paper) for paper in reversed(PAPERS.values())]}


@app.post("/api/papers/refresh-cache")
def refresh_papers_from_cache():
    loaded_count = restore_all_cached_papers()
    return {
        "loaded_count": loaded_count,
        "papers": [public_paper(paper) for paper in reversed(PAPERS.values())],
    }


@app.post("/api/upload")
async def upload_paper(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Upload a PDF file.")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded PDF is empty.")

    digest = file_digest(data)
    paper_id = digest[:12]
    safe_name = f"{paper_id}-{slugify(Path(file.filename).stem)}.pdf"
    pdf_path = PAPERS_DIR / safe_name

    if paper_id in PAPERS and pdf_path.exists():
        return public_paper(PAPERS[paper_id], include_details=True)

    cached = cached_analysis(digest, paper_id, file.filename, safe_name)
    if cached:
        write_paper(cached)
        return public_paper(cached, include_details=True)

    pdf_path.write_bytes(data)

    try:
        paper = build_uploaded_paper_record(pdf_path, paper_id, file.filename, digest)
    except fitz.FileDataError as error:
        pdf_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Uploaded file is not a readable PDF.") from error

    restore_cached_figure_analysis(digest, paper_id, paper, pdf_path)
    write_paper(paper)
    return public_paper(paper, include_details=True)


@app.post("/api/papers/{paper_id}/analyze")
async def analyze_uploaded_paper(paper_id: str, request: AnalysisRequest):
    paper = read_paper(paper_id)
    provider = request.provider or "auto"
    if provider not in {"auto", "codex", "openai", "openrouter"}:
        raise HTTPException(status_code=502, detail="The local fallback provider has been removed.")
    pdf_path = paper_pdf_path(paper)

    if paper.get("analysis_status") == "analyzing" or paper.get("reanalysis_status") == "analyzing":
        return public_paper(paper, include_details=True)
    if (
        not request.reanalyze
        and paper.get("analysis_status") == "complete"
        and paper.get("narrative_sections")
        and paper.get("analysis_version") == ANALYSIS_VERSION
        and paper.get("citation_version") == CITATION_VERSION
    ):
        return public_paper(paper, include_details=True)

    try:
        extracted = await asyncio.to_thread(extract_pdf, pdf_path)
        visuals = await asyncio.to_thread(prepare_visuals, pdf_path, extracted, FIGURES_DIR, paper_id)
        image_paths = list(dict.fromkeys(
            Path(path)
            for item in visuals
            for path in (item.get("image_path"), item.get("page_image_path"))
            if path
        ))
        validate_analysis_capacity(build_analysis_prompt(extracted, visuals), request.model, image_paths)
    except ModelCapacityError as error:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "model_capacity_exceeded",
                "message": str(error),
                "model": error.model,
                "required_tokens": error.required_tokens,
                "capacity_tokens": error.capacity_tokens,
            },
        ) from error

    is_reanalysis = paper.get("analysis_status") == "complete"
    if is_reanalysis:
        paper["reanalysis_status"] = "analyzing"
        paper["reanalysis_error"] = ""
    else:
        paper["analysis_status"] = "analyzing"
        paper["analysis_error"] = ""
    paper["analysis_stage"] = "Preparing paper text"
    write_paper(paper)

    asyncio.create_task(
        asyncio.to_thread(
            finish_paper_analysis,
            pdf_path,
            paper_id,
            paper["filename"],
            provider,
            paper.get("digest", ""),
            request.api_key,
            request.model,
            extracted,
            visuals,
            is_reanalysis,
        )
    )
    return public_paper(paper, include_details=True)


@app.get("/api/papers/{paper_id}")
def get_paper(paper_id: str):
    return public_paper(read_paper(paper_id), include_details=True)


@app.put("/api/papers/{paper_id}/highlights")
def update_paper_highlights(paper_id: str, request: HighlightsUpdateRequest):
    paper = read_paper(paper_id)
    try:
        pdf_path = paper_pdf_path(paper)
    except HTTPException:
        pdf_path = PAPERS_DIR / str(paper.get("stored_pdf", ""))
    requested = request.manual_highlights if request.manual_highlights is not None else request.highlights or []
    manual_highlights = [
        ground_clean_highlight(clean, item, pdf_path)
        for item in requested[:120]
        if (clean := clean_highlight_record(item))
    ]
    paper["manual_highlights"] = manual_highlights
    write_paper(paper)

    if pdf_path.exists():
        cache_paper(paper, pdf_path)

    return public_paper(paper, include_details=True)


@app.delete("/api/papers/{paper_id}/highlights/{highlight_id}")
def delete_highlight(
    paper_id: str,
    highlight_id: str,
    source: Literal["generated", "manual"],
):
    paper = read_paper(paper_id)
    if source == "generated":
        raise HTTPException(status_code=409, detail="Generated Highlights are immutable; use reanalysis to replace them.")
    sections = []
    for section in paper.get("narrative_sections", []):
        highlights = [
            item
            for item in section.get("highlights", [])
            if source == "manual" or item.get("id") != highlight_id
        ]
        if highlights:
            sections.append({**section, "highlights": highlights})
    paper["narrative_sections"] = sections
    if source != "generated":
        paper["manual_highlights"] = [item for item in paper.get("manual_highlights", []) if item.get("id") != highlight_id]
    write_paper(paper)
    try:
        cache_paper(paper, paper_pdf_path(paper))
    except HTTPException:
        pass
    return public_paper(paper, include_details=True)


@app.delete("/api/papers/{paper_id}")
def delete_paper(paper_id: str):
    paper = PAPERS.pop(paper_id, None)
    if not paper:
        delete_cached_paper("", paper_id)
        shutil.rmtree(figure_directory(FIGURES_DIR, paper_id), ignore_errors=True)
        return {"deleted": False}

    (PAPERS_DIR / str(paper.get("stored_pdf", ""))).unlink(missing_ok=True)
    delete_cached_paper(str(paper.get("digest", "")), paper_id)
    shutil.rmtree(figure_directory(FIGURES_DIR, paper_id), ignore_errors=True)
    return {"deleted": True}


@app.get("/api/papers/{paper_id}/file")
def get_paper_file(paper_id: str):
    paper = read_paper(paper_id)
    pdf_path = paper_pdf_path(paper)
    return FileResponse(pdf_path, media_type="application/pdf", filename=paper["filename"])


@app.get("/api/papers/{paper_id}/figures")
def get_figures(paper_id: str):
    return figure_analysis_response(paper_id, read_paper(paper_id))




@app.get("/api/papers/{paper_id}/figures/{figure_id}/image")
def get_figure_image(paper_id: str, figure_id: str):
    paper = read_paper(paper_id)
    figure = next((item for item in paper.get("figures", []) if item.get("id") == figure_id), None)
    if not figure:
        raise HTTPException(status_code=404, detail="Figure not found.")

    image_file = Path(str(figure.get("image_file", ""))).name
    image_path = figure_directory(FIGURES_DIR, paper_id) / image_file
    if not image_path.exists():
        pdf_path = paper_pdf_path(paper)
        ensure_figure_images(pdf_path, FIGURES_DIR, paper_id, [figure])
        if paper.get("digest"):
            ensure_figure_images(pdf_path, CACHE_FIGURES_DIR, str(paper.get("digest")), [figure])

    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Figure image not found.")
    return FileResponse(image_path, media_type="image/jpeg")


@app.post("/api/papers/{paper_id}/chat")
async def chat_with_paper(paper_id: str, request: ChatRequest):
    paper = read_paper(paper_id)
    if paper.get("analysis_status") != "complete":
        raise HTTPException(status_code=409, detail="Analyze this paper before starting Chat.")
    messages = [
        {"role": message.role, "content": message.content}
        for message in request.messages
        if message.role in {"user", "assistant"} and message.content.strip()
    ]
    if not messages:
        raise HTTPException(status_code=400, detail="Send at least one message.")

    web_results = []
    if request.use_web:
        query = messages[-1]["content"]
        try:
            web_results = await asyncio.to_thread(search_web, query, 5)
        except Exception as error:
            web_results = [{"title": "Web search failed", "url": "", "snippet": str(error)}]

    figure_image_paths = selected_figure_image_paths(paper_id, paper, request.figure_context)
    try:
        return await asyncio.to_thread(
            answer_chat,
            paper,
            messages,
            web_results,
            paper.get("provider_used") or request.provider,
            request.citation_context,
            request.api_key,
            request.figure_context,
            paper.get("analysis_model") or request.model,
            "high",
            figure_image_paths,
        )
    except Exception as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@app.post("/api/papers/{paper_id}/explain")
async def explain_selection(paper_id: str, request: SelectionExplainRequest):
    paper = read_paper(paper_id)
    selected_text = request.selected_text.strip()
    if not selected_text:
        raise HTTPException(status_code=400, detail="Select text to explain.")
    if len(selected_text) > 700:
        raise HTTPException(status_code=400, detail="Selection is too long.")

    try:
        return await asyncio.to_thread(
            answer_selection_explanation,
            paper,
            selected_text,
            request.page_number,
            request.page_text,
            request.provider,
            request.api_key,
            request.model,
            request.reasoning_effort,
        )
    except Exception as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@app.get("/api/search")
async def search(query: str):
    try:
        results = await asyncio.to_thread(search_web, query, 8)
    except Exception as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return {"results": results}
