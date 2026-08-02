Status: ready-for-agent

# Unified Multimodal Highlight Narrative

## Problem Statement

PaperSprint currently treats generated Highlights as verbatim PDF quotations. Visually harmless PDF extraction artifacts can therefore cause useful generated content to be discarded, leaving a warning that the remaining narrative may be incomplete. This makes the reading experience feel untrustworthy even when the model understood the paper correctly.

Reading depth also fragments the product without producing a reliable quality distinction: Balanced can feel like Overview, while the reader actually wants one comprehensive explanation. The summary, background, Takeaways, and unused generated fields duplicate or compete with the Highlight sequence. Figures are analyzed after text generation, so actual visual evidence cannot participate in the narrative. Separate text, vision, and reasoning controls overcrowd the top bar.

## Solution

Make a Highlight an immutable LLM-synthesized narrative point, not a quotation. Each Highlight has one hidden primary source: either one contiguous Source passage selected with a copied anchor and page hint, or one Figure source identified from the actual visual region. The left pane shows only concise synthesized Highlight text and facet labels. Source grounding is best effort and affects navigation only; an unavailable text location never deletes a Highlight or creates a global incompleteness warning.

Replace Reading depth with one comprehensive, uncapped Highlight sequence covering every materially distinct point needed to understand the paper. Generate that sequence, source references, and concise figure interpretations in one multimodal core-analysis call that receives complete analyzable paper text plus every substantive figure/table as actual pixels. Use high-resolution crops with full-page images only when deterministic preparation identifies incomplete or complex crop context.

Reduce the right pane to an initially empty Chat. Chat becomes available only after initial analysis succeeds. Reanalysis is transactional: the existing narrative and Chat remain active while replacement runs, and swap only after complete success.

## User Stories

