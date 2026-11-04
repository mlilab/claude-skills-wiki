"""Render explicit research-parent edges as an SVG diagram. Caller validates cycles."""

from labels import text
from views import esc
import unicodedata


def short_label(value, limit=29):
    width = 0
    for i, char in enumerate(value):
        width += 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
        if width > limit:
            return value[:i] + "…"
    return value


def diagram(rows, language="en"):
    index = {record["id"]: record for _, record in rows}
    if not index:
        return "<p>" + esc(text("unrecorded", language)) + "</p>"
    children = {identifier: [] for identifier in index}
    roots = []
    for identifier, record in index.items():
        parent = record.get("parent")
        if parent in index:
            children[parent].append(identifier)
        else:
            roots.append(identifier)
    order = lambda identifier: int(identifier.split("-", 1)[0])
    positions, leaf = {}, 0
    def place(identifier, depth):
        nonlocal leaf
        kids = sorted(children[identifier], key=order)
        if kids:
            for kid in kids:
                place(kid, depth + 1)
            x = sum(positions[kid][0] for kid in kids) / len(kids)
        else:
            x = leaf * 300 + 150
            leaf += 1
        positions[identifier] = (x, depth * 150 + 65)
    for identifier in sorted(roots, key=order):
        place(identifier, 0)
    width = max(300, leaf * 300)
    height = max(y for _, y in positions.values()) + 65
    parts = [f'<div class="scroll"><svg xmlns="http://www.w3.org/2000/svg" class="lineage-graph" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{esc(text("lineage", language))}">']
    parts.append('<defs><marker id="lineage-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8" fill="#8b9fb9"/></marker></defs>')
    for child, record in index.items():
        parent = record.get("parent")
        if parent not in index:
            continue
        x1, y1 = positions[parent]
        x2, y2 = positions[child]
        middle = (y1 + y2) / 2
        parts.append(f'<path class="lineage-edge" data-parent="{esc(parent)}" data-child="{esc(child)}" marker-end="url(#lineage-arrow)" d="M{x1},{y1 + 40} V{middle} H{x2} V{y2 - 40}"/>')
    for identifier, record in index.items():
        x, y = positions[identifier]
        status = record["status"]
        title = record["title"]
        parts.append(f'<a href="reports/{esc(identifier)}/analysis.html"><g data-node="{esc(identifier)}" transform="translate({x - 130},{y - 40})">'
                     f'<title>{esc(identifier + ": " + title)}</title><rect data-node-status="{esc(identifier)}" class="graph-node {esc(status)}" width="260" height="80" rx="8"/>'
                     f'<text class="graph-id" x="14" y="23">{esc(short_label(identifier))}</text><text class="graph-title" x="14" y="45">{esc(short_label(title))}</text>'
                     f'<text data-status="{esc(identifier)}" class="badge {esc(status)}" x="14" y="65">{esc(text(status, language))}</text></g></a>')
    return "".join(parts) + "</svg></div>"
