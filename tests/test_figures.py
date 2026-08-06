from pathlib import Path

import fitz

from app.figures import (
    coerce_bbox_pct,
    crop_figure_image,
    prepare_visuals,
    render_page_image,
    visual_candidate_pages,
)
from app.paper_processing import ExtractedPaper


def test_coerce_bbox_pct_clamps_and_orders_values():
    assert coerce_bbox_pct([90, -5, 10, 120]) == [10.0, 0.0, 90.0, 100.0]
    assert coerce_bbox_pct(["bad", 0, 1, 2]) == [0.0, 0.0, 100.0, 100.0]
    assert coerce_bbox_pct([1, 1, 1.5, 50]) == [0.0, 0.0, 100.0, 100.0]



def test_render_page_and_crop_figure_images(tmp_path):
    pdf_path = tmp_path / "paper.pdf"
    doc = fitz.open()
    page = doc.new_page(width=240, height=240)
    page.insert_text((40, 40), "Figure 1: Example plot")
    page.draw_rect(fitz.Rect(40, 70, 200, 190), color=(0, 0, 0), width=1)
    doc.save(pdf_path)
    doc.close()

    page_image = tmp_path / "page.jpg"
    crop_image = tmp_path / "figure.jpg"

    render_page_image(pdf_path, 1, page_image)
    crop_figure_image(pdf_path, 1, [15, 25, 90, 85], crop_image)

    assert page_image.exists()
    assert crop_image.exists()
    assert page_image.stat().st_size > 0
    assert crop_image.stat().st_size > 0


def test_prepare_visuals_ignores_page_furniture_drawings_without_visual_cue(tmp_path):
    pdf_path = tmp_path / "title-page.pdf"
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text((50, 120), "A paper title and abstract")
    for y in (75, 205, 706):
        page.draw_line((48, y), (553, y))
    doc.save(pdf_path)
    doc.close()
    extracted = ExtractedPaper("Paper", "", [{"page_number": 1, "text": "A paper title and abstract"}], [])

    visuals = prepare_visuals(pdf_path, extracted, tmp_path / "figures", "paper-1")

    assert visuals == []


def test_prepare_visuals_does_not_promote_text_page_with_figure_reference_to_full_page_visual(tmp_path):
    pdf_path = tmp_path / "figure-reference.pdf"
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text((50, 100), "The individual differences are summarized in Figure 1 on the next page.")
    page.insert_text((50, 140), "This page otherwise contains ordinary body text only.")
    doc.save(pdf_path)
    doc.close()
    extracted = ExtractedPaper(
        "Paper",
        "",
        [{"page_number": 1, "text": "The individual differences are summarized in Figure 1 on the next page. This page otherwise contains ordinary body text only."}],
        [],
    )

    visuals = prepare_visuals(pdf_path, extracted, tmp_path / "figures", "paper-1")

    assert visuals == []


def test_prepare_visuals_accepts_tuple_table_bounding_boxes(tmp_path):
    pdf_path = tmp_path / "table.pdf"
    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    for x in (40, 150, 260):
        page.draw_line((x, 80), (x, 220))
    for y in (80, 120, 170, 220):
        page.draw_line((40, y), (260, y))
    for y, text in ((105, "A"), (145, "B"), (195, "C")):
        page.insert_text((60, y), text)
    doc.save(pdf_path)
    doc.close()
    extracted = ExtractedPaper("Paper", "", [{"page_number": 1, "text": "Table 1"}], [])

    visuals = prepare_visuals(pdf_path, extracted, tmp_path / "figures", "paper-1")

    assert visuals
    assert visuals[0]["bbox_pct"] == [13.33, 26.67, 86.67, 73.33]