1. As a paper reader, I want Highlights written as concise explanations, so that I can understand the paper without reading awkward verbatim snippets.
2. As a paper reader, I want generated wording clearly treated as synthesis rather than quotation, so that prose quality is not constrained by PDF extraction artifacts.
3. As a paper reader, I want every Highlight tied to one primary source, so that I can inspect its evidence.
4. As a paper reader, I want a Highlight to use either one Source passage or one Figure source, so that its evidentiary relationship remains clear.
5. As a paper reader, I want mixed or distant evidence split into adjacent Highlights, so that each point remains atomic.
6. As a paper reader, I want only synthesized Highlight text in the narrative pane, so that hidden source anchors do not clutter reading.
7. As a paper reader, I want clicking a Highlight to reveal its source in the PDF, so that I can verify the model's synthesis.
8. As a paper reader, I want Source passages identified by a hidden copied anchor and page hint, so that the model can select evidence independently from its synthesized wording.
9. As a paper reader, I want PDF extraction differences matched tolerantly, so that soft hyphens, ligatures, line wrapping, and whitespace do not prevent navigation.
10. As a paper reader, I want a Highlight retained when its text source cannot be located, so that navigation failure never destroys narrative content.
11. As a paper reader, I want an unlocated Highlight to show a subtle Source unavailable state, so that I know why clicking cannot navigate.
12. As a paper reader, I do not want a global incomplete-sequence warning for source-location failures, so that a valid generated narrative is not presented as untrustworthy.
13. As a paper reader, I want analysis to succeed or fail cleanly, so that no partially discarded narrative is presented as complete.
14. As a paper reader, I want analysis with zero Highlights to fail, so that a successful analysis always contains its core reading product.
15. As a paper reader, I want malformed required Highlight fields to fail analysis, so that structural contract errors are not silently ignored.
16. As a paper reader, I want no automatic AI repair call, so that one model response remains the authoritative analysis attempt.
17. As a paper reader, I want one comprehensive Highlight sequence, so that I do not have to guess which Reading depth is sufficient.
18. As a paper reader, I want the sequence to cover problem, contribution, mechanism, evaluation, major results, limitations, failures, claim boundaries, and interpretation-relevant reproducibility details, so that it is genuinely comprehensive.
19. As a paper reader, I want every materially distinct major result represented, so that the sequence is not merely an abstract-level overview.
20. As a paper reader, I want no target Highlight count, so that paper complexity determines narrative length.
21. As a paper reader, I want no fixed or operational Highlight cap, so that long papers are not truncated after generation.
22. As a paper reader, I want each Highlight to be the shortest self-contained explanation of one claim, so that comprehensive does not mean verbose or repetitive.
23. As a paper reader, I want generated Highlight text never truncated, so that qualifications are preserved.
24. As a paper reader, I want inferred Narrative section headings, so that a long comprehensive sequence remains scannable.
25. As a paper reader, I want existing facets retained, so that I can inspect targeted subsets.
26. As a paper reader, I want facet filters to remain explicit subsets with Show full narrative, so that filtering is never mistaken for a complete explanation.
27. As a paper reader, I want reanalysis to clear an active facet filter, so that a new narrative opens in full.
28. As a paper reader, I want generated Highlights immutable, so that manual edits cannot invalidate the model's coherent sequence.
29. As a paper reader, I want generated Highlights replaceable only through reanalysis, so that correction has one clear mechanism.
30. As a paper reader, I want Manual highlights preserved as PDF annotations, so that my work survives reanalysis.
31. As a paper reader, I do not want Manual highlights mixed into the generated narrative pane, so that personal excerpts do not interrupt the paper's explanation.
32. As a paper reader, I want Manual highlights removable from their PDF popovers, so that I can manage annotations without a separate pane.
33. As a paper reader, I want all generated source overlays visible in the PDF, so that important evidence remains scannable.
34. As a paper reader, I want the selected source visually dominant and other overlays de-emphasized but visible, so that evidence focus is obvious.
35. As a paper reader, I want Highlight-to-source and source-to-Highlight navigation, so that narrative and evidence remain synchronized.
36. As a paper reader, I want Previous and Next to follow narrative order, so that source page order never controls the story.
37. As a paper reader, I want Figure sources based on actual pixels, so that chart, diagram, and table evidence is interpreted visually.
38. As a paper reader, I want figure-backed Highlights to jump to the exact visual region, so that I can inspect the evidence.
39. As a paper reader, I want crop-first visual input, so that axes, legends, labels, and table cells remain readable to the model.
40. As a paper reader, I want full rendered pages included when crop context is uncertain or complex, so that relevant legends, captions, and connected regions are not lost.
41. As a paper reader, I want every substantive figure and table considered, so that visual evidence is not silently sampled.
42. As a paper reader, I want decorative images excluded, so that logos and publisher ornaments do not waste model capacity.
43. As a paper reader, I want ambiguous visuals treated as substantive, so that completeness wins over cost.
44. As a paper reader, I want analysis rejected before the AI call when complete text and substantive visuals cannot fit, so that no incomplete input is presented as comprehensive.
45. As a paper reader, I want one core multimodal analysis call, so that text and visual evidence form one coherent narrative.
46. As a paper reader, I want concise figure interpretations generated in that call, so that figure popovers and Chat retain useful context without a separate figure-analysis operation.
47. As a paper reader, I want initial Chat disabled until analysis succeeds, so that it always operates against a complete analysis snapshot.
48. As a paper reader, I want the right pane to contain only Chat, so that it does not duplicate the narrative.
49. As a paper reader, I want Chat to start empty, so that the interface does not prescribe questions.
50. As a paper reader, I want a quiet pre-analysis, analyzing, and failed status in disabled Chat, so that its availability is understandable.
51. As a paper reader, I want Chat to use extracted text, the complete Highlight sequence, and figure interpretations, so that answers have full analysis context.
52. As a paper reader, I want provider and model changes to apply to the next analysis only, so that an existing narrative and Chat remain one coherent snapshot.
53. As a paper reader, I want reanalysis to preserve my current narrative and Chat while it runs, so that replacement is non-destructive.
54. As a paper reader, I want failed reanalysis to leave the existing analysis and Chat untouched, so that an attempted improvement cannot erase a working experience.
55. As a paper reader, I want successful reanalysis to atomically replace generated Highlights, sources, Narrative sections, and figure interpretations, so that generated state is internally consistent.
56. As a paper reader, I want successful reanalysis to clear Chat history, so that old answers are not mixed with a new analysis snapshot.
57. As a paper reader, I want to keep chatting and adding Manual highlights during reanalysis, so that background work does not block reading.
58. As a paper reader, I want Manual highlights created during reanalysis preserved through the swap, so that concurrent annotations are not lost.
59. As a paper reader, I want figure crops reused when the PDF and crop algorithm version are unchanged, so that reanalysis avoids unnecessary rendering.
60. As a paper reader, I want citation extraction and AI validation to remain available, so that clickable references remain accurate.
61. As a paper reader, I do not want citation validation to block Highlights or Chat, so that a citation-specific failure does not break the core experience.
62. As a paper reader, I want staged analysis status without fake percentages, so that I understand preparation, visual processing, narrative generation, and source finalization.
63. As a paper reader, I want one Analysis model control, so that separate text and vision choices cannot create conflicting interpretations.
64. As a paper reader, I want only known multimodal models offered, so that selected models support text, image input, structured output, and capacity enforcement.
65. As a paper reader, I want the analysis model to use a fixed high-quality reasoning effort, so that quality is not weakened by a crowded control.
66. As a paper reader, I want a compact top bar with provider, Analysis model, PDF choice, Analyze/Reanalyze, zoom, and theme, so that controls remain usable on laptop screens.
67. As a paper reader, I want the provider/model recorded with a successful analysis used for its Chat session, so that model changes do not silently alter an existing snapshot.
68. As a maintainer, I want old cached schemas invalidated, so that quotation-based and Reading-depth assumptions cannot leak into the new product.
69. As a maintainer, I want analysis artifacts swapped transactionally, so that concurrent Manual highlight updates and failed replacements cannot corrupt persisted state.
70. As a maintainer, I want substantive-visual preparation deterministic and versioned, so that crops can be reused safely.

