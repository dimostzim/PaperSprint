import json
import time

import fitz
from fastapi.testclient import TestClient

from app import main, paper_processing


def make_pdf_bytes(text: str = "Readable paper text.") -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def test_upload_rejects_unreadable_pdf_and_removes_file(tmp_path, monkeypatch):
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    monkeypatch.setattr(main, "PAPERS_DIR", papers_dir)
    main.PAPERS.clear()

    client = TestClient(main.app)
    response = client.post(
        "/api/upload",
        files={"file": ("bad.pdf", b"not a real pdf", "application/pdf")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Uploaded file is not a readable PDF."
    assert list(papers_dir.iterdir()) == []
    assert main.PAPERS == {}


def test_analyze_preserves_extracted_metadata_while_running(tmp_path, monkeypatch):
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "paper.pdf").write_bytes(make_pdf_bytes("This paper has extracted text ready for analysis."))
    monkeypatch.setattr(main, "PAPERS_DIR", papers_dir)
    main.PAPERS.clear()

    page_sizes = [{"page_number": 1, "width": 600, "height": 800}]
    sentences = [{"text": "This paper has extracted text ready for chat.", "page_number": 1}]
    main.PAPERS["paper-1"] = {
        "id": "paper-1",
        "filename": "paper.pdf",
        "stored_pdf": "paper.pdf",
        "title": "Readable paper",
        "overview": "PDF loaded.",
        "key_takeaways": [],
        "read_this_first": [],
        "glossary": [],
        "highlights": [],
        "figures": [],
        "figure_warnings": [],
        "figure_provider_used": "unknown",
        "citations": [],
        "questions": [],
        "provider_used": "not analyzed",
        "warnings": [],
        "page_sizes": page_sizes,
        "sentences": sentences,
        "full_text_chars": 120,
        "analysis_status": "ready",
        "analysis_error": "",
    }

    def close_background_task(coroutine):
        coroutine.close()

    monkeypatch.setattr(main.asyncio, "create_task", close_background_task)

    client = TestClient(main.app)
    response = client.post(
        "/api/papers/paper-1/analyze",
        json={"provider": "codex"},
    )

    assert response.status_code == 200
    assert main.PAPERS["paper-1"]["analysis_status"] == "analyzing"
    assert "reading_depth" not in main.PAPERS["paper-1"]
    assert main.PAPERS["paper-1"]["page_sizes"] == page_sizes
    assert main.PAPERS["paper-1"]["sentences"] == sentences
    assert main.PAPERS["paper-1"]["full_text_chars"] == 120


def test_analysis_api_has_no_reading_depth(tmp_path, monkeypatch):
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    monkeypatch.setattr(main, "PAPERS_DIR", papers_dir)
    main.PAPERS.clear()
    for index in range(1, 4):
        filename = f"paper-{index}.pdf"
        (papers_dir / filename).write_bytes(make_pdf_bytes(f"Readable paper {index}."))
        main.PAPERS[f"paper-{index}"] = {
            "id": f"paper-{index}", "filename": filename, "stored_pdf": filename,
            "title": "Paper", "analysis_status": "ready", "full_text_chars": 20,
            "narrative_sections": [], "manual_highlights": [], "figures": [], "citations": [],
        }

    def close_background_task(coroutine):
        coroutine.close()

    monkeypatch.setattr(main.asyncio, "create_task", close_background_task)
    client = TestClient(main.app)
    for index in range(1, 4):
        response = client.post(f"/api/papers/paper-{index}/analyze", json={"provider": "codex"})
        assert response.status_code == 200
        assert "reading_depth" not in response.json()


def test_reanalysis_lazily_restores_cached_paper_after_backend_reload(tmp_path, monkeypatch):
    papers_dir = tmp_path / "papers"
    figures_dir = tmp_path / "figures"
    cache_papers_dir = tmp_path / "cache-papers"
    cache_records_dir = tmp_path / "cache-records"
    cache_figures_dir = tmp_path / "cache-figures"
    for directory in (papers_dir, figures_dir, cache_papers_dir, cache_records_dir, cache_figures_dir):
        directory.mkdir()
    for name, value in (
        ("PAPERS_DIR", papers_dir),
        ("FIGURES_DIR", figures_dir),
        ("CACHE_PAPERS_DIR", cache_papers_dir),
        ("CACHE_RECORDS_DIR", cache_records_dir),
        ("CACHE_FIGURES_DIR", cache_figures_dir),
    ):
        monkeypatch.setattr(main, name, value)

    data = make_pdf_bytes("Figure 1 appears on the following page.")
    digest = main.file_digest(data)
    paper_id = digest[:12]
    (cache_papers_dir / f"{digest}.pdf").write_bytes(data)
    (cache_records_dir / f"{digest}.json").write_text(
        json.dumps(
            {
                "id": paper_id,
                "filename": "paper.pdf",
                "stored_pdf": "paper.pdf",
                "digest": digest,
                "analysis_version": main.ANALYSIS_VERSION,
                "citation_version": main.CITATION_VERSION,
                "title": "Cached paper",
                "analysis_status": "complete",
                "narrative_sections": [{"heading": "Result", "highlights": [{"id": "h1", "text": "Old analysis."}]}],
                "manual_highlights": [],
                "figures": [],
                "citations": [],
                "sentences": [],
                "full_text_chars": 42,
            }
        ),
        encoding="utf-8",
    )
    main.PAPERS.clear()

    def close_background_task(coroutine):
        coroutine.close()

    monkeypatch.setattr(main.asyncio, "create_task", close_background_task)

    response = TestClient(main.app).post(
        f"/api/papers/{paper_id}/analyze",
        json={"provider": "codex", "reanalyze": True},
    )

    assert response.status_code == 200
    assert response.json()["reanalysis_status"] == "analyzing"
    assert paper_id in main.PAPERS
    assert (papers_dir / f"{paper_id}-paper.pdf").exists()


def test_get_paper_file_restores_missing_session_pdf_from_cache(tmp_path, monkeypatch):
    papers_dir = tmp_path / "papers"
    cache_papers_dir = tmp_path / "cache-papers"
    papers_dir.mkdir()
    cache_papers_dir.mkdir()
    monkeypatch.setattr(main, "PAPERS_DIR", papers_dir)
    monkeypatch.setattr(main, "CACHE_PAPERS_DIR", cache_papers_dir)
    main.PAPERS.clear()

    data = make_pdf_bytes()
    digest = main.file_digest(data)
    (cache_papers_dir / f"{digest}.pdf").write_bytes(data)
    main.PAPERS["paper-1"] = {
        "id": "paper-1",
        "filename": "paper.pdf",
        "stored_pdf": "paper.pdf",
        "digest": digest,
    }

    client = TestClient(main.app)
    response = client.get("/api/papers/paper-1/file")

    assert response.status_code == 200
    assert response.content == data
    assert (papers_dir / "paper.pdf").read_bytes() == data


def test_analyze_restores_missing_session_pdf_from_cache(tmp_path, monkeypatch):
    papers_dir = tmp_path / "papers"
    cache_papers_dir = tmp_path / "cache-papers"
    papers_dir.mkdir()
    cache_papers_dir.mkdir()
    monkeypatch.setattr(main, "PAPERS_DIR", papers_dir)
    monkeypatch.setattr(main, "CACHE_PAPERS_DIR", cache_papers_dir)
    main.PAPERS.clear()

    data = make_pdf_bytes()
    digest = main.file_digest(data)
    (cache_papers_dir / f"{digest}.pdf").write_bytes(data)
    main.PAPERS["paper-1"] = {
        "id": "paper-1",
        "filename": "paper.pdf",
        "stored_pdf": "paper.pdf",
        "digest": digest,
        "title": "Readable paper",
        "overview": "PDF loaded.",
        "key_takeaways": [],
        "read_this_first": [],
        "glossary": [],
        "highlights": [],
        "figures": [],
        "figure_warnings": [],
        "figure_provider_used": "unknown",
        "citations": [],
        "questions": [],
        "provider_used": "not analyzed",
        "warnings": [],
        "page_sizes": [],
        "sentences": [],
        "full_text_chars": 120,
        "analysis_status": "ready",
        "analysis_error": "",
    }

    def close_background_task(coroutine):
        coroutine.close()

    monkeypatch.setattr(main.asyncio, "create_task", close_background_task)

    client = TestClient(main.app)
    response = client.post(
        "/api/papers/paper-1/analyze",
        json={"provider": "codex"},
    )

    assert response.status_code == 200
    assert main.PAPERS["paper-1"]["analysis_status"] == "analyzing"
    assert (papers_dir / "paper.pdf").read_bytes() == data


def test_upload_defers_citations_until_analysis(tmp_path, monkeypatch):
    papers_dir = tmp_path / "papers"
    figures_dir = tmp_path / "figures"
    cache_papers_dir = tmp_path / "cache-papers"
    cache_records_dir = tmp_path / "cache-records"
    cache_figures_dir = tmp_path / "cache-figures"
    for directory in (papers_dir, figures_dir, cache_papers_dir, cache_records_dir, cache_figures_dir):
        directory.mkdir()
    monkeypatch.setattr(main, "PAPERS_DIR", papers_dir)
    monkeypatch.setattr(main, "FIGURES_DIR", figures_dir)
    monkeypatch.setattr(main, "CACHE_PAPERS_DIR", cache_papers_dir)
    monkeypatch.setattr(main, "CACHE_RECORDS_DIR", cache_records_dir)
    monkeypatch.setattr(main, "CACHE_FIGURES_DIR", cache_figures_dir)
    main.PAPERS.clear()

    data = make_pdf_bytes("Prior work [1].\nReferences\n[1] A. Reader. 2022. Short Citation. CHI.")

    client = TestClient(main.app)
    response = client.post(
        "/api/upload",
        files={"file": ("paper.pdf", data, "application/pdf")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["citation_count"] == 0
    assert payload["citation_status"] == "pending"
    assert main.PAPERS[payload["id"]]["citations"] == []
    assert main.PAPERS[payload["id"]]["citation_version"] == 0


def test_finish_paper_analysis_generates_citations(tmp_path, monkeypatch):
    papers_dir = tmp_path / "papers"
    figures_dir = tmp_path / "figures"
    cache_papers_dir = tmp_path / "cache-papers"
    cache_records_dir = tmp_path / "cache-records"
    cache_figures_dir = tmp_path / "cache-figures"
    for directory in (papers_dir, figures_dir, cache_papers_dir, cache_records_dir, cache_figures_dir):
        directory.mkdir()
    monkeypatch.setattr(main, "PAPERS_DIR", papers_dir)
    monkeypatch.setattr(main, "FIGURES_DIR", figures_dir)
    monkeypatch.setattr(main, "CACHE_PAPERS_DIR", cache_papers_dir)
    monkeypatch.setattr(main, "CACHE_RECORDS_DIR", cache_records_dir)
    monkeypatch.setattr(main, "CACHE_FIGURES_DIR", cache_figures_dir)
    main.PAPERS.clear()

    data = make_pdf_bytes("Prior work [1].\nReferences\n[1] A. Reader. 2022. Short Citation. CHI.")
    pdf_path = papers_dir / "paper.pdf"
    pdf_path.write_bytes(data)
    digest = main.file_digest(data)
    main.PAPERS["paper-1"] = {
        "id": "paper-1",
        "filename": "paper.pdf",
        "stored_pdf": "paper.pdf",
        "digest": digest,
        "title": "Readable paper",
        "figures": [],
    }

    def fake_analyze_paper(*args, **kwargs):
        return {
            "title": "Readable paper",
            "overview": "Analyzed.",
            "background_notes": [],
            "key_takeaways": [],
            "not_shown": [],
            "code_availability": [],
            "reviewer_questions": [],
            "read_this_first": [],
            "glossary": [],
            "highlights": [],
            "questions": [],
            "provider_used": "test",
            "warnings": [],
        }

    captured = {}

    def fake_validate_citations(citations, provider, api_key=None, model=None, reasoning_effort=None):
        captured["provider"] = provider
        return citations

    monkeypatch.setattr(main, "analyze_paper", fake_analyze_paper)
    monkeypatch.setattr(main, "validate_citations", fake_validate_citations)

    main.finish_paper_analysis(pdf_path, "paper-1", "paper.pdf", "codex", digest)

    paper = main.PAPERS["paper-1"]
    assert captured["provider"] == "codex"
    assert paper["analysis_status"] == "complete"
    assert paper["citation_status"] == "complete"
    assert paper["citation_version"] == main.CITATION_VERSION
    assert paper["citations"][0]["label"] == "[1]"
    assert paper["citations"][0]["contexts"][0]["marker"] == "[1]"
    cached_record = json.loads((cache_records_dir / f"{digest}.json").read_text(encoding="utf-8"))
    assert cached_record["citation_status"] == "complete"
    assert cached_record["citations"][0]["label"] == "[1]"


def test_reanalysis_replaces_generated_sequence_and_preserves_manual_highlights(tmp_path, monkeypatch):
    papers_dir = tmp_path / "papers"
    cache_papers_dir = tmp_path / "cache-papers"
    cache_records_dir = tmp_path / "cache-records"
    cache_figures_dir = tmp_path / "cache-figures"
    figures_dir = tmp_path / "figures"
    for directory in (papers_dir, cache_papers_dir, cache_records_dir, cache_figures_dir, figures_dir):
        directory.mkdir()
    monkeypatch.setattr(main, "PAPERS_DIR", papers_dir)
    monkeypatch.setattr(main, "CACHE_PAPERS_DIR", cache_papers_dir)
    monkeypatch.setattr(main, "CACHE_RECORDS_DIR", cache_records_dir)
    monkeypatch.setattr(main, "CACHE_FIGURES_DIR", cache_figures_dir)
    monkeypatch.setattr(main, "FIGURES_DIR", figures_dir)
    data = make_pdf_bytes("New generated evidence appears here.")
    pdf_path = papers_dir / "paper.pdf"
    pdf_path.write_bytes(data)
    main.PAPERS.clear()
    main.PAPERS["paper-1"] = {
        "id": "paper-1", "filename": "paper.pdf", "stored_pdf": "paper.pdf", "digest": main.file_digest(data),
        "title": "Paper", "manual_highlights": [{"id": "manual-1", "label": "problem", "snippet": "My note."}],
        "narrative_sections": [{"heading": "Old", "highlights": [{"id": "old", "text": "Old.", "source": {"type": "text", "anchor": "Old.", "page_hint": 1}}]}],
        "figures": [],
    }

    monkeypatch.setattr(main, "prepare_visuals", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(main, "analyze_paper", lambda *_args, **_kwargs: {
        "title": "Paper", "narrative_sections": [
            {"heading": "New", "highlights": [{"id": "new", "label": "result", "text": "New synthesized result.", "source": {"type": "text", "anchor": "New generated evidence appears here.", "page_hint": 1}, "page_number": 1, "rects": [[1, 1, 2, 2]], "navigation_available": True}]}
        ], "figures": [], "provider_used": "test",
    })
    monkeypatch.setattr(main, "analyze_citations_for_paper", lambda *_args, **_kwargs: [])

    main.finish_paper_analysis(pdf_path, "paper-1", "paper.pdf", "codex", main.file_digest(data))

    paper = main.PAPERS["paper-1"]
    assert paper["narrative_sections"][0]["highlights"][0]["id"] == "new"
    assert paper["manual_highlights"] == [{"id": "manual-1", "label": "problem", "snippet": "My note."}]
    assert [item["id"] for item in main.public_paper(paper, True)["highlights"]] == ["new"]
    assert "reading_depth" not in paper


def test_upload_uses_cached_completed_analysis(tmp_path, monkeypatch):
    papers_dir = tmp_path / "papers"
    figures_dir = tmp_path / "figures"
    cache_papers_dir = tmp_path / "cache-papers"
    cache_records_dir = tmp_path / "cache-records"
    cache_figures_dir = tmp_path / "cache-figures"
    for directory in (papers_dir, figures_dir, cache_papers_dir, cache_records_dir, cache_figures_dir):
        directory.mkdir()
    monkeypatch.setattr(main, "PAPERS_DIR", papers_dir)
    monkeypatch.setattr(main, "FIGURES_DIR", figures_dir)
    monkeypatch.setattr(main, "CACHE_PAPERS_DIR", cache_papers_dir)
    monkeypatch.setattr(main, "CACHE_RECORDS_DIR", cache_records_dir)
    monkeypatch.setattr(main, "CACHE_FIGURES_DIR", cache_figures_dir)
    main.PAPERS.clear()

    data = make_pdf_bytes()
    digest = main.file_digest(data)
    cached_pdf = cache_papers_dir / f"{digest}.pdf"
    cached_pdf.write_bytes(data)
    cached_figure_dir = main.figure_directory(cache_figures_dir, digest)
    cached_figure_dir.mkdir()
    (cached_figure_dir / "p1-1.jpg").write_bytes(b"figure")
    cached_record = {
        "id": "old-id",
        "filename": "old.pdf",
        "stored_pdf": "old.pdf",
        "digest": digest,
        "analysis_version": main.ANALYSIS_VERSION,
        "title": "Cached analysis",
        "overview": "Already analyzed.",
        "key_takeaways": ["Cached takeaway"],
        "read_this_first": [],
        "glossary": [],
        "reading_depth": "Balanced",
        "narrative_sections": [{"heading": "Argument", "highlights": [{"id": "h1", "label": "problem", "snippet": "Cached highlight", "reason": "Cached"}]}],
        "manual_highlights": [],
        "figures": [{"id": "p1-1", "image_file": "p1-1.jpg", "label": "Figure 1"}],
        "figure_warnings": [],
        "figure_provider_used": "codex",
        "citations": [],
        "questions": [],
        "provider_used": "codex",
        "warnings": [],
        "page_sizes": [],
        "sentences": [],
        "full_text_chars": 42,
        "analysis_status": "complete",
        "analysis_error": "",
    }
    (cache_records_dir / f"{digest}.json").write_text(json.dumps(cached_record), encoding="utf-8")

    client = TestClient(main.app)
    response = client.post(
        "/api/upload",
        files={"file": ("paper.pdf", data, "application/pdf")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == digest[:12]
    assert payload["title"] == "Cached analysis"
    assert payload["analysis_status"] == "complete"
    assert payload["highlight_count"] == 1
    assert payload["figure_count"] == 1
    assert main.PAPERS[digest[:12]]["figures"][0]["id"] == "p1-1"
    assert (main.figure_directory(figures_dir, digest[:12]) / "p1-1.jpg").exists()
    assert (papers_dir / f"{digest[:12]}-paper.pdf").exists()


def test_public_paper_keeps_figure_bbox_source_navigable():
    payload = main.public_paper(
        {
            "id": "paper-1",
            "filename": "paper.pdf",
            "title": "Paper",
            "narrative_sections": [
                {
                    "heading": "Results",
                    "highlights": [
                        {
                            "id": "figure-result",
                            "text": "The chart shows the main result.",
                            "label": "result",
                            "page_number": 2,
                            "rects": [],
                            "source": {"type": "figure", "bbox_pct": [10, 20, 60, 80]},
                        }
                    ],
                }
            ],
            "figures": [],
            "citations": [],
        },
        include_details=True,
    )

    assert payload["highlights"][0]["navigation_available"] is True


def test_public_paper_counts_only_citations_with_contexts():
    payload = main.public_paper(
        {
            "id": "paper-1",
            "filename": "paper.pdf",
            "title": "Paper",
            "highlights": [],
            "figures": [],
            "citations": [
                {"label": "Used", "contexts": [{"marker": "Used 2024"}]},
                {"label": "Reference only", "contexts": []},
                {"label": "Missing contexts"},
            ],
        }
    )

    assert payload["citation_count"] == 1


def test_upload_refreshes_stale_cached_citations(tmp_path, monkeypatch):
    papers_dir = tmp_path / "papers"
    figures_dir = tmp_path / "figures"
    cache_papers_dir = tmp_path / "cache-papers"
    cache_records_dir = tmp_path / "cache-records"
    cache_figures_dir = tmp_path / "cache-figures"
    for directory in (papers_dir, figures_dir, cache_papers_dir, cache_records_dir, cache_figures_dir):
        directory.mkdir()
    monkeypatch.setattr(main, "PAPERS_DIR", papers_dir)
    monkeypatch.setattr(main, "FIGURES_DIR", figures_dir)
    monkeypatch.setattr(main, "CACHE_PAPERS_DIR", cache_papers_dir)
    monkeypatch.setattr(main, "CACHE_RECORDS_DIR", cache_records_dir)
    monkeypatch.setattr(main, "CACHE_FIGURES_DIR", cache_figures_dir)
    main.PAPERS.clear()

    data = make_pdf_bytes()
    digest = main.file_digest(data)
    (cache_papers_dir / f"{digest}.pdf").write_bytes(data)
    (cache_records_dir / f"{digest}.json").write_text(
        json.dumps(
            {
                "id": "old-id",
                "filename": "old.pdf",
                "stored_pdf": "old.pdf",
                "digest": digest,
                "analysis_version": main.ANALYSIS_VERSION,
                "title": "Cached analysis",
                "overview": "Already analyzed.",
                "key_takeaways": [],
                "read_this_first": [],
                "glossary": [],
                "highlights": [],
                "figures": [],
                "figure_warnings": [],
                "figure_provider_used": "unknown",
                "citations": [{"label": "old citation"}],
                "questions": [],
                "provider_used": "codex",
                "warnings": [],
                "page_sizes": [],
                "sentences": [],
                "full_text_chars": 42,
                "analysis_status": "complete",
                "analysis_error": "",
            }
        ),
        encoding="utf-8",
    )

    def fake_extract_pdf(pdf_path):
        return {"pdf_path": pdf_path}

    def fake_extract_citations(extracted):
        return [{"label": "new citation", "contexts": []}]

    def fake_ground_citation_rects(pdf_path, citations):
        return citations

    monkeypatch.setattr(main, "extract_pdf", fake_extract_pdf)
    monkeypatch.setattr(main, "extract_citations", fake_extract_citations)
    monkeypatch.setattr(main, "ground_citation_rects", fake_ground_citation_rects)

    client = TestClient(main.app)
    response = client.post(
        "/api/upload",
        files={"file": ("paper.pdf", data, "application/pdf")},
    )

    assert response.status_code == 200
    paper = main.PAPERS[digest[:12]]
    assert paper["citations"] == [{"label": "new citation", "contexts": []}]
    assert paper["citation_version"] == main.CITATION_VERSION
    refreshed_record = json.loads((cache_records_dir / f"{digest}.json").read_text(encoding="utf-8"))
    assert refreshed_record["citations"] == [{"label": "new citation", "contexts": []}]
    assert refreshed_record["citation_version"] == main.CITATION_VERSION


def test_refresh_cache_skips_unreadable_cached_pdf(tmp_path, monkeypatch):
    papers_dir = tmp_path / "papers"
    figures_dir = tmp_path / "figures"
    cache_papers_dir = tmp_path / "cache-papers"
    cache_records_dir = tmp_path / "cache-records"
    cache_figures_dir = tmp_path / "cache-figures"
    for directory in (papers_dir, figures_dir, cache_papers_dir, cache_records_dir, cache_figures_dir):
        directory.mkdir()
    monkeypatch.setattr(main, "PAPERS_DIR", papers_dir)
    monkeypatch.setattr(main, "FIGURES_DIR", figures_dir)
    monkeypatch.setattr(main, "CACHE_PAPERS_DIR", cache_papers_dir)
    monkeypatch.setattr(main, "CACHE_RECORDS_DIR", cache_records_dir)
    monkeypatch.setattr(main, "CACHE_FIGURES_DIR", cache_figures_dir)
    main.PAPERS.clear()

    valid_data = make_pdf_bytes()
    valid_digest = main.file_digest(valid_data)
    invalid_digest = "bad-digest"
    (cache_papers_dir / f"{valid_digest}.pdf").write_bytes(valid_data)
    (cache_papers_dir / f"{invalid_digest}.pdf").write_bytes(b"")

    base_record = {
        "analysis_version": main.ANALYSIS_VERSION,
        "overview": "Cached.",
        "key_takeaways": [],
        "read_this_first": [],
        "glossary": [],
        "highlights": [],
        "figures": [],
        "figure_warnings": [],
        "figure_provider_used": "unknown",
        "citations": [],
        "citation_version": main.CITATION_VERSION,
        "questions": [],
        "provider_used": "codex",
        "warnings": [],
        "page_sizes": [],
        "sentences": [],
        "full_text_chars": 42,
        "analysis_status": "complete",
        "analysis_error": "",
    }
    (cache_records_dir / f"{valid_digest}.json").write_text(
        json.dumps({**base_record, "id": "old-good", "filename": "good.pdf", "stored_pdf": "good.pdf", "digest": valid_digest, "title": "Good"}),
        encoding="utf-8",
    )
    (cache_records_dir / f"{invalid_digest}.json").write_text(
        json.dumps({**base_record, "id": "old-bad", "filename": "bad.pdf", "stored_pdf": "bad.pdf", "digest": invalid_digest, "title": "Bad", "citation_version": 0}),
        encoding="utf-8",
    )

    client = TestClient(main.app)
    response = client.post("/api/papers/refresh-cache")

    assert response.status_code == 200
    assert response.json()["loaded_count"] == 1
    assert list(main.PAPERS) == [valid_digest[:12]]


def test_cache_paper_persists_figure_records_and_images(tmp_path, monkeypatch):
    papers_dir = tmp_path / "papers"
    figures_dir = tmp_path / "figures"
    cache_papers_dir = tmp_path / "cache-papers"
    cache_records_dir = tmp_path / "cache-records"
    cache_figures_dir = tmp_path / "cache-figures"
    for directory in (papers_dir, figures_dir, cache_papers_dir, cache_records_dir, cache_figures_dir):
        directory.mkdir()
    monkeypatch.setattr(main, "PAPERS_DIR", papers_dir)
    monkeypatch.setattr(main, "FIGURES_DIR", figures_dir)
    monkeypatch.setattr(main, "CACHE_PAPERS_DIR", cache_papers_dir)
    monkeypatch.setattr(main, "CACHE_RECORDS_DIR", cache_records_dir)
    monkeypatch.setattr(main, "CACHE_FIGURES_DIR", cache_figures_dir)

    pdf_path = papers_dir / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    figure_dir = main.figure_directory(figures_dir, "paper-1")
    figure_dir.mkdir()
    (figure_dir / "p1-1.jpg").write_bytes(b"figure")
    paper = {
        "id": "paper-1",
        "filename": "paper.pdf",
        "stored_pdf": "paper.pdf",
        "digest": "digest-1",
        "title": "Readable paper",
        "figures": [{"id": "p1-1", "image_file": "p1-1.jpg", "label": "Figure 1"}],
        "figure_warnings": [],
        "figure_provider_used": "codex",
    }

    main.cache_paper(paper, pdf_path)

    cached_record = json.loads((cache_records_dir / "digest-1.json").read_text(encoding="utf-8"))
    assert cached_record["figures"][0]["id"] == "p1-1"
    assert cached_record["figure_provider_used"] == "codex"
    assert (main.figure_directory(cache_figures_dir, "digest-1") / "p1-1.jpg").exists()


def test_refresh_cache_loads_cached_papers_and_figures(tmp_path, monkeypatch):
    papers_dir = tmp_path / "papers"
    figures_dir = tmp_path / "figures"
    cache_papers_dir = tmp_path / "cache-papers"
    cache_records_dir = tmp_path / "cache-records"
    cache_figures_dir = tmp_path / "cache-figures"
    for directory in (papers_dir, figures_dir, cache_papers_dir, cache_records_dir, cache_figures_dir):
        directory.mkdir()
    monkeypatch.setattr(main, "PAPERS_DIR", papers_dir)
    monkeypatch.setattr(main, "FIGURES_DIR", figures_dir)
    monkeypatch.setattr(main, "CACHE_PAPERS_DIR", cache_papers_dir)
    monkeypatch.setattr(main, "CACHE_RECORDS_DIR", cache_records_dir)
    monkeypatch.setattr(main, "CACHE_FIGURES_DIR", cache_figures_dir)
    main.PAPERS.clear()

    data = make_pdf_bytes()
    digest = main.file_digest(data)
    (cache_papers_dir / f"{digest}.pdf").write_bytes(data)
    cached_figure_dir = main.figure_directory(cache_figures_dir, digest)
    cached_figure_dir.mkdir()
    (cached_figure_dir / "p1-1.jpg").write_bytes(b"figure")
    cached_record = {
        "id": "old-id",
        "filename": "paper.pdf",
        "stored_pdf": "old.pdf",
        "digest": digest,
        "analysis_version": main.ANALYSIS_VERSION,
        "title": "Cached paper",
        "overview": "Already analyzed.",
        "key_takeaways": ["Cached takeaway"],
        "read_this_first": [],
        "glossary": [],
        "reading_depth": "Balanced",
        "narrative_sections": [{"heading": "Argument", "highlights": [{"id": "h1", "label": "problem", "snippet": "Cached highlight", "reason": "Cached"}]}],
        "manual_highlights": [],
        "figures": [{"id": "p1-1", "image_file": "p1-1.jpg", "label": "Figure 1"}],
        "figure_warnings": [],
        "figure_provider_used": "codex",
        "citations": [],
        "questions": [],
        "provider_used": "codex",
        "warnings": [],
        "page_sizes": [],
        "sentences": [],
        "full_text_chars": 42,
        "analysis_status": "complete",
        "analysis_error": "",
    }
    (cache_records_dir / f"{digest}.json").write_text(json.dumps(cached_record), encoding="utf-8")

    client = TestClient(main.app)
    response = client.post("/api/papers/refresh-cache")

    assert response.status_code == 200
    payload = response.json()
    assert payload["loaded_count"] == 1
    assert payload["papers"][0]["id"] == digest[:12]
    assert payload["papers"][0]["highlight_count"] == 1
    assert payload["papers"][0]["figure_count"] == 1
    assert (papers_dir / f"{digest[:12]}-paper.pdf").exists()
    assert (main.figure_directory(figures_dir, digest[:12]) / "p1-1.jpg").exists()


def test_refresh_cache_repairs_missing_cached_figure_images(tmp_path, monkeypatch):
    papers_dir = tmp_path / "papers"
    figures_dir = tmp_path / "figures"
    cache_papers_dir = tmp_path / "cache-papers"
    cache_records_dir = tmp_path / "cache-records"
    cache_figures_dir = tmp_path / "cache-figures"
    for directory in (papers_dir, figures_dir, cache_papers_dir, cache_records_dir, cache_figures_dir):
        directory.mkdir()
    monkeypatch.setattr(main, "PAPERS_DIR", papers_dir)
    monkeypatch.setattr(main, "FIGURES_DIR", figures_dir)
    monkeypatch.setattr(main, "CACHE_PAPERS_DIR", cache_papers_dir)
    monkeypatch.setattr(main, "CACHE_RECORDS_DIR", cache_records_dir)
    monkeypatch.setattr(main, "CACHE_FIGURES_DIR", cache_figures_dir)
    main.PAPERS.clear()

    data = make_pdf_bytes("Figure 1: Repairable visual")
    digest = main.file_digest(data)
    (cache_papers_dir / f"{digest}.pdf").write_bytes(data)
    cached_record = {
        "id": "old-id",
        "filename": "paper.pdf",
        "stored_pdf": "old.pdf",
        "digest": digest,
        "analysis_version": main.ANALYSIS_VERSION,
        "title": "Cached paper",
        "overview": "Already analyzed.",
        "key_takeaways": [],
        "read_this_first": [],
        "glossary": [],
        "highlights": [],
        "figures": [
            {
                "id": "p1-1",
                "page_number": 1,
                "image_file": "p1-1.jpg",
                "bbox_pct": [0, 0, 100, 100],
                "label": "Figure 1",
            }
        ],
        "figure_warnings": [],
        "figure_provider_used": "codex",
        "citations": [],
        "questions": [],
        "provider_used": "codex",
        "warnings": [],
        "page_sizes": [],
        "sentences": [],
        "full_text_chars": 42,
        "analysis_status": "complete",
        "analysis_error": "",
    }
    (cache_records_dir / f"{digest}.json").write_text(json.dumps(cached_record), encoding="utf-8")

    client = TestClient(main.app)
    response = client.post("/api/papers/refresh-cache")

    assert response.status_code == 200
    assert (main.figure_directory(cache_figures_dir, digest) / "p1-1.jpg").exists()
    assert (main.figure_directory(figures_dir, digest[:12]) / "p1-1.jpg").exists()


def test_upload_ignores_stale_cached_analysis(tmp_path, monkeypatch):
    papers_dir = tmp_path / "papers"
    figures_dir = tmp_path / "figures"
    cache_papers_dir = tmp_path / "cache-papers"
    cache_records_dir = tmp_path / "cache-records"
    cache_figures_dir = tmp_path / "cache-figures"
    for directory in (papers_dir, figures_dir, cache_papers_dir, cache_records_dir, cache_figures_dir):
        directory.mkdir()
    monkeypatch.setattr(main, "PAPERS_DIR", papers_dir)
    monkeypatch.setattr(main, "FIGURES_DIR", figures_dir)
    monkeypatch.setattr(main, "CACHE_PAPERS_DIR", cache_papers_dir)
    monkeypatch.setattr(main, "CACHE_RECORDS_DIR", cache_records_dir)
    monkeypatch.setattr(main, "CACHE_FIGURES_DIR", cache_figures_dir)
    main.PAPERS.clear()

    data = make_pdf_bytes()
    digest = main.file_digest(data)
    (cache_papers_dir / f"{digest}.pdf").write_bytes(data)
    cached_figure_dir = main.figure_directory(cache_figures_dir, digest)
    cached_figure_dir.mkdir()
    (cached_figure_dir / "p1-1.jpg").write_bytes(b"figure")
    stale_record = {
        "id": "old-id",
        "filename": "old.pdf",
        "stored_pdf": "old.pdf",
        "digest": digest,
        "analysis_version": main.ANALYSIS_VERSION - 1,
        "title": "Stale analysis",
        "highlights": [{"label": "goal", "snippet": "Bad cached highlight", "reason": ""}],
        "figures": [{"id": "p1-1", "image_file": "p1-1.jpg", "label": "Figure 1"}],
        "figure_warnings": [],
        "figure_provider_used": "codex",
        "analysis_status": "complete",
    }
    (cache_records_dir / f"{digest}.json").write_text(json.dumps(stale_record), encoding="utf-8")

    client = TestClient(main.app)
    response = client.post(
        "/api/upload",
        files={"file": ("paper.pdf", data, "application/pdf")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["analysis_status"] == "ready"
    assert payload["title"] != "Stale analysis"
    assert payload["highlight_count"] == 0
    assert payload["figure_count"] == 1
    assert main.PAPERS[digest[:12]]["figures"][0]["id"] == "p1-1"


def test_generated_highlights_are_immutable_but_manual_highlights_can_be_deleted():
    main.PAPERS.clear()
    main.PAPERS["paper-1"] = {
        "id": "paper-1", "filename": "paper.pdf", "title": "Paper",
        "narrative_sections": [{"heading": "Narrative", "highlights": [{"id": "h1", "text": "Generated."}]}],
        "manual_highlights": [{"id": "manual-1", "snippet": "Mine."}],
        "figures": [], "citations": [], "analysis_status": "complete",
    }
    client = TestClient(main.app)

    generated = client.delete("/api/papers/paper-1/highlights/h1?source=generated")
    manual = client.delete("/api/papers/paper-1/highlights/manual-1?source=manual")

    assert generated.status_code == 409
    assert main.PAPERS["paper-1"]["narrative_sections"][0]["highlights"][0]["id"] == "h1"
    assert manual.status_code == 200
    assert main.PAPERS["paper-1"]["manual_highlights"] == []


def test_delete_paper_removes_session_files(tmp_path, monkeypatch):
    papers_dir = tmp_path / "papers"
    figures_dir = tmp_path / "figures"
    cache_papers_dir = tmp_path / "cache-papers"
    cache_records_dir = tmp_path / "cache-records"
    cache_figures_dir = tmp_path / "cache-figures"
    papers_dir.mkdir()
    figures_dir.mkdir()
    cache_papers_dir.mkdir()
    cache_records_dir.mkdir()
    cache_figures_dir.mkdir()
    pdf_path = papers_dir / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    digest = "abc123def456"
    cached_pdf = cache_papers_dir / f"{digest}.pdf"
    cached_record = cache_records_dir / f"{digest}.json"
    cached_pdf.write_bytes(b"%PDF-1.4\n")
    cached_record.write_text("{}", encoding="utf-8")
    cached_figures = main.figure_directory(cache_figures_dir, digest)
    cached_figures.mkdir()
    (cached_figures / "figure.jpg").write_bytes(b"cached image")
    figure_dir = main.figure_directory(figures_dir, "paper-1")
    figure_dir.mkdir()
    (figure_dir / "figure.jpg").write_bytes(b"image")
    monkeypatch.setattr(main, "PAPERS_DIR", papers_dir)
    monkeypatch.setattr(main, "FIGURES_DIR", figures_dir)
    monkeypatch.setattr(main, "CACHE_PAPERS_DIR", cache_papers_dir)
    monkeypatch.setattr(main, "CACHE_RECORDS_DIR", cache_records_dir)
    monkeypatch.setattr(main, "CACHE_FIGURES_DIR", cache_figures_dir)
    main.PAPERS.clear()
    main.PAPERS["paper-1"] = {
        "id": "paper-1",
        "filename": "paper.pdf",
        "stored_pdf": "paper.pdf",
        "digest": digest,
        "title": "Readable paper",
    }

    client = TestClient(main.app)
    response = client.delete("/api/papers/paper-1")

    assert response.status_code == 200
    assert response.json() == {"deleted": True}
    assert "paper-1" not in main.PAPERS
    assert not pdf_path.exists()
    assert not figure_dir.exists()
    assert not cached_pdf.exists()
    assert not cached_record.exists()
    assert not cached_figures.exists()


def test_delete_missing_paper_is_idempotent(tmp_path, monkeypatch):
    figures_dir = tmp_path / "figures"
    cache_papers_dir = tmp_path / "cache-papers"
    cache_records_dir = tmp_path / "cache-records"
    cache_figures_dir = tmp_path / "cache-figures"
    figures_dir.mkdir()
    cache_papers_dir.mkdir()
    cache_records_dir.mkdir()
    cache_figures_dir.mkdir()
    figure_dir = main.figure_directory(figures_dir, "missing-paper")
    figure_dir.mkdir()
    cached_pdf = cache_papers_dir / "missing-paper1234567890.pdf"
    cached_record = cache_records_dir / "missing-paper1234567890.json"
    cached_pdf.write_bytes(b"%PDF-1.4\n")
    cached_record.write_text("{}", encoding="utf-8")
    cached_figures = main.figure_directory(cache_figures_dir, "missing-paper")
    cached_figures.mkdir()
    monkeypatch.setattr(main, "FIGURES_DIR", figures_dir)
    monkeypatch.setattr(main, "CACHE_PAPERS_DIR", cache_papers_dir)
    monkeypatch.setattr(main, "CACHE_RECORDS_DIR", cache_records_dir)
    monkeypatch.setattr(main, "CACHE_FIGURES_DIR", cache_figures_dir)
    main.PAPERS.clear()

    client = TestClient(main.app)
    response = client.delete("/api/papers/missing-paper")

    assert response.status_code == 200
    assert response.json() == {"deleted": False}
    assert not figure_dir.exists()
    assert not cached_pdf.exists()
    assert not cached_record.exists()
    assert not cached_figures.exists()


def test_update_highlights_persists_to_cache(tmp_path, monkeypatch):
    papers_dir = tmp_path / "papers"
    figures_dir = tmp_path / "figures"
    cache_papers_dir = tmp_path / "cache-papers"
    cache_records_dir = tmp_path / "cache-records"
    cache_figures_dir = tmp_path / "cache-figures"
    for directory in (papers_dir, figures_dir, cache_papers_dir, cache_records_dir, cache_figures_dir):
        directory.mkdir()
    monkeypatch.setattr(main, "PAPERS_DIR", papers_dir)
    monkeypatch.setattr(main, "FIGURES_DIR", figures_dir)
    monkeypatch.setattr(main, "CACHE_PAPERS_DIR", cache_papers_dir)
    monkeypatch.setattr(main, "CACHE_RECORDS_DIR", cache_records_dir)
    monkeypatch.setattr(main, "CACHE_FIGURES_DIR", cache_figures_dir)
    main.PAPERS.clear()

    pdf_path = papers_dir / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    main.PAPERS["paper-1"] = {
        "id": "paper-1",
        "filename": "paper.pdf",
        "stored_pdf": "paper.pdf",
        "digest": "digest-1",
        "title": "Readable paper",
        "highlights": [{"label": "goal", "snippet": "Old highlight", "reason": ""}],
        "figures": [],
        "figure_warnings": [],
        "figure_provider_used": "unknown",
        "citations": [],
        "page_sizes": [],
        "analysis_status": "complete",
    }

    client = TestClient(main.app)
    response = client.put(
        "/api/papers/paper-1/highlights",
        json={
            "highlights": [
                {
                    "label": "Custom Finding",
                    "snippet": "This manually selected sentence should stay highlighted.",
                    "reason": "manual",
                    "comment": "This explains why the selected sentence matters.",
                    "page_number": 2,
                    "rects": [[10, 20, 100, 32]],
                    "color": "#bb66cc",
                }
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["highlight_count"] == 0
    assert payload["manual_highlights"][0]["id"].startswith("manual-")
    assert payload["manual_highlights"][0]["label"] == "custom finding"
    assert payload["manual_highlights"][0]["color"] == "#bb66cc"
    assert payload["manual_highlights"][0]["comment"] == "This explains why the selected sentence matters."
    cached_record = json.loads((cache_records_dir / "digest-1.json").read_text(encoding="utf-8"))
    assert cached_record["manual_highlights"][0]["snippet"] == "This manually selected sentence should stay highlighted."
    assert cached_record["manual_highlights"][0]["color"] == "#bb66cc"
    assert cached_record["manual_highlights"][0]["comment"] == "This explains why the selected sentence matters."


def test_update_manual_highlight_regrounds_to_selected_page(tmp_path, monkeypatch):
    papers_dir = tmp_path / "papers"
    figures_dir = tmp_path / "figures"
    cache_papers_dir = tmp_path / "cache-papers"
    cache_records_dir = tmp_path / "cache-records"
    cache_figures_dir = tmp_path / "cache-figures"
    for directory in (papers_dir, figures_dir, cache_papers_dir, cache_records_dir, cache_figures_dir):
        directory.mkdir()
    monkeypatch.setattr(main, "PAPERS_DIR", papers_dir)
    monkeypatch.setattr(main, "FIGURES_DIR", figures_dir)
    monkeypatch.setattr(main, "CACHE_PAPERS_DIR", cache_papers_dir)
    monkeypatch.setattr(main, "CACHE_RECORDS_DIR", cache_records_dir)
    monkeypatch.setattr(main, "CACHE_FIGURES_DIR", cache_figures_dir)
    main.PAPERS.clear()

    snippet = "Repeated exact highlight target for manual grounding."
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), snippet)
    doc.new_page().insert_text((72, 144), snippet)
    pdf_path = papers_dir / "paper.pdf"
    doc.save(pdf_path)
    doc.close()

    main.PAPERS["paper-1"] = {
        "id": "paper-1",
        "filename": "paper.pdf",
        "stored_pdf": "paper.pdf",
        "digest": "digest-1",
        "title": "Readable paper",
        "highlights": [],
        "figures": [],
        "figure_warnings": [],
        "figure_provider_used": "unknown",
        "citations": [],
        "page_sizes": [],
        "analysis_status": "complete",
    }

    client = TestClient(main.app)
    response = client.put(
        "/api/papers/paper-1/highlights",
        json={
            "highlights": [
                {
                    "label": "goal",
                    "snippet": snippet,
                    "reason": "manual",
                    "page_number": 2,
                    "rects": [[1, 1, 2, 2]],
                    "reground": True,
                }
            ]
        },
    )

    assert response.status_code == 200
    highlight = response.json()["manual_highlights"][0]
    assert highlight["page_number"] == 2
    assert highlight["rects"] != [[1, 1, 2, 2]]
    assert highlight["rects"][0][1] > 100


def test_analysis_api_persists_synthesized_narrative_and_unavailable_source(tmp_path, monkeypatch):
    papers_dir = tmp_path / "papers"; figures_dir = tmp_path / "figures"
    cache_papers_dir = tmp_path / "cache-papers"; cache_records_dir = tmp_path / "cache-records"; cache_figures_dir = tmp_path / "cache-figures"
    for directory in (papers_dir, figures_dir, cache_papers_dir, cache_records_dir, cache_figures_dir): directory.mkdir()
    for name, value in (("PAPERS_DIR", papers_dir), ("FIGURES_DIR", figures_dir), ("CACHE_PAPERS_DIR", cache_papers_dir), ("CACHE_RECORDS_DIR", cache_records_dir), ("CACHE_FIGURES_DIR", cache_figures_dir)):
        monkeypatch.setattr(main, name, value)
    monkeypatch.setattr(main, "analyze_citations_for_paper", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(main, "prepare_visuals", lambda *_args, **_kwargs: [])
    main.PAPERS.clear()
    source = "The paper reports evidence on the second page."
    doc = fitz.open(); doc.new_page().insert_text((72,72), "Introduction."); doc.new_page().insert_text((72,72), source); data=doc.tobytes(); doc.close()

    def fake_run_ai(*_args, **_kwargs):
        return json.dumps({"title":"Narrative paper","narrative_sections":[{"heading":"Evidence","highlights":[
            {"id":"h1","text":"The evaluation supports the proposed approach.","label":"result","source":{"type":"text","anchor":source,"page_hint":2}},
            {"id":"h2","text":"A second synthesized point remains useful without navigation.","label":"limitation","source":{"type":"text","anchor":"Unlocatable but structurally valid anchor.","page_hint":2}}
        ]}],"figures":[]}), "test"
    monkeypatch.setattr("app.ai.run_ai", fake_run_ai)
    client=TestClient(main.app)
    uploaded=client.post("/api/upload",files={"file":("paper.pdf",data,"application/pdf")}).json()
    payload=client.post(f"/api/papers/{uploaded['id']}/analyze",json={"provider":"codex"}).json()
    for _ in range(50):
        if payload["analysis_status"] != "analyzing": break
        time.sleep(.01); payload=client.get(f"/api/papers/{uploaded['id']}").json()
    assert payload["analysis_status"] == "complete"
    assert [item["text"] for item in payload["highlights"]] == ["The evaluation supports the proposed approach.", "A second synthesized point remains useful without navigation."]
    assert [item["navigation_available"] for item in payload["highlights"]] == [True, False]
    assert "sequence_warnings" not in payload
    digest=main.PAPERS[uploaded["id"]]["digest"]
    cached=json.loads((cache_records_dir/f"{digest}.json").read_text())
    assert [h["id"] for sec in cached["narrative_sections"] for h in sec["highlights"]] == ["h1","h2"]


def test_public_paper_preserves_narrative_order_and_excludes_manual_highlights():
    paper = {
        "id": "paper-1",
        "filename": "paper.pdf",
        "title": "Narrative paper",
        "reading_depth": "Deep",
        "narrative_sections": [
            {"heading": "Conclusion first", "highlights": [
                {"id": "h-late", "label": "result", "snippet": "Late page evidence.", "page_number": 8, "rects": [[1, 80, 20, 90]]},
            ]},
            {"heading": "Earlier source", "highlights": [
                {"id": "h-early", "label": "method", "snippet": "Earlier page method.", "page_number": 2, "rects": [[1, 10, 20, 20]]},
            ]},
        ],
        "manual_highlights": [
            {"id": "manual-1", "label": "problem", "snippet": "Personal note.", "page_number": 1, "rects": [[1, 1, 2, 2]]},
        ],
        "figures": [],
        "citations": [],
    }

    payload = main.public_paper(paper, include_details=True)

    assert [item["id"] for item in payload["highlights"]] == ["h-late", "h-early"]
    assert [item["origin"] for item in payload["highlights"]] == ["generated", "generated"]
    assert [item["narrative_index"] for item in payload["highlights"]] == [0, 1]
    assert payload["manual_highlights"][0]["id"] == "manual-1"
    assert "reading_depth" not in payload


def test_analysis_capacity_error_does_not_mutate_paper_or_schedule_model(tmp_path, monkeypatch):
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    pdf_path = papers_dir / "paper.pdf"
    pdf_path.write_bytes(make_pdf_bytes())
    monkeypatch.setattr(main, "PAPERS_DIR", papers_dir)
    main.PAPERS.clear()
    main.PAPERS["paper-1"] = {
        "id": "paper-1", "filename": "paper.pdf", "stored_pdf": "paper.pdf", "title": "Large paper",
        "overview": "Ready.", "analysis_status": "ready", "full_text_chars": 2_000_000,
        "narrative_sections": [], "manual_highlights": [], "figures": [], "citations": [],
    }
    scheduled = []
    monkeypatch.setattr(main.asyncio, "create_task", lambda task: scheduled.append(task))
    monkeypatch.setattr("app.ai.model_capacity_tokens", lambda _model: 100)

    response = TestClient(main.app).post("/api/papers/paper-1/analyze", json={"provider": "codex", "model": "small-model"})

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "model_capacity_exceeded"
    assert main.PAPERS["paper-1"]["analysis_status"] == "ready"
    assert main.PAPERS["paper-1"]["overview"] == "Ready."
    assert scheduled == []



def test_chat_requires_successful_analysis(monkeypatch):
    main.PAPERS.clear()
    main.PAPERS["paper-1"] = {"id": "paper-1", "filename": "paper.pdf", "title": "Paper", "analysis_status": "ready"}

    response = TestClient(main.app).post(
        "/api/papers/paper-1/chat",
        json={"messages": [{"role": "user", "content": "Explain the paper"}]},
    )

    assert response.status_code == 409


def test_failed_reanalysis_preserves_installed_narrative_and_manual_highlights(tmp_path, monkeypatch):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(make_pdf_bytes("Existing source."))
    main.PAPERS.clear()
    original_sections = [{"heading": "Existing", "highlights": [{"id": "h1", "text": "Existing narrative."}]}]
    main.PAPERS["paper-1"] = {
        "id": "paper-1", "filename": "paper.pdf", "stored_pdf": "paper.pdf", "digest": "digest",
        "title": "Paper", "analysis_status": "complete", "analysis_revision": 2,
        "narrative_sections": original_sections, "manual_highlights": [{"id": "manual-1", "snippet": "Mine"}],
    }
    monkeypatch.setattr(main, "prepare_visuals", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(main, "analyze_paper", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("model failed")))

    main.finish_paper_analysis(pdf_path, "paper-1", "paper.pdf", "codex", "digest", is_reanalysis=True)

    paper = main.PAPERS["paper-1"]
    assert paper["analysis_status"] == "complete"
    assert paper["analysis_revision"] == 2
    assert paper["narrative_sections"] == original_sections
    assert paper["manual_highlights"][0]["id"] == "manual-1"
    assert paper["reanalysis_status"] == "error"


def test_chat_passes_selected_figure_pixels_to_model(tmp_path, monkeypatch):
    figures_dir = tmp_path / "figures"
    figure_dir = main.figure_directory(figures_dir, "paper-1")
    figure_dir.mkdir(parents=True)
    figure_image = figure_dir / "p3-1.jpg"
    figure_image.write_bytes(b"actual figure pixels")
    monkeypatch.setattr(main, "FIGURES_DIR", figures_dir)
    main.PAPERS.clear()
    main.PAPERS["paper-1"] = {
        "id": "paper-1",
        "filename": "paper.pdf",
        "stored_pdf": "paper.pdf",
        "title": "Readable paper",
        "overview": "Paper overview.",
        "key_takeaways": [],
        "sentences": [],
        "figures": [{"id": "p3-1", "image_file": "p3-1.jpg", "label": "Figure 1", "page_number": 3}],
        "analysis_status": "complete",
    }
    captured = {}

    def fake_answer_chat(
        paper,
        messages,
        web_results,
        provider,
        citation_context=None,
        api_key=None,
        figure_context=None,
        model=None,
        reasoning_effort=None,
        figure_image_paths=None,
    ):
        captured["figure_context"] = figure_context
        captured["figure_image_paths"] = figure_image_paths
        return {"answer": "ok", "provider_used": "test", "web_results": [], "warnings": []}

    monkeypatch.setattr(main, "answer_chat", fake_answer_chat)

    client = TestClient(main.app)
    response = client.post(
        "/api/papers/paper-1/chat",
        json={
            "messages": [{"role": "user", "content": "What is the yellow line?"}],
            "figure_context": [{"id": "p3-1", "label": "Figure 1", "page_number": 3}],
        },
    )

    assert response.status_code == 200
    assert response.json()["answer"] == "ok"
    assert captured["figure_context"][0]["label"] == "Figure 1"
    assert captured["figure_image_paths"] == [figure_image]
    assert captured["figure_image_paths"][0].read_bytes() == b"actual figure pixels"
