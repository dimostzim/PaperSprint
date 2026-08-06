import json
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest

from app.ai import (
    DEFAULT_MODEL,
    analyze_paper,
    answer_chat,
    build_analysis_prompt,
    build_chat_prompt,
    build_selection_explanation_prompt,
    choose_provider,
    format_analysis_text,
    format_guided_reading_text,
    normalize_analysis,
    normalize_highlight_snippet,
    parse_json_payload,
    list_codex_models,
    provider_model_options,
    provider_status,
    model_supports_multimodal,
    resolve_reasoning_effort,
    resolve_text_model,
    run_ai,
    run_codex,
    sanitize_prompt_text,
    select_relevant_excerpts,
)
from app.paper_processing import (
    ExtractedPaper,
    clean_pdf_text,
    find_exact_rects,
    ground_highlights,
    process_narrative_sections,
    normalize_text,
    score_match,
    search_phrases,
    sanitize_label,
    slugify,
    sort_highlights,
    split_sentences,
)


def test_normalize_text_collapses_whitespace():
    assert normalize_text("A\n\n  useful\tpaper") == "A useful paper"


def test_pdf_and_prompt_text_remove_embedded_nulls():
    assert clean_pdf_text("A\x00paper") == "A paper"
    assert sanitize_prompt_text("A\x00prompt") == "A prompt"


def test_split_sentences_keeps_substantial_sentences():
    text = "Short. We propose a method that improves paper reading for researchers. It works on PDFs."
    assert split_sentences(text) == ["We propose a method that improves paper reading for researchers."]


def test_score_match_prefers_shared_scientific_terms():
    assert score_match("semantic graph reader", "The reader uses a semantic graph.") > 0.6
    assert score_match("semantic graph reader", "The dataset contains microscopy images.") == 0


def test_search_phrases_include_reasonable_chunks():
    phrases = search_phrases(
        "This paper presents an interactive reading interface for scholarly documents using AI generated highlights."
    )
    assert phrases
    assert all(len(phrase) >= 40 for phrase in phrases)


def test_find_exact_rects_returns_line_level_sentence_rects(tmp_path):
    pdf_path = tmp_path / "paper.pdf"
    sentence = (
        "Predicting which candidates will produce strong knockdown requires models that generalize across experiments, "
        "but published predictors are trained and evaluated on incompatible datasets."
    )
    doc = fitz.open()
    page = doc.new_page(width=360, height=240)
    page.insert_textbox(fitz.Rect(72, 72, 260, 180), sentence, fontsize=10)
    doc.save(pdf_path)
    doc.close()

    page_number, rects = find_exact_rects(pdf_path, sentence)

    with fitz.open(pdf_path) as saved_doc:
        line_count = len({(word[5], word[6]) for word in saved_doc[0].get_text("words")})
    assert page_number == 1
    assert len(rects) == line_count
    assert len(rects) < len(sentence.split()) / 2


def test_ground_highlights_preserves_comments(tmp_path):
    pdf_path = tmp_path / "paper.pdf"
    sentence = "ParaDISM assigns reads only when unambiguous sequence-specific evidence supports one origin."
    doc = fitz.open()
    page = doc.new_page(width=360, height=240)
    page.insert_textbox(fitz.Rect(72, 72, 280, 180), sentence, fontsize=10)
    doc.save(pdf_path)
    doc.close()

    highlights = [
        {
            "label": "solution",
            "snippet": sentence,
            "reason": "Shows the decision rule.",
            "comment": "The method chooses caution over forced assignment.",
        }
    ]

    grounded = ground_highlights(pdf_path, highlights, [])

    assert grounded[0]["comment"] == "The method chooses caution over forced assignment."
    assert grounded[0]["rects"]


def test_synthesized_highlight_survives_when_source_anchor_is_unavailable(tmp_path):
    pdf_path = tmp_path / "paper.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "The paper reports a measured result.")
    doc.save(pdf_path)
    doc.close()
    sections = [{"heading": "Result", "highlights": [{
        "id": "h1",
        "text": "The experiment provides evidence for the proposed approach.",
        "label": "result",
        "source": {"type": "text", "anchor": "A source anchor that cannot be located.", "page_hint": 1},
    }]}]

    result = process_narrative_sections(pdf_path, sections, "The paper reports a measured result.")

    highlight = result["narrative_sections"][0]["highlights"][0]
    assert highlight["text"] == "The experiment provides evidence for the proposed approach."
    assert highlight["navigation_available"] is False
    assert result.get("sequence_warnings", []) == []


