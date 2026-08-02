from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from .paper_processing import ExtractedPaper, normalize_text, process_narrative_sections, score_match

load_dotenv()

MAX_HIGHLIGHT_SNIPPET_CHARS = 900  # Manual highlights only.
MAX_TAKEAWAY_EXCERPT_CHARS = 1600
MAX_CITATION_VALIDATION_CONTEXTS = 180
ANALYSIS_VERSION = 16
ANALYSIS_RESPONSE_RESERVE_TOKENS = 24_000
ANALYSIS_SAFETY_MARGIN_TOKENS = 8_000
DYNAMIC_MODEL_CONTEXT_TOKENS: dict[str, int] = {}
DYNAMIC_MULTIMODAL_MODELS: set[str] = set()
DEFAULT_DISCOVERED_CONTEXT_TOKENS = 128_000
MODEL_MULTIMODAL = {
    "gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex", "gpt-5.3-codex-spark",
    "gpt-5.2", "gpt-5.2-pro", "gpt-5.1", "gpt-5-mini", "gpt-4.1", "gpt-4.1-mini",
    "o3", "o4-mini", "openai/gpt-5.5", "openai/gpt-5.4", "openai/gpt-5.4-mini",
    "openai/gpt-5.2", "anthropic/claude-sonnet-4.5", "google/gemini-3-pro",
}
MODEL_CONTEXT_TOKENS = {
    "gpt-5.5": 400_000,
    "gpt-5.4": 400_000,
    "gpt-5.4-mini": 400_000,
    "gpt-5.3-codex": 400_000,
    "gpt-5.3-codex-spark": 400_000,
    "gpt-5.2": 400_000,
    "gpt-5.2-pro": 400_000,
    "gpt-5.1": 400_000,
    "gpt-5-mini": 400_000,
    "gpt-4.1": 1_000_000,
    "gpt-4.1-mini": 1_000_000,
    "o3": 200_000,
    "o4-mini": 200_000,
    "anthropic/claude-sonnet-4.5": 200_000,
    "google/gemini-3-pro": 1_000_000,
}
DEFAULT_MODEL = "gpt-5.5"
DEFAULT_REASONING_EFFORT = "high"
REASONING_EFFORTS = {"none", "low", "medium", "high", "xhigh"}
CODEX_MODEL_OPTIONS = [
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.3-codex",
    "gpt-5.3-codex-spark",
    "gpt-5.2",
]
OPENAI_MODEL_OPTIONS = [
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.3-codex",
    "gpt-5.2",
    "gpt-5.2-pro",
    "gpt-5.1",
    "gpt-5-mini",
    "gpt-4.1",
    "gpt-4.1-mini",
    "o3",
    "o4-mini",
]
OPENROUTER_MODEL_OPTIONS = [
    "openai/gpt-5.5",
    "openai/gpt-5.4",
    "openai/gpt-5.4-mini",
    "openai/gpt-5.2",
    "anthropic/claude-sonnet-4.5",
    "google/gemini-3-pro",
]
MODEL_OPTIONS = list(dict.fromkeys([*CODEX_MODEL_OPTIONS, *OPENAI_MODEL_OPTIONS, *OPENROUTER_MODEL_OPTIONS]))
REFERENCES_START_RE = re.compile(r"(?:^|\n)\s*(?:references|bibliography|works cited)\s*(?:\n|$)", re.IGNORECASE)
PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
MODEL_EXCLUDE_TERMS = (
    "audio",
    "dall-e",
    "embedding",
    "image",
    "moderation",
    "realtime",
    "search",
    "sora",
    "transcribe",
    "tts",
    "whisper",
)


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8").strip()


def render_prompt(name: str, **values: Any) -> str:
    prompt = load_prompt(name)
    for key, value in values.items():
        prompt = prompt.replace(f"{{{{{key}}}}}", str(value))
    return prompt.strip()


ANALYSIS_SYSTEM = load_prompt("analysis_system.md")
CHAT_SYSTEM = load_prompt("chat_system.md")
CITATION_VALIDATION_SYSTEM = load_prompt("citation_validation_system.md")
SELECTION_EXPLANATION_SYSTEM = load_prompt("selection_explanation_system.md")


def configured_model_ids() -> list[str]:
    values = [os.getenv(name, "").strip() for name in ("CODEX_MODEL", "OPENAI_MODEL", "OPENROUTER_MODEL", "PI_MODEL")]
    models = [value for value in values if value and model_id_is_usable(value)]
    for model in models:
        register_catalog_model(model, assume_image_input=True)
    return list(dict.fromkeys(models))


