import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_URI = (ROOT / "static" / "highlight-navigation.mjs").as_uri()


def run_navigation_script(body: str) -> dict:
    script = f'''
import {{ createHighlightNavigationController, highlightSourceRects }} from "{MODULE_URI}";
{body}
'''
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_figure_source_bbox_becomes_a_pdf_overlay_rectangle():
    payload = run_navigation_script(
        '''
const rects = highlightSourceRects(
  { rects: [], source: { type: "figure", bbox_pct: [10, 20, 60, 80] } },
  { width: 600, height: 800 },
);
console.log(JSON.stringify(rects));
'''
    )

    assert payload == [[60, 160, 360, 640]]


def test_activating_available_highlight_selects_centers_and_opens_source():
    payload = run_navigation_script(
        '''
const state = { activeHighlightIndex: null };
const events = [];
const sourceNodes = [
  { getBoundingClientRect: () => ({ top: 100, left: 40, right: 140, bottom: 120, width: 100, height: 20 }) },
  { getBoundingClientRect: () => ({ top: 124, left: 40, right: 220, bottom: 144, width: 180, height: 20 }) },
];
const controller = createHighlightNavigationController({
  getHighlight: (index) => ({ text: `Highlight ${index}`, navigation_available: true }),
  getVisibleHighlightIndexes: () => [0, 1, 2],
  getActiveHighlightIndex: () => state.activeHighlightIndex,
  getSourceNodes: () => sourceNodes,
  selectHighlight: (index) => { state.activeHighlightIndex = index; events.push(["select", index]); },
  closeCompetingPopovers: () => events.push(["close-others"]),
  centerSource: (rect) => events.push(["center", rect]),
  openHighlightPopover: (index, rect) => events.push(["open", index, rect]),
  hideHighlightPopover: () => events.push(["hide"]),
  flashUnavailableHighlight: (index) => events.push(["flash", index]),
  notifySourceUnavailable: () => events.push(["unavailable"]),
  updateButtons: (buttons) => events.push(["buttons", buttons]),
});
controller.activate(1);
console.log(JSON.stringify({ state, events }));
'''
    )

    assert payload["state"]["activeHighlightIndex"] == 1
    assert payload["events"] == [
        ["close-others"],
        ["select", 1],
        ["center", {"top": 100, "left": 40, "right": 220, "bottom": 144, "width": 180, "height": 44}],
        ["open", 1, {"top": 100, "left": 40, "right": 220, "bottom": 144, "width": 180, "height": 44}],
        ["buttons", {"previousDisabled": False, "nextDisabled": False}],
    ]


def test_next_advances_to_source_unavailable_highlight_without_moving_paper():
    payload = run_navigation_script(
        '''
const state = { activeHighlightIndex: 0 };
const events = [];
const highlights = [
  { navigation_available: true },
  { navigation_available: false },
  { navigation_available: true },
];
const controller = createHighlightNavigationController({
  getHighlight: (index) => highlights[index],
  getVisibleHighlightIndexes: () => [0, 1, 2],
  getActiveHighlightIndex: () => state.activeHighlightIndex,
  getSourceNodes: () => [],
  selectHighlight: (index) => { state.activeHighlightIndex = index; events.push(["select", index]); },
  closeCompetingPopovers: () => events.push(["close-others"]),
  centerSource: () => events.push(["center"]),
  openHighlightPopover: () => events.push(["open"]),
  hideHighlightPopover: () => events.push(["hide"]),
  flashUnavailableHighlight: (index) => events.push(["flash", index]),
  notifySourceUnavailable: () => events.push(["unavailable"]),
  updateButtons: (buttons) => events.push(["buttons", buttons]),
});
controller.step(1);
console.log(JSON.stringify({ state, events }));
'''
    )

    assert payload == {
        "state": {"activeHighlightIndex": 1},
        "events": [
            ["close-others"],
            ["select", 1],
            ["hide"],
            ["flash", 1],
            ["unavailable"],
            ["buttons", {"previousDisabled": False, "nextDisabled": False}],
        ],
    }


def test_closing_popover_preserves_active_highlight_and_navigation_position():
    payload = run_navigation_script(
        '''
const state = { activeHighlightIndex: 1 };
const events = [];
const controller = createHighlightNavigationController({
  getHighlight: () => null,
  getVisibleHighlightIndexes: () => [0, 1, 2],
  getActiveHighlightIndex: () => state.activeHighlightIndex,
  getSourceNodes: () => [],
  selectHighlight: () => {},
  closeCompetingPopovers: () => {},
  centerSource: () => {},
  openHighlightPopover: () => {},
  hideHighlightPopover: () => events.push(["hide"]),
  flashUnavailableHighlight: () => {},
  notifySourceUnavailable: () => {},
  updateButtons: (buttons) => events.push(["buttons", buttons]),
});
controller.closePopover();
console.log(JSON.stringify({ state, events }));
'''
    )

    assert payload == {
        "state": {"activeHighlightIndex": 1},
        "events": [["hide"]],
    }