def test_process_narrative_sections_grounds_hidden_anchor_without_comparing_synthesized_text(tmp_path):
    pdf_path = tmp_path / "paper.pdf"
    anchor = "Later source passage appears first in the narrative."
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), anchor)
    doc.save(pdf_path)
    doc.close()
    sections = [{"heading": "The argument", "highlights": [{
        "id": "h1",
        "text": "A synthesized explanation with completely different wording.",
        "label": "result",
        "source": {"type": "text", "anchor": anchor, "page_hint": 1},
    }]}]

    result = process_narrative_sections(pdf_path, sections, anchor)

    highlight = result["narrative_sections"][0]["highlights"][0]
    assert highlight["text"] == "A synthesized explanation with completely different wording."
    assert highlight["navigation_available"] is True
    assert highlight["page_number"] == 1


def test_parse_json_payload_handles_markdown_fence():
    payload = parse_json_payload('```json\n{"ok": true, "items": [1]}\n```')
    assert payload == {"ok": True, "items": [1]}


def test_parse_json_payload_accepts_raw_control_characters_in_strings():
    payload = parse_json_payload('{"snippet": "first line\nsecond line"}')
    assert payload == {"snippet": "first line\nsecond line"}


def test_build_analysis_prompt_asks_for_complete_guided_highlights():
    extracted = ExtractedPaper(
        "Useful paper",
        "This paper has enough\x00text to analyze.",
        [{"page_number": 2, "text": "Body text with enough detail to analyze."}],
        [],
    )

    prompt = build_analysis_prompt(extracted)

    assert "problem|solution|novelty|method|benchmarking|result|ablation|hyperparams|tradeoff|limitation|failure" in prompt
    assert "one comprehensive" in prompt
    assert "Do not use a target count" in prompt
    assert "Highlight text is synthesized prose, not a quotation" in prompt
    assert '"narrative_sections"' in prompt
    assert '"id": "h1"' in prompt
    assert "Preserve argumentative order" in prompt
    assert "one text Source passage or one Figure source" in prompt
    assert "copied verbatim contiguous anchor and page hint" in prompt
    assert "Inspect the attached actual image pixels" in prompt
    assert "self-check comprehensive coverage" in prompt
    assert "Headings organize" in prompt
    assert "Do not return overview, Takeaways" in prompt
    assert "[Page 2]" in prompt
    assert "Paper text:" in prompt
    assert "Return exactly" not in prompt
    assert "\x00" not in prompt


def test_format_analysis_text_adds_page_markers_without_mutating_text():
    extracted = ExtractedPaper(
        "Useful paper",
        "Fallback text",
        [
            {"page_number": 1, "text": "Abstract text."},
            {"page_number": 2, "text": "Body\x00 text."},
        ],
        [],
    )

    text = format_analysis_text(extracted)

    assert "[Page 1]\nAbstract text." in text
    assert "[Page 2]\nBody  text." in text


def test_format_guided_reading_text_keeps_abstract_and_removes_references():
    extracted = ExtractedPaper(
        "Useful paper",
        "",
        [
            {
                "page_number": 1,
                "text": (
                    "Title\nAuthors\nAbstract\n"
                    "Background\nAbstract-only motivation. "
                    "Methods\nAbstract-only method. "
                    "Results\nAbstract-only result.\n"
                    "1 Introduction\nBody contribution starts here."
                ),
            },
            {"page_number": 2, "text": "The method body gives implementation details."},
            {"page_number": 3, "text": "References\nA. Author. 2024. Reference title."},
        ],
        [],
    )

    text = format_guided_reading_text(extracted)

    assert "Abstract-only motivation" in text
    assert "[Page 1]\nTitle Authors Abstract Background Abstract-only motivation." in text
    assert "1 Introduction Body contribution starts here." in text
    assert "[Page 2]\nThe method body gives implementation details." in text
    assert "References" not in text