def provider_status() -> dict[str, Any]:
    has_openai_key = bool(os.getenv("OPENAI_API_KEY"))
    has_openrouter_key = bool(os.getenv("OPENROUTER_API_KEY"))
    has_codex = bool(shutil.which("codex"))
    default_provider = os.getenv("AI_PROVIDER", "codex")
    if default_provider not in {"auto", "codex", "openai", "openrouter"}:
        default_provider = "codex"
    configured_models = configured_model_ids()
    configured_codex_models = [model.split("/", 1)[-1] for model in configured_models]
    for model in configured_codex_models:
        register_catalog_model(model, assume_image_input=True)
    codex_model_options = list(dict.fromkeys([*(list_codex_models() if has_codex else CODEX_MODEL_OPTIONS), *configured_codex_models]))
    model_options = [
        model
        for model in dict.fromkeys([*codex_model_options, *OPENAI_MODEL_OPTIONS, *OPENROUTER_MODEL_OPTIONS, *configured_models])
        if model_supports_multimodal(model)
    ]
    return {
        "default_provider": default_provider,
        "default_text_model": resolve_text_model(None),
        "default_vision_model": resolve_vision_model(None),
        "default_reasoning_effort": resolve_reasoning_effort(None, "OPENAI_REASONING_EFFORT", "CODEX_REASONING_EFFORT"),
        "default_vision_reasoning_effort": resolve_reasoning_effort(
            None,
            "OPENAI_VISION_REASONING_EFFORT",
            "CODEX_VISION_REASONING_EFFORT",
            "OPENAI_REASONING_EFFORT",
            "CODEX_REASONING_EFFORT",
        ),
        "reasoning_efforts": sorted(REASONING_EFFORTS, key=["none", "low", "medium", "high", "xhigh"].index),
        "model_options": model_options,
        "model_capacities": {model: model_capacity_tokens(model) for model in model_options},
        "provider_model_options": {
            "auto": model_options,
            "codex": [model for model in codex_model_options if model_supports_multimodal(model)],
            "openai": [model for model in OPENAI_MODEL_OPTIONS if model_supports_multimodal(model)],
            "openrouter": [model for model in OPENROUTER_MODEL_OPTIONS if model_supports_multimodal(model)],
        },
        "openai_available": has_openai_key,
        "openrouter_available": has_openrouter_key,
        "codex_available": has_codex,
        "providers": [
            {"id": "codex", "label": "Codex subscription"},
            {"id": "openai", "label": "OpenAI API key"},
            {"id": "openrouter", "label": "OpenRouter API key"},
        ],
    }


def resolve_model(value: str | None, *env_names: str) -> str:
    candidates = [value, *(os.getenv(name) for name in env_names), DEFAULT_MODEL]
    for candidate in candidates:
        clean = str(candidate or "").replace('"', "").strip()
        if clean:
            return clean[:120]
    return DEFAULT_MODEL


def resolve_text_model(value: str | None) -> str:
    return resolve_model(value, "OPENAI_MODEL", "OPENROUTER_MODEL", "CODEX_MODEL")


def resolve_vision_model(value: str | None) -> str:
    return resolve_model(
        value,
        "OPENAI_VISION_MODEL",
        "OPENROUTER_VISION_MODEL",
        "CODEX_VISION_MODEL",
        "OPENAI_MODEL",
        "OPENROUTER_MODEL",
        "CODEX_MODEL",
    )


def resolve_reasoning_effort(value: str | None, *env_names: str) -> str:
    candidates = [value, *(os.getenv(name) for name in env_names), DEFAULT_REASONING_EFFORT]
    for candidate in candidates:
        clean = str(candidate or "").strip().lower()
        if clean in REASONING_EFFORTS:
            return clean
    return DEFAULT_REASONING_EFFORT


def sanitize_prompt_text(value: str) -> str:
    return str(value).replace("\x00", " ")


def openai_api_key(api_key: str | None = None) -> str:
    return (api_key or os.getenv("OPENAI_API_KEY") or "").strip()


def openrouter_api_key(api_key: str | None = None) -> str:
    return (api_key or os.getenv("OPENROUTER_API_KEY") or "").strip()


def model_id_is_usable(model_id: str) -> bool:
    normalized = model_id.lower()
    if any(term in normalized for term in MODEL_EXCLUDE_TERMS):
        return False
    return normalized.startswith(("gpt-", "o", "chatgpt-", "computer-use", "openai/", "anthropic/", "google/", "x-ai/", "meta-llama/"))


def catalog_input_modalities(item: Any) -> set[str]:
    if not isinstance(item, dict):
        return set()
    architecture = item.get("architecture") if isinstance(item.get("architecture"), dict) else {}
    capabilities = item.get("capabilities") if isinstance(item.get("capabilities"), dict) else {}
    raw = (
        architecture.get("input_modalities")
        or item.get("input_modalities")
        or item.get("modalities")
        or capabilities.get("input_modalities")
        or []
    )
    if isinstance(raw, str):
        raw = [raw]
    return {str(value).lower() for value in raw if value}


def register_catalog_model(model_id: str, item: Any = None, assume_image_input: bool = False) -> None:
    if not model_id:
        return
    metadata = item if isinstance(item, dict) else {}
    modalities = catalog_input_modalities(metadata)
    capabilities = metadata.get("capabilities") if isinstance(metadata.get("capabilities"), dict) else {}
    supports_images = (
        "image" in modalities
        or metadata.get("supports_image_input") is True
        or metadata.get("supports_vision") is True
        or capabilities.get("vision") is True
        or capabilities.get("image_input") is True
        or (assume_image_input and not modalities)
    )
    if supports_images:
        DYNAMIC_MULTIMODAL_MODELS.add(model_id)
    try:
        context_length = int(
            metadata.get("context_window")
            or metadata.get("context_length")
            or capabilities.get("context_window")
            or 0
        )
    except (TypeError, ValueError):
        context_length = 0
    if context_length > 0:
        DYNAMIC_MODEL_CONTEXT_TOKENS[model_id] = context_length
    elif supports_images:
        DYNAMIC_MODEL_CONTEXT_TOKENS.setdefault(model_id, DEFAULT_DISCOVERED_CONTEXT_TOKENS)


