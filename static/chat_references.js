const PAGE_REFERENCE_PATTERN = /\b(?:p(?:g|age)?|pages?)\.?\s*(\d{1,4})\b/gi;
const SKIP_REFERENCE_TAGS = new Set(["A", "BUTTON", "CODE", "PRE", "SCRIPT", "STYLE", "TEXTAREA"]);

function validPageNumber(rawPageNumber, pageCount = 0) {
  const pageNumber = Number.parseInt(rawPageNumber, 10);
  const maxPageNumber = Number(pageCount) || 0;
  if (!Number.isInteger(pageNumber) || pageNumber < 1) {
    return null;
  }
  if (maxPageNumber && pageNumber > maxPageNumber) {
    return null;
  }
  return pageNumber;
}

export function chatPageReferenceSegments(value, pageCount = 0) {
  const text = String(value || "");
  const segments = [];
  let cursor = 0;

  for (const match of text.matchAll(PAGE_REFERENCE_PATTERN)) {
    const pageNumber = validPageNumber(match[1], pageCount);
    if (!pageNumber) {
      continue;
    }

    if (match.index > cursor) {
      segments.push({ text: text.slice(cursor, match.index) });
    }
    segments.push({ text: match[0], pageNumber });
    cursor = match.index + match[0].length;
  }

  if (!segments.length) {
    return [{ text }];
  }
  if (cursor < text.length) {
    segments.push({ text: text.slice(cursor) });
  }
  return segments;
}

function shouldSkipTextNode(node) {
  const parent = node.parentElement;
  return !parent || Boolean(parent.closest(Array.from(SKIP_REFERENCE_TAGS).join(",")));
}

function pageReferenceButton(documentRef, segment) {
  const button = documentRef.createElement("button");
  button.className = "chat-page-reference";
  button.type = "button";
  button.dataset.chatPageReference = String(segment.pageNumber);
  button.textContent = segment.text;
  button.title = `Jump to page ${segment.pageNumber}`;
  button.setAttribute("aria-label", `Jump to page ${segment.pageNumber}`);
  return button;
}

export function linkifyChatPageReferences(root, options = {}) {
  if (!root) {
    return 0;
  }

  const documentRef = root.ownerDocument || globalThis.document;
  if (!documentRef) {
    return 0;
  }

  const textNodes = [];
  const showText = documentRef.defaultView?.NodeFilter?.SHOW_TEXT || globalThis.NodeFilter?.SHOW_TEXT || 4;
  const walker = documentRef.createTreeWalker(root, showText);
  while (walker.nextNode()) {
    if (!shouldSkipTextNode(walker.currentNode)) {
      textNodes.push(walker.currentNode);
    }
  }

  let referenceCount = 0;
  for (const node of textNodes) {
    const segments = chatPageReferenceSegments(node.nodeValue || "", options.pageCount || 0);
    if (!segments.some((segment) => segment.pageNumber)) {
      continue;
    }

    const fragment = documentRef.createDocumentFragment();
    for (const segment of segments) {
      if (segment.pageNumber) {
        fragment.appendChild(pageReferenceButton(documentRef, segment));
        referenceCount += 1;
      } else if (segment.text) {
        fragment.appendChild(documentRef.createTextNode(segment.text));
      }
    }
    node.replaceWith(fragment);
  }

  return referenceCount;
}