def test_normalize_analysis_does_not_cap_highlights():
    extracted = ExtractedPaper("Useful paper", "", [], [])
    payload = {
        "title": "Useful paper",
        "background_notes": ["RNA interference: A way to reduce target gene expression."],
        "not_shown": ["The paper does not test clinical deployment."],
        "code_availability": ["Code release is unclear from the provided text."],
        "reviewer_questions": ["Can the authors release the evaluation scripts?"],
        "key_takeaways": [
            {
                "text": "The method improves benchmark accuracy.",
                "supporting_excerpt": (
                    "The method improves benchmark accuracy by five points. "
                    "This supports the main benchmark takeaway."
                ),
                "highlight_ids": ["h1", "missing"],
            }
        ],
        "narrative_sections": [{
            "heading": "The paper's argument",
            "highlights": [
                {
                    "id": f"h{index + 1}",
                    "label": "problem",
                    "text": f"Synthesized point {index}",
                    "source": {"type": "text", "anchor": f"Source {index}.", "page_hint": 1},
                }
                for index in range(45)
            ],
        }],
    }

    analysis = normalize_analysis(payload, extracted)

    highlights = analysis["narrative_sections"][0]["highlights"]
    assert len(highlights) == 45
    assert highlights[0]["id"] == "h1"
    assert highlights[0]["text"] == "Synthesized point 0"
    assert "key_takeaways" not in analysis


def test_analyze_paper_defers_capacity_validation_to_provider(monkeypatch, tmp_path):
    pdf_path = tmp_path / "paper.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Source evidence.")
    document.save(pdf_path)
    document.close()
    extracted = ExtractedPaper("Paper", "Source evidence.", [], [])
    provider_calls = []
    payload = {
        "title": "Paper",
        "narrative_sections": [{
            "heading": "Argument",
            "highlights": [{
                "id": "h1",
                "label": "result",
                "text": "The paper reports a result.",
                "source": {"type": "text", "anchor": "Source evidence.", "page_hint": 1},
            }],
        }],
        "figures": [],
    }

    def fake_run_ai(*args, **kwargs):
        provider_calls.append((args, kwargs))
        return json.dumps(payload), "codex"

    monkeypatch.setattr(
        "app.ai.model_capacity_tokens",
        lambda _model: (_ for _ in ()).throw(AssertionError("analysis must not preflight model capacity")),
    )
    monkeypatch.setattr("app.ai.run_ai", fake_run_ai)

    analysis = analyze_paper(pdf_path, extracted, "codex", model="gpt-5.6-sol")

    assert provider_calls
    assert analysis["narrative_sections"][0]["highlights"][0]["id"] == "h1"


def test_normalize_analysis_fails_when_a_highlight_has_no_source():
    extracted = ExtractedPaper("Paper", "", [], [])
    payload = {"narrative_sections": [{"heading": "Argument", "highlights": [
        {"id": "invalid", "text": "Synthesized point without evidence."},
    ]}]}

    with pytest.raises(ValueError, match="requires synthesized text and one source"):
        normalize_analysis(payload, extracted)


def test_normalize_highlight_snippet_does_not_cut_mid_sentence():
    long_sentence = "This complete sentence should survive even when followed by extra text. "
    extra = " ".join(["additional"] * 120)

    snippet = normalize_highlight_snippet(long_sentence + extra)

    assert snippet == normalize_text(long_sentence + extra)


def test_analysis_prompt_keeps_complete_text_beyond_old_character_limit():
    sentinel = "LATE-EVIDENCE-SENTINEL"
    extracted = ExtractedPaper("Long paper", "", [{"page_number": 1, "text": "x" * 71000 + sentinel}], [])

    prompt = build_analysis_prompt(extracted)

    assert sentinel in prompt
    assert "Reading depth" not in prompt


def test_sanitize_label_uses_guided_reading_facets():
    assert sanitize_label("objective") == "problem"
    assert sanitize_label("contribution") == "novelty"
    assert sanitize_label("approach") == "solution"
    assert sanitize_label("evidence") == "result"
    assert sanitize_label("evaluation") == "benchmarking"
    assert sanitize_label("tradeoff") == "tradeoff"
    assert sanitize_label("hyperparameters") == "hyperparams"
    assert sanitize_label("compute") == "hyperparams"
    assert sanitize_label("ablation study") == "ablation"
    assert sanitize_label("failure modes") == "failure"
    assert sanitize_label("definition") == "problem"


def test_build_selection_explanation_prompt_uses_selection_and_page_context():
    paper = {"title": "Useful paper", "overview": "The paper studies semantic readers."}

    prompt = build_selection_explanation_prompt(
        paper,
        "Semantic Reader",
        3,
        "Semantic Reader augments scholarly PDFs with interactive reading tools.",
    )

    assert "Selected text (p. 3):" in prompt
    assert "Semantic Reader" in prompt
    assert "interactive reading tools" in prompt