def sort_model_ids(model_ids: list[str]) -> list[str]:
    preferred = [
        "gpt-5.5",
        "openai/gpt-5.5",
        "gpt-5.4",
        "openai/gpt-5.4",
        "gpt-5.4-mini",
        "openai/gpt-5.4-mini",
        "gpt-5.3-codex",
        "gpt-5.3-codex-spark",
        "gpt-5.2",
        "openai/gpt-5.2",
    ]
    preferred_rank = {model: index for index, model in enumerate(preferred)}
    return sorted(dict.fromkeys(model_ids), key=lambda model: (preferred_rank.get(model, len(preferred)), model))


@lru_cache(maxsize=1)
def list_codex_models() -> list[str]:
    codex_path = shutil.which("codex")
    if not codex_path:
        return CODEX_MODEL_OPTIONS

    try:
        result = subprocess.run(
            [codex_path, "debug", "models"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        payload = json.loads(result.stdout)
    except Exception:
        return CODEX_MODEL_OPTIONS

    model_ids = []
    for item in payload.get("models", []):
        if not isinstance(item, dict) or item.get("visibility") != "list":
            continue
        model_id = str(item.get("slug", "")).strip()
        if model_id:
            model_ids.append(model_id)
            register_catalog_model(model_id, item, assume_image_input=True)
    return sort_model_ids(model_ids) or CODEX_MODEL_OPTIONS


def list_openai_models(api_key: str | None = None) -> list[str]:
    key = openai_api_key(api_key)
    if not key:
        return OPENAI_MODEL_OPTIONS

    from openai import OpenAI

    client = OpenAI(api_key=key)
    models = client.models.list()
    model_ids = []
    for model in models.data:
        model_id = str(model.id)
        if not model_id_is_usable(model_id):
            continue
        model_ids.append(model_id)
        metadata = model.model_dump() if hasattr(model, "model_dump") else vars(model)
        register_catalog_model(model_id, metadata, assume_image_input=True)
    return sort_model_ids(model_ids) or OPENAI_MODEL_OPTIONS


def list_openrouter_models(api_key: str | None = None) -> list[str]:
    headers = {"Accept": "application/json"}
    key = openrouter_api_key(api_key)
    if key:
        headers["Authorization"] = f"Bearer {key}"

    response = requests.get(f"{OPENROUTER_BASE_URL}/models", headers=headers, timeout=10)
    response.raise_for_status()
    payload = response.json()
    model_ids = []
    for item in payload.get("data", []):
        model_id = str(item.get("id", "")).strip()
        architecture = item.get("architecture") if isinstance(item, dict) else {}
        input_modalities = architecture.get("input_modalities", []) if isinstance(architecture, dict) else []
        output_modalities = architecture.get("output_modalities", []) if isinstance(architecture, dict) else []
        supports_text = not input_modalities or "text" in input_modalities
        outputs_text = not output_modalities or "text" in output_modalities
        if model_id and supports_text and outputs_text:
            model_ids.append(model_id)
            register_catalog_model(model_id, item)
    return sort_model_ids(model_ids) or OPENROUTER_MODEL_OPTIONS


def provider_model_options(provider: str | None, api_key: str | None = None) -> list[str]:
    selected = (provider or "auto").lower()
    try:
        if selected == "openai":
            return list_openai_models(api_key)
        if selected == "openrouter":
            return list_openrouter_models(api_key)
    except Exception:
        pass
    if selected == "codex":
        return list_codex_models()
    if selected == "openai":
        return OPENAI_MODEL_OPTIONS
    if selected == "openrouter":
        return OPENROUTER_MODEL_OPTIONS
    return MODEL_OPTIONS


def choose_provider(requested: str | None, api_key: str | None = None) -> str:
    provider = (requested or os.getenv("AI_PROVIDER", "auto")).lower()
    if provider == "auto":
        if str(api_key or "").strip().startswith("sk-or-"):
            return "openrouter"
        if openai_api_key(api_key):
            return "openai"
        if openrouter_api_key():
            return "openrouter"
        if shutil.which("codex"):
            return "codex"
        raise RuntimeError("No AI provider available. Log in to Codex CLI or set OPENAI_API_KEY or OPENROUTER_API_KEY.")
    if provider in {"codex", "openai", "openrouter"}:
        return provider
    if provider == "local":
        raise RuntimeError("The local fallback provider has been removed.")
    return provider


class ModelCapacityError(ValueError):
    def __init__(self, model: str, required_tokens: int, capacity_tokens: int | None):
        self.model = model
        self.required_tokens = required_tokens
        self.capacity_tokens = capacity_tokens
        capacity = f"{capacity_tokens:,} tokens" if capacity_tokens else "unknown"
        super().__init__(
            f"The complete paper requires about {required_tokens:,} input tokens, but {model} has {capacity} capacity. "
            "Choose a larger-context model and analyze again."
        )


def model_capacity_tokens(model: str | None) -> int | None:
    selected = resolve_text_model(model)
    overrides = os.getenv("MODEL_CONTEXT_TOKENS", "").strip()
    if overrides:
        try:
            value = json.loads(overrides)
            if isinstance(value, dict) and int(value.get(selected, 0)) > 0:
                return int(value[selected])
        except (ValueError, TypeError, json.JSONDecodeError):
            pass
    unqualified = selected.split("/", 1)[-1]
    return DYNAMIC_MODEL_CONTEXT_TOKENS.get(selected) or MODEL_CONTEXT_TOKENS.get(selected) or MODEL_CONTEXT_TOKENS.get(unqualified)


def estimate_tokens(value: str) -> int:
    # Conservative tokenizer-independent estimate suitable for preflight.
    return (len(value.encode("utf-8")) + 2) // 3


def estimate_image_tokens(image_paths: list[Path] | None) -> int:
    """Conservative tile estimate; unreadable dimensions make capacity unknowable."""
    import fitz

    total = 0
    for path in image_paths or []:
        try:
            pixmap = fitz.Pixmap(path)
            tiles = ((pixmap.width + 511) // 512) * ((pixmap.height + 511) // 512)
        except Exception as error:
            raise ModelCapacityError(path.name, 0, None) from error
        total += 512 + tiles * 512
    return total


def analysis_required_tokens(prompt: str, image_paths: list[Path] | None = None) -> int:
    return estimate_tokens(f"{ANALYSIS_SYSTEM}\n\n{prompt}") + estimate_image_tokens(image_paths) + ANALYSIS_RESPONSE_RESERVE_TOKENS + ANALYSIS_SAFETY_MARGIN_TOKENS


def model_supports_multimodal(model: str | None) -> bool:
    selected = resolve_text_model(model)
    return selected in DYNAMIC_MULTIMODAL_MODELS or selected in MODEL_MULTIMODAL or selected.split("/", 1)[-1] in MODEL_MULTIMODAL


def validate_analysis_capacity(prompt: str, model: str | None, image_paths: list[Path] | None = None) -> dict[str, int | str]:
    selected = resolve_text_model(model)
    required = analysis_required_tokens(prompt, image_paths)
    capacity = model_capacity_tokens(selected)
    if not model_supports_multimodal(selected):
        raise ModelCapacityError(selected, required, capacity)
    if capacity is None or required > capacity:
        raise ModelCapacityError(selected, required, capacity)
    return {"model": selected, "required_tokens": required, "capacity_tokens": capacity}


def build_analysis_prompt(extracted: ExtractedPaper, visuals: list[dict[str, Any]] | None = None) -> str:
    text = format_guided_reading_text(extracted)
    visual_manifest = json.dumps([{key: item.get(key) for key in ("id", "page_number", "nearby_text")} for item in visuals or []], ensure_ascii=False)
    return render_prompt("analysis_user.md", title=extracted.title, visual_manifest=visual_manifest, text=text)


def format_analysis_text(extracted: ExtractedPaper) -> str:
    if not extracted.pages:
        return sanitize_prompt_text(extracted.full_text)

    parts = []
    for page in extracted.pages:
        page_number = int(page.get("page_number", len(parts) + 1))
        text = sanitize_prompt_text(str(page.get("text", ""))).strip()
        if text:
            parts.append(f"[Page {page_number}]\n{text}")
    return "\n\n".join(parts)


def format_guided_reading_text(extracted: ExtractedPaper) -> str:
    if not extracted.pages:
        text, _ = without_reference_section(sanitize_prompt_text(extracted.full_text))
        return normalize_text(text)

    parts = []
    for page in extracted.pages:
        page_number = int(page.get("page_number", len(parts) + 1))
        text = sanitize_prompt_text(str(page.get("text", ""))).strip()
        text, found_references = without_reference_section(text)
        text = normalize_text(text)
        if text:
            parts.append(f"[Page {page_number}]\n{text}")
        if found_references:
            break

    return "\n\n".join(parts) or format_analysis_text(extracted)


def without_reference_section(text: str) -> tuple[str, bool]:
    match = REFERENCES_START_RE.search(text)
    if not match:
        return text, False
    return text[: match.start()], True


def parse_json_payload(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
    if fenced:
        cleaned = fenced.group(1).strip()

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("AI response did not contain a JSON object.")

    return json.loads(cleaned[start : end + 1], strict=False)


def run_openai(
    prompt: str,
    system_prompt: str,
    expect_json: bool,
    api_key: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    image_paths: list[Path] | None = None,
) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=openai_api_key(api_key))
    user_content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
    for image_path in image_paths or []:
        user_content.append({"type": "input_text", "text": f"Visual image {image_path.stem}:"})
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        user_content.append({"type": "input_image", "image_url": f"data:image/jpeg;base64,{encoded}"})
    response = client.responses.create(
        model=resolve_text_model(model),
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        reasoning={"effort": resolve_reasoning_effort(reasoning_effort, "OPENAI_REASONING_EFFORT")},
        temperature=0.2,
    )
    return response.output_text


def openrouter_headers(api_key: str | None = None) -> dict[str, str]:
    key = openrouter_api_key(api_key)
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not set.")
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://127.0.0.1:8788",
        "X-Title": "PaperSprint",
    }


def openrouter_response_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not choices:
        raise RuntimeError("OpenRouter response did not contain a completion.")
    message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
    content = message.get("content", "")
    if isinstance(content, list):
        return "\n".join(str(item.get("text", "")) for item in content if isinstance(item, dict)).strip()
    return str(content).strip()


def openrouter_reasoning(reasoning_effort: str | None) -> dict[str, str] | None:
    effort = resolve_reasoning_effort(reasoning_effort, "OPENROUTER_REASONING_EFFORT", "OPENAI_REASONING_EFFORT")
    if effort == "none":
        return None
    return {"effort": effort}


def run_openrouter(
    prompt: str,
    system_prompt: str,
    expect_json: bool,
    api_key: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    image_paths: list[Path] | None = None,
) -> str:
    user_content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for image_path in image_paths or []:
        user_content.append({"type": "text", "text": f"Visual image {image_path.stem}:"})
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        user_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}})
    body: dict[str, Any] = {
        "model": model or os.getenv("OPENROUTER_MODEL") or "openai/gpt-5.5",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.2,
    }
    reasoning = openrouter_reasoning(reasoning_effort)
    if reasoning:
        body["reasoning"] = reasoning
    if expect_json:
        body["response_format"] = {"type": "json_object"}

    response = requests.post(
        f"{OPENROUTER_BASE_URL}/chat/completions",
        headers=openrouter_headers(api_key),
        json=body,
        timeout=int(os.getenv("OPENROUTER_TIMEOUT_SECONDS", "180")),
    )
    response.raise_for_status()
    return openrouter_response_text(response.json())


