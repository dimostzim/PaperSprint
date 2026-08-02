import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def run_chat_reference_script(script: str):
    if not shutil.which("node"):
        pytest.skip("node is not available")

    result = subprocess.run(
        ["node", "--input-type=module", "-e", textwrap.dedent(script)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_chat_page_reference_segments_detects_common_page_forms():
    payload = run_chat_reference_script(
        """
        import { chatPageReferenceSegments } from "./static/chat_references.js";

        const segments = chatPageReferenceSegments(
          "See pg.1, pg. 2, page 3, and p. 4 for details.",
          4,
        );
        console.log(JSON.stringify(segments));
        """,
    )

    references = [segment for segment in payload if segment.get("pageNumber")]
    assert [segment["text"] for segment in references] == ["pg.1", "pg. 2", "page 3", "p. 4"]
    assert [segment["pageNumber"] for segment in references] == [1, 2, 3, 4]
    assert "".join(segment["text"] for segment in payload) == "See pg.1, pg. 2, page 3, and p. 4 for details."


def test_chat_page_reference_segments_ignores_pages_outside_paper():
    payload = run_chat_reference_script(
        """
        import { chatPageReferenceSegments } from "./static/chat_references.js";

        const segments = chatPageReferenceSegments("page 0, page 2, and page 8", 5);
        console.log(JSON.stringify(segments));
        """,
    )

    references = [segment for segment in payload if segment.get("pageNumber")]
    assert references == [{"text": "page 2", "pageNumber": 2}]
    assert "".join(segment["text"] for segment in payload) == "page 0, page 2, and page 8"