def test_build_chat_prompt_uses_complete_highlight_narrative():
    prompt = build_chat_prompt(
        {
            "title": "Useful paper",
            "narrative_sections": [{"heading": "Evidence", "highlights": [
                {"text": "The reader links synthesized explanations to evidence."},
            ]}],
        },
        [{"role": "user", "content": "What is the main takeaway?"}],
        [],
        [],
    )

    assert "## Evidence" in prompt
    assert "- The reader links synthesized explanations to evidence." in prompt


def test_build_chat_prompt_includes_citation_focus():
    prompt = build_chat_prompt(
        {"title": "Useful paper", "overview": "The paper studies semantic readers.", "key_takeaways": []},
        [{"role": "user", "content": "Why is this citation important?"}],
        [],
        [],
        {
            "label": "[15]",
            "title": "CiteSee",
            "authors": "A. Reader",
            "year": "2022",
            "raw_reference": "A. Reader. 2022. CiteSee. CHI.",
            "contexts": [{"page_number": 4, "sentence": "CiteSee highlights familiar citations [15]."}],
        },
    )

    assert "Citation focus:" in prompt
    assert "Label: [15]" in prompt
    assert "p. 4: CiteSee highlights familiar citations [15]." in prompt


def test_build_chat_prompt_includes_figure_focus():
    prompt = build_chat_prompt(
        {
            "title": "Useful paper",
            "overview": "The paper studies semantic readers.",
            "key_takeaways": [],
            "figures": [{"id": "unselected", "label": "Unselected figure", "explanation": "Unrelated visual."}],
        },
        [{"role": "user", "content": "What does this figure show?"}],
        [],
        [],
        None,
        [
            {
                "id": "p6-1",
                "label": "Figure 2",
                "type": "plot",
                "page_number": 6,
                "caption": "Model comparison across benchmarks.",
                "explanation": "The plot compares error across methods.",
                "why_it_matters": "It supports the main evaluation claim.",
            }
        ],
    )

    assert "Figure focus:" in prompt
    assert "Figure 1: Figure 2" in prompt
    assert "Page: 6" in prompt
    assert "Visual image ID: p6-1" in prompt
    assert "The plot compares error across methods." in prompt
    assert "Unrelated visual." not in prompt


def test_select_relevant_excerpts_by_question_terms():
    spans = [
        {"text": "The method uses semantic graph features.", "page_number": 2},
        {"text": "The limitation is that scanned PDFs remain difficult.", "page_number": 7},
    ]
    selected = select_relevant_excerpts("What are the limitations?", spans, max_excerpts=1)
    assert selected[0]["page_number"] == 7


def test_slugify_produces_file_safe_name():
    assert slugify(Path("A Semantic Reader!.pdf").stem) == "a-semantic-reader"


def test_choose_provider_rejects_removed_local_provider():
    with pytest.raises(RuntimeError, match="local fallback provider has been removed"):
        choose_provider("local")