def run_codex(
    prompt: str,
    timeout_seconds: int | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> str:
    codex_path = shutil.which("codex")
    if not codex_path:
        raise RuntimeError("Codex CLI is not installed or not on PATH.")

    prompt = sanitize_prompt_text(prompt)
    timeout = timeout_seconds or int(os.getenv("CODEX_TIMEOUT_SECONDS", "180"))
    selected_model = resolve_text_model(model)
    with tempfile.TemporaryDirectory() as tmp_dir:
        output_path = Path(tmp_dir) / "last-message.txt"
        args = [
            codex_path,
            "--ask-for-approval",
            "never",
            "--sandbox",
            "read-only",
            "exec",
            "--skip-git-repo-check",
            "--ephemeral",
            "--color",
            "never",
            "-c",
            f"model_reasoning_effort={json.dumps(resolve_reasoning_effort(reasoning_effort, 'CODEX_REASONING_EFFORT', 'OPENAI_REASONING_EFFORT'))}",
            "-o",
            str(output_path),
            prompt,
        ]
        if selected_model:
            args[5:5] = ["-m", selected_model]

        try:
            result = subprocess.run(
                args,
                cwd=Path(__file__).resolve().parent.parent,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(
                f"Codex timed out after {timeout} seconds with model {selected_model}. "
                "Try lower reasoning effort or set CODEX_ANALYSIS_TIMEOUT_SECONDS higher."
            ) from error
        if output_path.exists():
            output = output_path.read_text(encoding="utf-8").strip()
            if output:
                return output
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "Codex failed.").strip()
            raise RuntimeError(message[:1200])
        return result.stdout.strip()


def run_ai(
    prompt: str,
    system_prompt: str,
    provider: str,
    expect_json: bool,
    api_key: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    timeout_seconds: int | None = None,
    image_paths: list[Path] | None = None,
) -> tuple[str, str]:
    selected = choose_provider(provider, api_key)
    if selected == "openai":
        if not openai_api_key(api_key):
            raise RuntimeError("OPENAI_API_KEY is not set.")
        return run_openai(prompt, system_prompt, expect_json, api_key, model, reasoning_effort, image_paths), "openai"
    if selected == "openrouter":
        if not openrouter_api_key(api_key):
            raise RuntimeError("OPENROUTER_API_KEY is not set.")
        return run_openrouter(prompt, system_prompt, expect_json, api_key, model, reasoning_effort, image_paths), "openrouter"
    if selected == "codex":
        visual_paths = "\n".join(f"- {path.resolve()}" for path in image_paths or [])
        codex_prompt = f"{system_prompt}\n\n{prompt}"
        if visual_paths:
            codex_prompt += f"\n\nInspect every visual image at these paths directly:\n{visual_paths}"
        return run_codex(
            codex_prompt,
            timeout_seconds=timeout_seconds,
            model=model,
            reasoning_effort=reasoning_effort,
        ), "codex"
    raise RuntimeError(f"Unknown AI provider: {provider}")


def normalize_highlight_snippet(value: str) -> str:
    """Normalize a generated passage while preserving its complete contiguous text."""
    return normalize_text(str(value))


def normalize_supporting_excerpt(value: str) -> str:
    excerpt = normalize_text(str(value))
    if len(excerpt) <= MAX_TAKEAWAY_EXCERPT_CHARS:
        return excerpt

    window = excerpt[: MAX_TAKEAWAY_EXCERPT_CHARS + 1]
    sentence_ends = [window.rfind(marker) for marker in (".", "?", "!")]
    sentence_end = max(sentence_ends)
    if sentence_end >= MAX_TAKEAWAY_EXCERPT_CHARS * 0.55:
        return window[: sentence_end + 1].strip()

    return window.rsplit(" ", 1)[0].rstrip(",;:") or window.strip()


def normalize_reference_id(value: Any, fallback: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value or "").strip()).strip("-").lower()
    return (text[:48] or fallback).strip("-") or fallback


