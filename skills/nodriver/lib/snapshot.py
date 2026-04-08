"""
snapshot.py — DOM walker that gives the model a "view" of the current page.

It does two things in one shot:
  1. Find every interactive element (links, buttons, inputs, role-based
     widgets, contenteditable, [onclick]) and assign each a sequential
     ref id (`r1`, `r2`, ...).
  2. MUTATE the DOM by writing `data-nd-ref="rN"` onto each element. This
     gives us a stable CSS selector (`[data-nd-ref="r17"]`) that survives
     re-querying within the same page lifetime.

The caller (scripts/snapshot.py) writes `{ref: selector}` to refs.json so
click.py / type.py / press.py can resolve a ref into a selector later.

Refs are page-scoped: a navigation or significant SPA re-render invalidates
them. The script is cheap to re-run.
"""

from __future__ import annotations

import json

# JS payload. Kept as a single expression so JSON.stringify can wrap the
# whole thing for the js() helper in runner.py.
SNAPSHOT_JS = r"""
(() => {
  const SEL = [
    'a[href]',
    'button',
    'input:not([type="hidden"])',
    'select',
    'textarea',
    '[role="button"]',
    '[role="link"]',
    '[role="textbox"]',
    '[role="combobox"]',
    '[role="checkbox"]',
    '[role="radio"]',
    '[role="menuitem"]',
    '[role="tab"]',
    '[contenteditable="true"]',
    '[onclick]',
  ].join(', ');

  const isVisible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none' || cs.opacity === '0') return false;
    return true;
  };

  const cleanText = (s) => (s || '').replace(/\s+/g, ' ').trim().slice(0, 100);

  const nameOf = (el) => {
    return cleanText(
      el.getAttribute('aria-label') ||
      el.getAttribute('alt') ||
      el.innerText ||
      el.value ||
      el.placeholder ||
      el.getAttribute('title') ||
      el.getAttribute('name') ||
      ''
    );
  };

  // Walk and collect. Skip elements that already have a ref from a previous
  // snapshot — keep the older id stable so click/type calls referencing the
  // earlier snapshot still work as long as the element survived.
  const all = Array.from(document.querySelectorAll(SEL));
  let nextId = 1;
  // Find the highest existing ref so we don't collide.
  for (const el of all) {
    const existing = el.dataset && el.dataset.ndRef;
    if (existing && /^r(\d+)$/.test(existing)) {
      const n = parseInt(existing.slice(1), 10);
      if (n >= nextId) nextId = n + 1;
    }
  }

  const refs = [];
  for (const el of all) {
    let refId = el.dataset.ndRef;
    if (!refId) {
      refId = 'r' + (nextId++);
      el.dataset.ndRef = refId;
    }
    const r = el.getBoundingClientRect();
    refs.push({
      ref: refId,
      tag: el.tagName.toLowerCase(),
      type: el.type || null,
      role: el.getAttribute('role') || null,
      name: nameOf(el),
      href: el.tagName === 'A' ? (el.href || null) : null,
      value: ('value' in el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT'))
        ? (el.value || null) : null,
      visible: isVisible(el),
      bbox: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
    });
  }

  return {
    url: location.href,
    title: document.title,
    text: (document.body && document.body.innerText || '').slice(0, 8000),
    refs: refs,
  };
})()
"""


async def take_snapshot(tab) -> dict:
    """
    Run the snapshot JS in `tab`, return the parsed dict.

    Returns: {url, title, text, refs: [{ref, tag, type, role, name, href, value, visible, bbox}]}
    """
    raw = await tab.evaluate(f"JSON.stringify({SNAPSHOT_JS})")
    if raw is None:
        return {"url": None, "title": None, "text": "", "refs": []}
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


def selector_for(ref: str) -> str:
    """The CSS selector that resolves a ref id back to its element."""
    return f'[data-nd-ref="{ref}"]'


def build_selector_map(snapshot: dict) -> dict[str, str]:
    """{r1: '[data-nd-ref="r1"]', ...} — what gets written to refs.json."""
    return {r["ref"]: selector_for(r["ref"]) for r in snapshot.get("refs", [])}
