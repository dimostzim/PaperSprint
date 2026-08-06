const MAX_SOURCE_RECT_PAGE_AREA_RATIO = 0.9;

function usefulSourceRects(rects, pageWidth, pageHeight) {
  const pageArea = pageWidth * pageHeight;
  return rects.filter((rect) => {
    if (!Array.isArray(rect) || rect.length !== 4 || rect.some((value) => !Number.isFinite(Number(value)))) {
      return false;
    }
    const [x0, y0, x1, y1] = rect.map(Number);
    return x1 > x0
      && y1 > y0
      && ((x1 - x0) * (y1 - y0)) / pageArea < MAX_SOURCE_RECT_PAGE_AREA_RATIO;
  });
}

export function highlightSourceRects(highlight, pageSize) {
  const pageWidth = Number(pageSize?.width);
  const pageHeight = Number(pageSize?.height);
  if (!Number.isFinite(pageWidth) || !Number.isFinite(pageHeight) || pageWidth <= 0 || pageHeight <= 0) {
    return [];
  }

  if (Array.isArray(highlight?.rects) && highlight.rects.length) {
    return usefulSourceRects(highlight.rects, pageWidth, pageHeight);
  }

  const bbox = Array.isArray(highlight?.source?.bbox_pct)
    ? highlight.source.bbox_pct.map(Number)
    : [];
  if (bbox.length !== 4 || bbox.some((value) => !Number.isFinite(value))) {
    return [];
  }

  const [x0, y0, x1, y1] = bbox.map((value) => Math.max(0, Math.min(100, value)));
  return usefulSourceRects([[
    pageWidth * x0 / 100,
    pageHeight * y0 / 100,
    pageWidth * x1 / 100,
    pageHeight * y1 / 100,
  ]], pageWidth, pageHeight);
}

export function combinedClientRect(nodes) {
  const rects = Array.from(nodes || [], (node) => node.getBoundingClientRect());
  if (!rects.length) {
    return null;
  }

  const top = Math.min(...rects.map((rect) => rect.top));
  const left = Math.min(...rects.map((rect) => rect.left));
  const right = Math.max(...rects.map((rect) => rect.right));
  const bottom = Math.max(...rects.map((rect) => rect.bottom));
  return {
    top,
    left,
    right,
    bottom,
    width: right - left,
    height: bottom - top,
  };
}

export function createHighlightNavigationController({
  getHighlight,
  getVisibleHighlightIndexes,
  getActiveHighlightIndex,
  getSourceNodes,
  selectHighlight,
  closeCompetingPopovers,
  centerSource,
  openHighlightPopover,
  hideHighlightPopover,
  flashUnavailableHighlight,
  notifySourceUnavailable,
  updateButtons,
}) {
  function syncButtons() {
    const indexes = getVisibleHighlightIndexes();
    const position = indexes.indexOf(getActiveHighlightIndex());
    updateButtons({
      previousDisabled: !indexes.length || position <= 0,
      nextDisabled: !indexes.length || position === indexes.length - 1,
    });
  }

  function activate(highlightIndex) {
    const highlight = getHighlight(highlightIndex);
    if (!highlight) {
      return;
    }

    closeCompetingPopovers();
    selectHighlight(highlightIndex);
    const sourceNodes = getSourceNodes(highlightIndex);
    const sourceRect = highlight.navigation_available
      ? combinedClientRect(sourceNodes)
      : null;

    if (!sourceRect) {
      hideHighlightPopover();
      flashUnavailableHighlight(highlightIndex);
      notifySourceUnavailable();
      syncButtons();
      return;
    }

    centerSource(sourceRect);
    openHighlightPopover(highlightIndex, combinedClientRect(sourceNodes));
    syncButtons();
  }

  function step(delta) {
    const indexes = getVisibleHighlightIndexes();
    if (!indexes.length) {
      return;
    }
    const position = indexes.indexOf(getActiveHighlightIndex());
    const nextPosition = position < 0
      ? (delta > 0 ? 0 : indexes.length - 1)
      : Math.max(0, Math.min(indexes.length - 1, position + delta));
    activate(indexes[nextPosition]);
  }

  function closePopover() {
    hideHighlightPopover();
  }

  return { activate, step, syncButtons, closePopover };
}
