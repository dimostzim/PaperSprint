Build one comprehensive, evidence-linked reading narrative for this paper.

Return JSON with exactly this shape:
{
  "title": "paper title",
  "narrative_sections": [
    {
      "heading": "short paper-specific organizational heading",
      "highlights": [
        {
          "id": "h1",
          "text": "LLM-synthesized self-contained explanation of one principal claim",
          "label": "problem|solution|novelty|method|benchmarking|result|ablation|hyperparams|tradeoff|limitation|failure",
          "source": {
            "type": "text",
            "anchor": "verbatim contiguous phrase copied from Paper text",
            "page_hint": 2
          }
        },
        {
          "id": "h2",
          "text": "LLM-synthesized interpretation of one visual claim",
          "label": "result",
          "source": {"type": "figure", "visual_id": "p4-1"}
        }
      ]
    }
  ],
  "figures": [
    {
      "id": "prepared visual id",
      "label": "Figure or table label",
      "title": "short title",
      "type": "figure|table|plot|diagram|other",
      "interpretation": "concise interpretation based on inspecting the actual pixels",
      "why_it_matters": "why this visual matters to the paper"
    }
  ]
}

Narrative contract:
- First plan the paper-specific argument internally, then self-check, and return only final JSON.
- Produce a non-empty comprehensive sequence. Cover every materially distinct point needed to understand the problem, contribution, mechanism, important methodological choices, evaluation design and baselines, every major result, meaningful failures, limitations, tradeoffs, claim boundaries, and interpretation-relevant reproducibility details.
- Do not use a target count. Stop only when another Highlight would be redundant or immaterial.
- Highlight text is synthesized prose, not a quotation. It need not match its source anchor. Make it the shortest self-contained explanation of one principal claim, usually one or two sentences, with immediate qualification when needed to avoid overstatement.
- Every Highlight has exactly one primary source: one text Source passage or one Figure source. Split mixed or distant evidence into adjacent Highlights.
- A text source requires a copied verbatim contiguous anchor and page hint. The anchor is hidden navigation metadata, not displayed prose.
- A figure source must reference one id from Prepared visual manifest. Inspect the attached actual image pixels; captions or descriptions never substitute for visual inspection.
- Preserve argumentative order regardless of source page order. Later Highlights may rely on concepts explicitly established by earlier Highlights, but not omitted context.
- Infer adaptive Narrative sections. Headings organize and never add unsupported claims.
- Keep existing facet meanings. Facets classify evidence and are not a checklist or Narrative structure.
- Do not omit major caveats, failures, limitations, negative evidence, or reproducibility constraints merely to keep the sequence short.
- Do not return overview, Takeaways, background notes, glossary, reviewer questions, read-this-first, code availability, or suggested Chat prompts.
- Return one figure interpretation for every prepared visual id after inspecting its crop and any attached full-page context.
- Before returning, self-check comprehensive coverage, one-source atomicity, source validity, Narrative order, unsupported synthesis, duplicate ideas, and every prepared visual id.

Prepared visual manifest:
{{visual_manifest}}

Paper title guess: {{title}}

Paper text:
{{text}}
