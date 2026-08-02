# PaperSprint

PaperSprint helps readers understand research papers through an evidence-grounded reading experience.

## Language

**Highlight**:
An immutable LLM-synthesized narrative point expressed as one coherent, untruncated text field and linked to exactly one primary source: either one contiguous Source passage or one Figure source. Its text is the shortest self-contained explanation of one principal claim, usually one or two sentences, and grows only when immediate qualification prevents overstatement. Each Highlight makes one principal claim; ideas requiring distant or mixed text-and-visual evidence are split into adjacent Highlights. Its wording explains the paper and is not a quotation, so it need not match a Source passage; the source remains visible in the PDF rather than being repeated in the highlight pane. Generated Highlights can be replaced only through reanalysis, not individually removed or edited.
_Avoid_: Source passage, quotation, annotation, highlight comment

**Source passage**:
A contiguous region of paper text selected by the LLM to support a Highlight and determine its PDF overlay and jump-to-source location. The model identifies it with a hidden copied anchor and page hint; PaperSprint locates that anchor tolerantly against PDF extraction artifacts. Its wording is source evidence, but it is not repeated in the highlight pane. Locating it is best effort: a Highlight remains normal narrative content when its source location is unavailable, shows a subtle per-Highlight “Source unavailable” status, and disables source navigation without creating a global warning. Available source type and page metadata stay hidden in the narrative pane; clicking reveals the source in the PDF.
_Avoid_: Highlight, figure source

**Figure source**:
An actual visual region of a paper figure, chart, diagram, or table that supports a Highlight and determines its PDF overlay and jump-to-source location. The model generating the Highlight sequence inspects a high-resolution crop containing the visual, legend, and caption alongside extracted caption and nearby page text. A full rendered page is additionally supplied when deterministic crop confidence is low, the visual spans disconnected regions, context lies outside the crop, or the layout is unusually complex; full pages are not sent by default. Previously generated descriptions never substitute for the actual pixels. Available source type and page metadata stay hidden in the narrative pane; clicking reveals the source in the PDF.
_Avoid_: Figure description, source passage, Highlight

**Highlight sequence**:
An ordered, non-empty set of Highlights whose complete, unfiltered narrative comprehensively explains every materially distinct point needed to understand the paper: its problem, contribution, mechanism, evaluation, major results, meaningful failures and limitations, claim boundaries, and interpretation-relevant reproducibility details across both text and substantive visuals. It has no target count or operational Highlight cap and stops when another Highlight would be redundant or immaterial. Its order follows the paper's argument as inferred from the paper itself, rather than sources' physical positions; filtered subsets need not be self-contained. Analysis succeeds only when it produces a structurally valid, non-empty Highlight sequence; otherwise analysis fails and Chat remains unavailable. Complete analyzable text and every substantive figure/table must fit the selected model's multimodal capacity before analysis starts; decorative images may be excluded, but substantive visuals are never silently sampled or omitted.
_Avoid_: Highlight list, document order, reading depth

**Narrative section**:
A paper-specific, generated heading and its Highlights within a Highlight sequence. The heading organizes the paper's argument without adding claims beyond the Highlights it contains.
_Avoid_: Facet, paper section

**Manual highlight**:
A reader-selected PDF annotation that remains separate from the generated Highlight sequence. It stays attached to its paper passage and survives reanalysis, but does not appear in or interrupt the narrative pane; a separate annotations view may expose Manual highlights later.
_Avoid_: Highlight, narrative section

**Chat**:
The reader's interactive workspace for asking questions about an analyzed paper. It is the only content in the right pane, starts empty, and remains unavailable until initial analysis succeeds; it may use the completed Highlight sequence, figure interpretations, and extracted paper text as context. During reanalysis, the existing successful analysis and Chat remain available. Chat history clears only when a complete replacement analysis is successfully installed; failed reanalysis leaves the existing narrative and conversation intact.
_Avoid_: Summary pane, suggested prompts

**Citation validation**:
A background AI check that removes false or mismatched clickable citation contexts after deterministic citation extraction and grounding. It remains useful but never blocks the Highlight sequence, successful analysis, or Chat activation; failure affects citations only.
_Avoid_: Paper analysis, highlight verification