def normalize_analysis(payload: dict[str, Any], extracted: ExtractedPaper) -> dict[str, Any]:
    raw_sections = payload.get("narrative_sections")
    if not isinstance(raw_sections, list) or not raw_sections:
        raise ValueError("Analysis did not return a non-empty Highlight sequence.")

    sections: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for section_index, section in enumerate(raw_sections, start=1):
        if not isinstance(section, dict) or not isinstance(section.get("highlights"), list):
            raise ValueError("Analysis returned a malformed Narrative section.")
        heading = normalize_text(str(section.get("heading", "")))
        if not heading:
            raise ValueError("Every Narrative section requires a heading.")
        highlights = []
        for item in section["highlights"]:
            if not isinstance(item, dict):
                raise ValueError("Analysis returned a malformed Highlight.")
            text = normalize_text(str(item.get("text", "")))
            source = item.get("source")
            if not text or not isinstance(source, dict):
                raise ValueError("Every Highlight requires synthesized text and one source.")
            source_type = str(source.get("type", ""))
            if source_type == "text":
                anchor = normalize_text(str(source.get("anchor", "")))
                try:
                    page_hint = int(source.get("page_hint"))
                except (TypeError, ValueError):
                    raise ValueError("Text sources require a copied anchor and page hint.") from None
                if not anchor or page_hint < 1:
                    raise ValueError("Text sources require a copied anchor and page hint.")
                clean_source = {"type": "text", "anchor": anchor, "page_hint": page_hint}
            elif source_type == "figure":
                visual_id = normalize_reference_id(source.get("visual_id"), "")
                if not visual_id:
                    raise ValueError("Figure sources require a prepared visual id.")
                clean_source = {"type": "figure", "visual_id": visual_id}
            else:
                raise ValueError("Every Highlight source must be text or figure.")

            fallback_id = f"h{len(used_ids) + 1}"
            highlight_id = normalize_reference_id(item.get("id"), fallback_id)
            while highlight_id in used_ids:
                highlight_id = f"{fallback_id}-{len(used_ids) + 1}"
            used_ids.add(highlight_id)
            highlights.append({
                "id": highlight_id,
                "text": text,
                "label": str(item.get("label", "important")),
                "source": clean_source,
            })
        if highlights:
            sections.append({"heading": heading[:160], "highlights": highlights})

    if not sections or not used_ids:
        raise ValueError("Analysis did not return a non-empty Highlight sequence.")

    raw_figures = payload.get("figures", [])
    figures = []
    if isinstance(raw_figures, list):
        for item in raw_figures:
            if not isinstance(item, dict):
                continue
            visual_id = normalize_reference_id(item.get("id") or item.get("visual_id"), "")
            if not visual_id:
                continue
            figures.append({
                "id": visual_id,
                "label": normalize_text(str(item.get("label") or item.get("title") or "Visual"))[:180],
                "title": normalize_text(str(item.get("title") or item.get("label") or "Visual"))[:180],
                "type": normalize_text(str(item.get("type") or "figure"))[:40],
                "explanation": normalize_text(str(item.get("interpretation") or item.get("explanation") or "")),
                "why_it_matters": normalize_text(str(item.get("why_it_matters") or "")),
            })

    return {
        "title": normalize_text(str(payload.get("title") or extracted.title))[:220],
        "narrative_sections": sections,
        "figures": figures,
    }