## Implementation Decisions

- Replace the quotation-based Highlight schema with synthesized `text`, one facet, stable identity, Narrative ordering metadata, and exactly one source reference.
- A text source reference contains a non-empty copied anchor and page hint. The anchor is hidden from the narrative pane and is used only for tolerant grounding and PDF overlay creation.
- A figure source reference contains a valid prepared figure-region identity. Invalid or missing source references are structural analysis failures; failure to locate an otherwise valid text anchor is navigation unavailability, not analysis failure.
- Source-passage matching will tolerate source-equivalent PDF artifacts such as soft hyphens, line-wrap hyphenation, whitespace variation, and common ligatures while preserving source coordinates. It will not rewrite the synthesized Highlight.
- Remove sequence completeness and warning fields. Model responses are accepted only when they contain a structurally valid non-empty sequence; otherwise analysis fails.
- Remove Reading depth from UI, request, prompt, persistence, cache identity, and public representation.
- Remove the operational generated-Highlight cap and all post-response truncation. Capacity preflight reserves sufficient structured-output capacity and rejects models/papers that cannot fit.
- Keep adaptive Narrative sections and existing semantic facets. Array order remains authoritative.
- Generated Highlights cannot be edited or deleted individually. Reanalysis is the only replacement mechanism.
- Manual highlights remain separately persisted PDF annotations and overlays. They do not appear in the generated narrative pane and remain removable through their PDF interaction.
- Build one deterministic visual-preparation stage before the model call. Numbered/captioned figures and tables, charts, diagrams, architectures, flowcharts, and data tables are substantive. Logos, publisher marks, repeated headers/footers, icons, and tiny ornaments are decorative. Ambiguous visuals are substantive.
- Prepare a high-resolution crop including visual, legend, and caption plus extracted caption/nearby text. Add a full-page render when crop confidence is low, content spans disconnected regions, relevant context lies outside the crop, or layout is complex.
- Fail before the core AI call if any substantive visual cannot be rendered or if complete text plus every substantive visual and output reserve cannot fit the selected model.
- Replace separate text analysis and post-analysis figure-description calls with one core multimodal structured-output call. It receives complete analyzable paper text and prepared actual visual images, and returns Narrative sections, Highlights, source references, and concise figure interpretations.
- The unified core call remains one shot. No reviewer, repair, or figure-description AI call is added to that core path.
- Retain deterministic citation extraction/grounding and background AI citation validation. Citation work does not determine analysis success or Chat availability.
- Analysis has staged status values for text preparation, visual preparation, narrative generation, and source finalization, but no synthetic percentage.
- Initial analysis activates Chat only after the complete generated snapshot succeeds.
- Reanalysis builds a candidate snapshot without clearing the current one. Successful completion atomically swaps generated content, records the provider/model, clears Chat history client-side, resets facet filtering, and reads the latest Manual highlights during the swap. Failure leaves the previous snapshot untouched.
- Replace separate Text model, Vision model, Reading depth, and reasoning controls with provider and one Analysis model selector. Models are offered only when known to support multimodal input, structured output, and enforceable context/output capacity. Unknown-capability models are excluded, including for text-only papers.
- Use fixed high reasoning effort for core analysis. The successful analysis provider/model remains the Chat model for that snapshot until successful reanalysis.
- Remove visible overview, background, Takeaways, paper header, and resize handles from the right pane. Stop generating and persisting overview-like auxiliary fields that are no longer rendered: background notes, Takeaways, read-this-first, not-shown, code availability, reviewer questions, glossary, and generated questions.
- Chat is the only right-pane content. Before success it is disabled with a quiet state message; after success it starts empty with no suggested actions.
- Chat context uses complete extracted paper text/excerpts, the full generated Highlight sequence, figure interpretations, and explicitly selected citation/figure/text context.
- Generated source overlays remain visible. Selecting a Highlight jumps to and emphasizes its text or figure source while de-emphasizing but retaining other generated overlays. Clicking a source overlay selects and scrolls to the matching Highlight. Narrative Previous/Next behavior remains authoritative.
- Source type and page stay hidden in available Highlight cards. Only unavailable navigation gets a subtle per-Highlight status.
- Bump generated-analysis and visual-preparation versions; old cached records are invalidated without migration.