def test_choose_provider_requires_ai_provider_for_auto(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("PATH", "")

    with pytest.raises(RuntimeError, match="No AI provider available"):
        choose_provider("auto")


def test_choose_provider_uses_request_api_key_for_auto(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("PATH", "")

    assert choose_provider("auto", "sk-test") == "openai"
    assert choose_provider("auto", "sk-or-v1-test") == "openrouter"


def test_choose_provider_accepts_openrouter(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    assert choose_provider("openrouter") == "openrouter"


def test_new_codex_catalog_models_are_available_without_name_allowlisting(monkeypatch):
    future_model = "gpt-future-visual"
    payload = {"models": [{"slug": future_model, "visibility": "list", "context_window": 250000}]}
    list_codex_models.cache_clear()
    monkeypatch.setattr("app.ai.shutil.which", lambda command: "/usr/local/bin/codex" if command == "codex" else None)
    monkeypatch.setattr("app.ai.subprocess.run", lambda *_args, **_kwargs: SimpleNamespace(stdout=json.dumps(payload)))

    try:
        models = list_codex_models()
        assert future_model in models
        assert model_supports_multimodal(future_model) is True
        assert provider_status()["model_capacities"][future_model] == 250000
    finally:
        list_codex_models.cache_clear()


def test_provider_status_exposes_model_defaults(monkeypatch):
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("CODEX_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_REASONING_EFFORT", raising=False)
    monkeypatch.delenv("CODEX_REASONING_EFFORT", raising=False)
    monkeypatch.setattr("app.ai.list_codex_models", lambda: ["gpt-5.5", "gpt-5.4"])

    status = provider_status()

    assert status["default_provider"] == "codex"
    assert status["default_text_model"] == DEFAULT_MODEL
    assert status["default_vision_model"] == DEFAULT_MODEL
    assert status["default_reasoning_effort"] == "high"
    assert status["reasoning_efforts"] == ["none", "low", "medium", "high", "xhigh"]
    assert "auto" not in {provider["id"] for provider in status["providers"]}
    assert "openrouter" in {provider["id"] for provider in status["providers"]}
    assert status["provider_model_options"]["codex"]
    assert status["provider_model_options"]["openrouter"]


def test_list_codex_models_uses_visible_cli_catalog(monkeypatch):
    payload = {
        "models": [
            {"slug": "codex-auto-review", "visibility": "hide"},
            {"slug": "gpt-5.2", "visibility": "list"},
            {"slug": "gpt-5.3-codex-spark", "visibility": "list"},
            {"slug": "gpt-5.5", "visibility": "list"},
        ]
    }

    list_codex_models.cache_clear()
    monkeypatch.setattr("app.ai.shutil.which", lambda command: "/usr/local/bin/codex" if command == "codex" else None)
    monkeypatch.setattr(
        "app.ai.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=json.dumps(payload)),
    )

    try:
        assert list_codex_models() == ["gpt-5.5", "gpt-5.3-codex-spark", "gpt-5.2"]
    finally:
        list_codex_models.cache_clear()


def test_provider_model_options_uses_codex_catalog(monkeypatch):
    monkeypatch.setattr("app.ai.list_codex_models", lambda: ["gpt-5.5", "gpt-5.3-codex-spark"])

    assert provider_model_options("codex") == ["gpt-5.5", "gpt-5.3-codex-spark"]


def test_reanalysis_start_preserves_existing_chat_workspace():
    source = (Path(__file__).resolve().parents[1] / "static" / "app.js").read_text(encoding="utf-8")

    assert "function setSelectedPaper(paper, { preserveWorkspace = false } = {})" in source
    assert "setSelectedPaper(paper, { preserveWorkspace: isReanalysis })" in source


def test_failed_analysis_does_not_poll_pending_citations_forever():
    source = (Path(__file__).resolve().parents[1] / "static" / "app.js").read_text(encoding="utf-8")
    start = source.index("function paperNeedsPolling(paper)")
    end = source.index("\n\nfunction pollPaperAnalysis", start)
    function_source = source[start:end]
    script = f"""
{function_source}
console.log(JSON.stringify([
  paperNeedsPolling({{ analysis_status: "error", citation_status: "pending" }}),
  paperNeedsPolling({{ analysis_status: "complete", reanalysis_status: "error", citation_status: "pending" }}),
  paperNeedsPolling({{ analysis_status: "analyzing", citation_status: "pending" }}),
]));
"""
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)

    assert json.loads(result.stdout) == [False, False, True]


def test_polling_surfaces_reanalysis_error_before_complete_status():
    source = (Path(__file__).resolve().parents[1] / "static" / "app.js").read_text(encoding="utf-8")
    start = source.index("function pollPaperAnalysis(paperId)")
    end = source.index("\n\n\nfunction renderChat", start)
    polling_source = source[start:end]

    assert "paper.reanalysis_status === \"error\"" in polling_source
    assert polling_source.index("paper.reanalysis_status === \"error\"") < polling_source.index("paper.analysis_status === \"complete\"")
    assert "paper.reanalysis_error || \"Reanalysis failed\"" in polling_source


def test_structured_api_errors_use_their_message():
    source = (Path(__file__).resolve().parents[1] / "static" / "app.js").read_text(encoding="utf-8")
    start = source.index("function apiErrorMessage(payload, fallback)")
    end = source.index("\n\nasync function requestJson", start)
    function_source = source[start:end]
    script = f"""
{function_source}
console.log(apiErrorMessage({{ detail: {{ code: "model_capacity_exceeded", message: "Paper needs 200k tokens." }} }}, "Failed"));
"""
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)

    assert result.stdout.strip() == "Paper needs 200k tokens."


def test_default_highlight_palette_separates_similar_categories():
    source = (Path(__file__).resolve().parents[1] / "static" / "app.js").read_text(encoding="utf-8")
    start = source.index("const DEFAULT_HIGHLIGHT_COLORS = {")
    end = source.index("};", start)
    colors = dict(re.findall(r'^\s+(\w+): "(#[0-9a-fA-F]{6})"', source[start:end], re.MULTILINE))

    def distance(first, second):
        first_rgb = tuple(int(first[index:index + 2], 16) for index in (1, 3, 5))
        second_rgb = tuple(int(second[index:index + 2], 16) for index in (1, 3, 5))
        return sum((left - right) ** 2 for left, right in zip(first_rgb, second_rgb)) ** 0.5

    def blended_distance(first, second):
        return distance(first, second) * 0.32

    assert blended_distance(colors["problem"], colors["solution"]) > 55
    assert blended_distance(colors["problem"], colors["method"]) > 55
    assert blended_distance(colors["solution"], colors["method"]) > 55
    assert blended_distance(colors["limitation"], colors["failure"]) > 50
    core = [colors[facet] for facet in (
        "problem", "solution", "novelty", "method", "benchmarking", "result",
        "ablation", "hyperparams", "tradeoff", "limitation", "failure",
    )]
    assert min(blended_distance(first, second) for index, first in enumerate(core) for second in core[index + 1:]) > 25

    styles = (Path(__file__).resolve().parents[1] / "static" / "styles.css").read_text(encoding="utf-8").lower()
    for color in set(core):
        assert f"background: {color.lower()};" in styles
        assert f"color-mix(in srgb, {color.lower()}" in styles


def test_highlight_category_chips_always_use_overlay_colors():
    root = Path(__file__).resolve().parents[1]
    source = (root / "static" / "app.js").read_text(encoding="utf-8")
    styles = (root / "static" / "styles.css").read_text(encoding="utf-8")

    assert "--facet-bg: ${hexToRgba(color, 0.32)}" in source
    assert ".facet-chip.has-color {" in styles
    assert "background: var(--facet-bg)" in styles[styles.index(".facet-chip.has-color {"):]


def test_chat_has_standalone_reset_without_sending():
    root = Path(__file__).resolve().parents[1]
    template = (root / "templates" / "index.html").read_text(encoding="utf-8")
    source = (root / "static" / "app.js").read_text(encoding="utf-8")

    assert '<button id="chat-reset-button" type="button">Reset</button>' in template
    assert "Reset &amp; Send" not in template
    assert "resetHistory" not in source

    start = source.index("function resetChat()")
    end = source.index("\n\nasync function sendChatMessage", start)
    function_source = source[start:end]
    script = f"""
const state = {{
  chatMessages: [{{ role: "user", content: "old question" }}],
  pendingCitationContext: {{ id: "citation" }},
  selectedFigures: [{{ id: "figure" }}],
}};
let submissions = 0;
const els = {{ chatInput: {{ value: "draft", focus() {{}} }} }};
function resizeChatInput() {{}}
function renderChat() {{}}
function renderChatFigureFocus() {{}}
function sendChatMessage() {{ submissions += 1; }}
{function_source}
resetChat();
console.log(JSON.stringify({{ ...state, draft: els.chatInput.value, submissions }}));
"""
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    payload = json.loads(result.stdout)

    assert payload == {
        "chatMessages": [],
        "pendingCitationContext": None,
        "selectedFigures": [],
        "draft": "",
        "submissions": 0,
    }


def test_highlight_selection_only_adds_a_strong_outline():
    styles = (Path(__file__).resolve().parents[1] / "static" / "styles.css").read_text(encoding="utf-8")
    active_start = styles.index(".highlight-rect.active {")
    active_end = styles.index("}\n", active_start)
    active_rule = styles[active_start:active_end]

    assert "opacity:" not in active_rule
    assert "box-shadow:" not in active_rule
    assert ".overlay-layer:has(.highlight-rect.active) .highlight-rect:not(.active)" not in styles
    assert ".highlight-rect:hover" not in styles
    assert "outline: 3px solid var(--accent-strong)" in active_rule


def test_source_unavailable_highlight_flash_respects_reduced_motion():
    styles = (Path(__file__).resolve().parents[1] / "static" / "styles.css").read_text(encoding="utf-8")

    assert ".highlight-card.source-unavailable-flash" in styles
    assert "animation: source-unavailable-flash 700ms" in styles
    assert "@media (prefers-reduced-motion: reduce)" in styles


def test_highlight_popover_uses_complete_text_without_truncation():
    root = Path(__file__).resolve().parents[1]
    source = (root / "static" / "app.js").read_text(encoding="utf-8")
    start = source.index("function renderHighlightPopover(highlight)")
    end = source.index("\n\nfunction openHighlightPopover", start)
    function_source = source[start:end]

    assert "briefText(" not in function_source
    assert 'highlight?.text || highlight?.snippet || ""' in function_source
    styles = (root / "static" / "styles.css").read_text(encoding="utf-8")
    highlight_styles = styles[styles.index(".highlight-popover {"):styles.index(".highlight-popover-copy {")]
    assert "max-height: calc(100vh - 16px)" in highlight_styles
    assert "overflow-y: auto" in highlight_styles


def test_figure_backed_highlight_offers_visual_attachment_instead_of_text_explanation():
    source = (Path(__file__).resolve().parents[1] / "static" / "app.js").read_text(encoding="utf-8")
    start = source.index("function renderHighlightPopover(highlight)")
    end = source.index("\n\nfunction openHighlightPopover", start)
    function_source = source[start:end]

    assert "data-add-highlight-figure" in function_source
    assert "highlight?.source?.type === \"figure\"" in function_source


def test_add_figure_to_chat_only_attaches_without_submitting():
    source = (Path(__file__).resolve().parents[1] / "static" / "app.js").read_text(encoding="utf-8")
    start = source.index("function addFigureToChat(figure)")
    end = source.index("\n\nfunction citationsByPage", start)
    function_source = source[start:end]
    script = f"""
const state = {{ selectedFigures: [] }};
let submissions = 0;
const els = {{
  chatInput: {{ value: "my visual question", focus() {{}} }},
  chatForm: {{ requestSubmit() {{ submissions += 1; }} }},
}};
function isFigureSelected(id) {{ return state.selectedFigures.some((figure) => figure.id === id); }}
function renderChatFigureFocus() {{}}
function showToast() {{}}
function sendChatMessage() {{ submissions += 1; }}
{function_source}
addFigureToChat({{ id: "p1-1", image_url: "/figure.jpg" }});
console.log(JSON.stringify({{
  selectedIds: state.selectedFigures.map((figure) => figure.id),
  draft: els.chatInput.value,
  submissions,
}}));
"""

    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    payload = json.loads(result.stdout)

    assert payload == {"selectedIds": ["p1-1"], "draft": "my visual question", "submissions": 0}
    assert '<img src="${escapeHtml(figure.image_url || "")}"' in source
    assert "Add figure to chat" in source


def test_run_ai_passes_every_visual_to_multimodal_adapter(monkeypatch, tmp_path):
    images = [tmp_path / "one.jpg", tmp_path / "two.jpg"]
    for image in images:
        image.write_bytes(b"jpeg")
    captured = {}

    def fake_openai(prompt, system_prompt, expect_json, api_key=None, model=None, reasoning_effort=None, image_paths=None):
        captured["images"] = image_paths
        return "{}"

    monkeypatch.setattr("app.ai.run_openai", fake_openai)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    run_ai("prompt", "system", "openai", True, image_paths=images)

    assert captured["images"] == images


def test_run_ai_attaches_visuals_to_codex_cli(monkeypatch, tmp_path):
    images = [tmp_path / "one.jpg", tmp_path / "two.jpg"]
    for image in images:
        image.write_bytes(b"jpeg")
    captured = {}

    def fake_subprocess_run(args, **_kwargs):
        if args[-2:] == ["exec", "--help"]:
            return SimpleNamespace(returncode=0, stdout="--image <FILE>", stderr="")
        captured["args"] = args
        output_path = Path(args[args.index("-o") + 1])
        output_path.write_text("visual answer", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("app.ai.shutil.which", lambda command: "/usr/local/bin/codex" if command == "codex" else None)
    monkeypatch.setattr("app.ai.subprocess.run", fake_subprocess_run)

    answer, provider = run_ai("What is blue?", "system", "codex", False, image_paths=images)

    assert answer == "visual answer"
    assert provider == "codex"
    image_arg = next(argument for argument in captured["args"] if argument.startswith("--image="))
    assert image_arg.removeprefix("--image=").split(",") == [str(image.resolve()) for image in images]
    assert "What is blue?" in captured["args"][-1]
    assert captured["args"][-1] != "-"


def test_run_ai_retries_codex_when_image_option_consumes_prompt(monkeypatch, tmp_path):
    image = tmp_path / "figure.jpg"
    image.write_bytes(b"jpeg")
    invocations = []

    def fake_subprocess_run(args, **_kwargs):
        if args[-2:] == ["exec", "--help"]:
            return SimpleNamespace(returncode=0, stdout="--image <FILE>", stderr="")
        invocations.append(args)
        if any(argument == "--image" or argument.startswith("--image=") for argument in args):
            return SimpleNamespace(
                returncode=2,
                stdout="",
                stderr="Reading prompt from stdin... No prompt provided via stdin.",
            )
        output_path = Path(args[args.index("-o") + 1])
        output_path.write_text("fallback answer", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("app.ai.shutil.which", lambda command: "/usr/local/bin/codex" if command == "codex" else None)
    monkeypatch.setattr("app.ai.subprocess.run", fake_subprocess_run)

    answer, provider = run_ai("Analyze", "system", "codex", False, image_paths=[image])

    assert answer == "fallback answer"
    assert provider == "codex"
    assert len(invocations) == 2
    assert str(image.resolve()) in invocations[1][-1]


def test_run_ai_keeps_codex_compatible_when_cli_lacks_image_flag(monkeypatch, tmp_path):
    image = tmp_path / "figure.jpg"
    image.write_bytes(b"jpeg")
    captured = {}

    def fake_subprocess_run(args, **_kwargs):
        if args[-2:] == ["exec", "--help"]:
            return SimpleNamespace(returncode=0, stdout="Usage: codex exec [PROMPT]", stderr="")
        captured["args"] = args
        output_path = Path(args[args.index("-o") + 1])
        output_path.write_text("analysis answer", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("app.ai.shutil.which", lambda command: "/usr/local/bin/codex" if command == "codex" else None)
    monkeypatch.setattr("app.ai.subprocess.run", fake_subprocess_run)

    answer, provider = run_ai("Analyze", "system", "codex", False, image_paths=[image])

    assert answer == "analysis answer"
    assert provider == "codex"
    assert "--image" not in captured["args"]
    assert str(image.resolve()) in captured["args"][-1]


def test_answer_chat_sends_selected_figure_pixels_to_run_ai(monkeypatch, tmp_path):
    image_path = tmp_path / "selected-figure.jpg"
    image_path.write_bytes(b"jpeg")
    captured = {}

    def fake_run_ai(*args, **kwargs):
        captured["image_paths"] = kwargs.get("image_paths")
        return "The yellow line is the baseline.", "test"

    monkeypatch.setattr("app.ai.run_ai", fake_run_ai)
    result = answer_chat(
        {"title": "Paper", "sentences": [], "figures": []},
        [{"role": "user", "content": "What is the yellow line?"}],
        [],
        "codex",
        figure_context=[{"id": "p1-1", "label": "Figure 1"}],
        figure_image_paths=[image_path],
    )

    assert result["answer"] == "The yellow line is the baseline."
    assert captured["image_paths"] == [image_path]


def test_run_codex_timeout_hides_full_prompt(monkeypatch):
    def timeout(*_args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["codex", "very long prompt"], timeout=kwargs["timeout"])

    monkeypatch.setattr("app.ai.shutil.which", lambda command: "/usr/local/bin/codex" if command == "codex" else None)
    monkeypatch.setattr("app.ai.subprocess.run", timeout)

    with pytest.raises(RuntimeError) as error:
        run_codex("very long prompt", timeout_seconds=7, model="gpt-5.4", reasoning_effort="low")

    message = str(error.value)
    assert "Codex timed out after 7 seconds with model gpt-5.4" in message
    assert "very long prompt" not in message


def test_provider_model_options_uses_fallback_for_openrouter(monkeypatch):
    def fail(*_args, **_kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr("app.ai.list_openrouter_models", fail)

    assert provider_model_options("openrouter")[0].startswith("openai/")


def test_model_and_effort_resolution_prefers_request_then_env(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.4")
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "medium")

    assert resolve_text_model("gpt-5.5") == "gpt-5.5"
    assert resolve_text_model(None) == "gpt-5.4"
    assert resolve_reasoning_effort("xhigh", "OPENAI_REASONING_EFFORT") == "xhigh"
    assert resolve_reasoning_effort(None, "OPENAI_REASONING_EFFORT") == "medium"
    assert resolve_reasoning_effort("bad", "OPENAI_REASONING_EFFORT") == "medium"


def test_sort_highlights_uses_pdf_position():
    highlights = [
        {"page_number": 3, "rects": [[10, 40, 20, 50]], "snippet": "third"},
        {"page_number": 1, "rects": [[10, 80, 20, 90]], "snippet": "second on page"},
        {"page_number": 1, "rects": [[10, 20, 20, 30]], "snippet": "first on page"},
    ]

    assert [item["snippet"] for item in sort_highlights(highlights)] == [
        "first on page",
        "second on page",
        "third",
    ]