def analyze_paper(
    pdf_path: Path,
    extracted: ExtractedPaper,
    provider: str | None,
    api_key: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    visuals: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    selected_provider = choose_provider(provider, api_key)
    prompt = build_analysis_prompt(extracted, visuals)
    image_paths = list(dict.fromkeys(
        Path(path)
        for item in visuals or []
        for path in (item.get("image_path"), item.get("page_image_path"))
        if path
    ))
    validate_analysis_capacity(prompt, model, image_paths)
    output, provider_used = run_ai(
        prompt,
        ANALYSIS_SYSTEM,
        selected_provider,
        True,
        api_key,
        model,
        reasoning_effort,
        int(os.getenv("CODEX_ANALYSIS_TIMEOUT_SECONDS", os.getenv("CODEX_TIMEOUT_SECONDS", "600"))),
        image_paths,
    )
    analysis = normalize_analysis(parse_json_payload(output), extracted)

    visual_records = []
    interpretations = {item["id"]: item for item in analysis.get("figures", [])}
    missing_interpretations = [item["id"] for item in visuals or [] if item["id"] not in interpretations]
    if missing_interpretations:
        raise ValueError("Analysis did not interpret every prepared substantive visual.")
    for visual in visuals or []:
        interpretation = interpretations.get(visual["id"], {})
        visual_records.append({**visual, **interpretation})
    known_visual_ids = {item["id"] for item in visual_records}
    for section in analysis["narrative_sections"]:
        for highlight in section["highlights"]:
            source = highlight["source"]
            if source["type"] == "figure" and source["visual_id"] not in known_visual_ids:
                raise ValueError("A Highlight references an unknown Figure source.")
    processed = process_narrative_sections(
        pdf_path,
        analysis["narrative_sections"],
        format_guided_reading_text(extracted),
        visual_records,
    )
    analysis["narrative_sections"] = processed["narrative_sections"]
    analysis["figures"] = visual_records
    analysis["analysis_text"] = format_guided_reading_text(extracted)
    analysis["provider_used"] = provider_used
    return analysis


def build_citation_validation_prompt(citations: list[dict[str, Any]]) -> str:
    candidates = []
    for citation in citations:
        citation_id = str(citation.get("id", "")).strip()
        if not citation_id:
            continue
        for context_index, context in enumerate(citation.get("contexts", [])):
            candidates.append(
                {
                    "citation_id": citation_id,
                    "context_index": context_index,
                    "label": citation.get("label", ""),
                    "marker": context.get("marker", ""),
                    "page_number": context.get("page_number"),
                    "sentence": context.get("sentence", ""),
                    "reference_title": citation.get("title", ""),
                    "reference_authors": citation.get("authors", ""),
                    "reference_year": citation.get("year", ""),
                    "raw_reference": str(citation.get("raw_reference", ""))[:700],
                    "resolved": bool(citation.get("resolved")),
                }
            )
            if len(candidates) >= MAX_CITATION_VALIDATION_CONTEXTS:
                return render_prompt(
                    "citation_validation_user.md",
                    candidates_json=json.dumps(candidates, ensure_ascii=False),
                )

    return render_prompt(
        "citation_validation_user.md",
        candidates_json=json.dumps(candidates, ensure_ascii=False),
    )


def validate_citations(
    citations: list[dict[str, Any]],
    provider: str | None,
    api_key: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> list[dict[str, Any]]:
    if not any(citation.get("contexts") for citation in citations):
        return citations
    if os.getenv("CITATION_AI_VALIDATION", "1").strip().lower() in {"0", "false", "no"}:
        return citations

    output, _ = run_ai(
        build_citation_validation_prompt(citations),
        CITATION_VALIDATION_SYSTEM,
        choose_provider(provider, api_key),
        True,
        api_key,
        model,
        reasoning_effort,
        int(os.getenv("CODEX_CITATION_TIMEOUT_SECONDS", os.getenv("CODEX_TIMEOUT_SECONDS", "180"))),
    )
    payload = parse_json_payload(output)
    rejected = set()
    for item in payload.get("rejected_contexts", []):
        if not isinstance(item, dict):
            continue
        try:
            rejected.add((str(item.get("citation_id", "")).strip(), int(item.get("context_index"))))
        except (TypeError, ValueError):
            continue

    if not rejected:
        return citations

    validated = []
    for citation in citations:
        citation_id = str(citation.get("id", "")).strip()
        contexts = [
            context
            for index, context in enumerate(citation.get("contexts", []))
            if (citation_id, index) not in rejected
        ]
        validated.append({**citation, "contexts": contexts, "context_count": len(contexts)})
    return validated


def select_relevant_excerpts(
    question: str,
    sentence_spans: list[dict[str, Any]],
    max_excerpts: int = 12,
) -> list[dict[str, Any]]:
    scored: list[tuple[float, dict[str, Any]]] = []
    for span in sentence_spans:
        text = str(span.get("text", ""))
        score = score_match(question, text)
        if any(word in question.lower() for word in ["summarize", "overview", "main", "takeaway"]):
            score += 0.1 if int(span.get("page_number", 999)) <= 2 else 0
        if score > 0:
            scored.append((score, span))

    if not scored:
        return sentence_spans[:max_excerpts]

    return [span for _, span in sorted(scored, key=lambda item: item[0], reverse=True)[:max_excerpts]]


def build_chat_prompt(
    paper: dict[str, Any],
    messages: list[dict[str, str]],
    excerpts: list[dict[str, Any]],
    web_results: list[dict[str, str]],
    citation_context: dict[str, Any] | None = None,
    figure_context: list[dict[str, Any]] | None = None,
) -> str:
    history = "\n".join(f"{item['role']}: {item['content']}" for item in messages[-8:])
    excerpt_text = "\n".join(
        f"- p. {item.get('page_number')}: {normalize_text(str(item.get('text', '')))[:700]}" for item in excerpts
    )
    web_text = "\n".join(
        f"- {item['title']} ({item['url']}): {item.get('snippet', '')}" for item in web_results
    )
    citation_text = format_citation_context(citation_context)
    figure_text = format_figure_context([*paper.get("figures", []), *(figure_context or [])])
    highlight_narrative = "\n".join(
        f"## {section.get('heading', 'Narrative')}\n" + "\n".join(
            f"- {highlight.get('text', '')}" for highlight in section.get("highlights", [])
        )
        for section in paper.get("narrative_sections", [])
    )
    return render_prompt(
        "chat_user.md",
        title=paper.get("title", "Untitled"),
        highlight_narrative=highlight_narrative,
        paper_text=paper.get("analysis_text", ""),
        excerpts=excerpt_text,
        citation_context=citation_text,
        figure_context=figure_text,
        web_results=web_text or "None",
        history=history,
    )


def format_citation_context(citation_context: dict[str, Any] | None) -> str:
    if not citation_context:
        return "None"

    contexts = citation_context.get("contexts", [])
    context_lines = []
    for item in contexts[:8]:
        page_number = item.get("page_number") or "?"
        sentence = normalize_text(str(item.get("sentence", "")))
        if sentence:
            context_lines.append(f"- p. {page_number}: {sentence[:700]}")

    return f"""
Label: {citation_context.get("label", "")}
Title: {normalize_text(str(citation_context.get("title", "")))[:300]}
Authors: {normalize_text(str(citation_context.get("authors", "")))[:300]}
Year: {citation_context.get("year", "")}
Reference: {normalize_text(str(citation_context.get("raw_reference", "")))[:1400] or "Reference text not extracted."}
Inline citation contexts:
{chr(10).join(context_lines) if context_lines else "No inline citation context extracted."}
""".strip()


def format_figure_context(figure_context: list[dict[str, Any]] | None) -> str:
    if not figure_context:
        return "None"

    lines = []
    for index, figure in enumerate(figure_context, start=1):
        page_number = figure.get("page_number") or "?"
        title = normalize_text(str(figure.get("title") or figure.get("label") or "Visual"))[:300]
        figure_type = normalize_text(str(figure.get("type", "")))[:80]
        caption = normalize_text(str(figure.get("caption", "")))[:700]
        explanation = normalize_text(str(figure.get("explanation", "")))[:900]
        why_it_matters = normalize_text(str(figure.get("why_it_matters", "")))[:700]
        uncertainty = normalize_text(str(figure.get("uncertainty", "")))[:400]

        parts = [f"Figure {index}: {title}", f"Page: {page_number}"]
        if figure_type:
            parts.append(f"Type: {figure_type}")
        if caption:
            parts.append(f"Caption: {caption}")
        if explanation:
            parts.append(f"Explanation: {explanation}")
        if why_it_matters:
            parts.append(f"Why it matters: {why_it_matters}")
        if uncertainty:
            parts.append(f"Uncertainty: {uncertainty}")
        lines.append("\n".join(parts))

    return "\n\n".join(lines)


def summary_item_text(item: Any) -> str:
    if isinstance(item, dict):
        return normalize_text(str(item.get("text") or item.get("takeaway") or item.get("summary") or ""))
    return normalize_text(str(item))


def build_selection_explanation_prompt(
    paper: dict[str, Any],
    selected_text: str,
    page_number: int | None,
    page_text: str,
) -> str:
    page_label = f"p. {page_number}" if page_number else "unknown page"
    return render_prompt(
        "selection_explanation_user.md",
        title=paper.get("title", "Untitled"),
        overview=paper.get("overview", ""),
        page_label=page_label,
        selected_text=normalize_text(selected_text)[:700],
        page_text=normalize_text(page_text)[:5000],
    )


def answer_selection_explanation(
    paper: dict[str, Any],
    selected_text: str,
    page_number: int | None,
    page_text: str,
    provider: str | None,
    api_key: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    selected_provider = choose_provider(provider, api_key)
    prompt = build_selection_explanation_prompt(paper, selected_text, page_number, page_text)
    answer, provider_used = run_ai(prompt, SELECTION_EXPLANATION_SYSTEM, selected_provider, False, api_key, model, reasoning_effort)

    return {
        "answer": answer.strip(),
        "provider_used": provider_used,
        "warnings": [],
    }


def answer_chat(
    paper: dict[str, Any],
    messages: list[dict[str, str]],
    web_results: list[dict[str, str]],
    provider: str | None,
    citation_context: dict[str, Any] | None = None,
    api_key: str | None = None,
    figure_context: list[dict[str, Any]] | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    last_question = next((item["content"] for item in reversed(messages) if item.get("role") == "user"), "")
    excerpts = select_relevant_excerpts(last_question, paper.get("sentences", []))
    selected_provider = choose_provider(provider, api_key)

    prompt = build_chat_prompt(paper, messages, excerpts, web_results, citation_context, figure_context)
    answer, provider_used = run_ai(prompt, CHAT_SYSTEM, selected_provider, False, api_key, model, reasoning_effort)

    return {
        "answer": answer.strip(),
        "provider_used": provider_used,
        "web_results": web_results,
        "warnings": [],
    }