## Testing Decisions

- Tests verify behavior through the highest existing seams, primarily the paper-analysis API boundary with a synthetic PDF, prepared visual fixtures, and a stubbed multimodal model response.
- API tests will assert a synthesized Highlight survives even when its text does not occur in the PDF, while its hidden source anchor controls grounding.
- API tests will assert source-equivalent PDF artifacts ground successfully and an unlocatable valid anchor retains the Highlight with navigation unavailable and no global warning.
- API tests will assert text-backed and figure-backed Highlights preserve stable identity and Narrative order through processing, persistence, cache reload, public serialization, overlays, and takeaway-free Chat context.
- API tests will assert malformed source references, malformed sections, and zero Highlights fail the initial analysis without activating Chat.
- API tests will assert no generated Highlight count cap or output truncation is applied.
- Prompt-boundary tests will assert comprehensive semantic coverage, one-shot self-checking, synthesized text, one-source atomicity, actual visual input, and the absence of Reading depth and obsolete summary fields.
- Multimodal adapter tests will assert actual crop/full-page image payloads are sent with paper text for OpenAI, OpenRouter, and Codex adapters without asserting private payload-building helper names.
- Visual-preparation tests will use synthetic PDFs to assert crop-first output, full-page fallback conditions, substantive/decorative classification, exact region metadata, and failure when substantive visuals cannot be prepared.
- Capacity tests will assert complete text and every substantive image fit before the model runs; oversized/unknown-capability models fail without invoking the runner or mutating current analysis.
- Transactional API tests will assert existing generated content, Chat eligibility, figures, and latest Manual highlights survive in-progress and failed reanalysis, then swap only on successful completion.
- Citation tests will assert validation remains asynchronous and citation failure does not block successful analysis or Chat.
- Reader-level behavior will be tested at the broadest practical rendered seam. If no browser harness is introduced, manual acceptance must cover Chat-only right pane, disabled states, empty Chat, facet restoration, source unavailable status, bidirectional text/figure selection, overlay dominance, Manual-overlay deletion, reanalysis swap, and laptop top-bar usability.
- Existing FastAPI analysis/cache tests, PDF grounding tests, figure crop tests, and rendered-reader manual acceptance provide prior art.
- Tests must not assert exact prompt prose, internal storage layout, exact CSS values, or private helper names. They should assert user-visible synthesis, source navigation, failure/transaction semantics, comprehensive input, and persistence behavior.

## Out of Scope

- User-selectable Reading depth or reasoning effort.
- Separate Text and Vision model selection.
- Text-only Analysis models, even for papers without substantive visuals.
- Multiple source references for one Highlight.
- Showing exact source excerpts, source type, or page metadata in available Highlight cards.
- Editing, deleting, reordering, or renaming generated Highlights and Narrative sections.
- Mixing Manual highlights into the generated narrative pane.
- A dedicated Manual-annotation management pane.
- Suggested Chat prompts, visible summary, Takeaways, Background, glossary, reviewer-question, read-this-first, code-availability, or not-shown panels.
- AI repair, reviewer, chunking, sampling, or multi-pass core narrative generation.
- Silent omission of substantive visuals or silent truncation of paper text/output.
- Blocking core analysis on citation validation.
- Migrating or compatibility-rendering old analysis schemas.

## Further Notes

- The original specification's verbatim-Highlight trust model is deliberately superseded: source evidence remains in the PDF, while the Highlight is explicitly synthesized prose.
- The success-or-failure contract applies to the generated snapshot's structural validity and complete model input, not to best-effort coordinate location for a valid text source anchor.
- The one-call constraint applies to the core multimodal paper analysis. Interactive Chat and background citation validation remain separate AI operations.
- The existing implementation currently analyzes figures after text and uses figure descriptions as a second product. That flow must be inverted and unified so actual pixels can influence the Narrative.
