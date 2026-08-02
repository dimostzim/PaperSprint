# Unified multimodal Highlight narrative: manual acceptance

Run the app with a paper containing body text, at least one substantive figure/table, citations, and a Manual highlight. Validate both themes and a 13-inch laptop viewport at 100% browser zoom.

- Confirm the top bar shows one Analysis model and no Reading depth, Vision model, or reasoning controls.
- Before analysis, confirm the right pane contains only disabled Chat with “Analyze this paper to start chatting.”
- Analyze and observe staged preparation/narrative status without percentages. Confirm Chat activates only when a non-empty narrative succeeds and starts with no message or suggested prompt.
- Confirm left-pane cards show synthesized prose rather than copied PDF text, with paper-specific section headings and facets.
- Click text-backed and figure-backed Highlights. Confirm each jumps to and strongly selects its source; source type/page are not printed on available cards.
- Confirm clicking a generated source overlay selects and scrolls its Highlight card. Other generated overlays remain visible but de-emphasized.
- Force an unlocatable valid text anchor. Confirm the Highlight remains, displays only “Source unavailable,” and no global incomplete warning appears.
- Select a facet. Confirm only matching generated Highlights appear, the subset cue is visible, and Show full narrative restores cards and overlays.
- Add a Manual highlight. Confirm its PDF overlay appears and is removable from its popover, but it never appears in the generated narrative pane.
- Start reanalysis. Confirm the old narrative and Chat remain usable. Force failure and confirm both remain intact; then succeed and confirm the new narrative swaps atomically, facet resets, Manual overlays remain, and Chat history clears.
- Click a substantive figure and confirm its interpretation reflects the actual visual rather than only its caption and can be added to Chat.
- Confirm citation extraction/validation may finish after Chat activation and citation failure does not disable Chat.
- Collapse and restore the right pane at 100% zoom. Confirm the restore control remains fully visible and clickable.