def test_prepare_visuals_keeps_exact_source_box_separate_from_context_crop(tmp_path):
    pdf_path = tmp_path / "algorithm.pdf"
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text((50, 50), "Page header")
    page.draw_line((40, 45), (560, 45))
    source_box = fitz.Rect(300, 440, 550, 730)
    page.draw_rect(source_box)
    page.insert_text((315, 470), "Algorithm 1: Iterative procedure")
    doc.save(pdf_path)
    doc.close()
    extracted = ExtractedPaper("Paper", "", [{"page_number": 1, "text": "Algorithm 1: Iterative procedure"}], [])

    visuals = prepare_visuals(pdf_path, extracted, tmp_path / "figures", "paper-1")

    assert len(visuals) == 1
    assert visuals[0]["rects"] == [[300.0, 440.0, 550.0, 730.0]]
    assert visuals[0]["bbox_pct"] != visuals[0]["crop_bbox_pct"]
    assert visuals[0]["bbox_pct"][1] > 50


def test_prepare_visuals_ignores_page_sized_drawing_union(tmp_path):
    pdf_path = tmp_path / "paper.pdf"
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text((50, 100), "Figure 1 is discussed later.")
    page.draw_rect(page.rect)
    doc.save(pdf_path)
    doc.close()
    extracted = ExtractedPaper("Paper", "", [{"page_number": 1, "text": "Figure 1 is discussed later."}], [])

    visuals = prepare_visuals(pdf_path, extracted, tmp_path / "figures", "paper-1")

    assert visuals == []


def test_prepare_visuals_keeps_full_page_drawing_union_as_context_not_visual(tmp_path):
    pdf_path = tmp_path / "paper.pdf"
    image_path = tmp_path / "figure.png"
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 100, 100), False)
    pixmap.clear_with(200)
    pixmap.save(image_path)
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    figure_box = fitz.Rect(75, 140, 540, 480)
    page.insert_image(figure_box, filename=image_path)
    page.draw_rect(page.rect)
    doc.save(pdf_path)
    doc.close()
    extracted = ExtractedPaper("Paper", "", [{"page_number": 1, "text": "Figure 1: Benchmark result"}], [])

    visuals = prepare_visuals(pdf_path, extracted, tmp_path / "figures", "paper-1")

    assert len(visuals) == 1
    assert visuals[0]["rects"] == [[75.0, 140.0, 540.0, 480.0]]
    assert visuals[0]["page_image_path"]


def test_prepare_visuals_provides_actual_crop_and_full_page_fallback(tmp_path):
    pdf_path = tmp_path / "paper.pdf"
    doc = fitz.open()
    page = doc.new_page(width=240, height=240)
    page.insert_text((40, 40), "Figure 1: Benchmark result")
    page.draw_rect(fitz.Rect(40, 70, 200, 190), color=(0, 0, 0), width=1)
    doc.save(pdf_path)
    doc.close()
    extracted = ExtractedPaper("Paper", "", [{"page_number": 1, "text": "Figure 1: Benchmark result"}], [])

    visuals = prepare_visuals(pdf_path, extracted, tmp_path / "figures", "paper-1")

    assert visuals
    assert Path(visuals[0]["image_path"]).exists()
    assert visuals[0]["page_number"] == 1
    assert visuals[0]["rects"]


def test_visual_candidate_pages_uses_text_and_pdf_structure(tmp_path):
    pdf_path = tmp_path / "paper.pdf"
    doc = fitz.open()
    doc.new_page(width=240, height=240).insert_text((40, 40), "Plain introduction page")
    doc.new_page(width=240, height=240).insert_text((40, 40), "Figure 1: Benchmark result")
    visual_page = doc.new_page(width=240, height=240)
    visual_page.draw_rect(fitz.Rect(40, 70, 200, 190), color=(0, 0, 0), width=1)
    doc.save(pdf_path)
    doc.close()
    pages = [
        {"page_number": 1, "text": "Plain introduction page"},
        {"page_number": 2, "text": "Figure 1: Benchmark result"},
        {"page_number": 3, "text": "A page with a large vector drawing"},
    ]

    candidates = visual_candidate_pages(pdf_path, pages)

    assert [page["page_number"] for page in candidates] == [2, 3]
