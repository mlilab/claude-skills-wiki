#!/usr/bin/env python3
"""Headless click-through of a built simulator page (playwright + Chrome/Chromium).

usage: python3 tests/ui_smoke.py <page.html> [--shots DIR]
Walks: open a paper, drag a dot, zoom, change hops, cluster layouts (edges kept), take a numbered move with a pasted
agent reply, fill a TODO result, make a custom move, go back along the trail, reload, phone width.
"""
import json
import os
import sys

from playwright.sync_api import sync_playwright

page_path = os.path.abspath(sys.argv[1])
shots = sys.argv[sys.argv.index("--shots") + 1] if "--shots" in sys.argv else None


def shot(pg, name, full=False):
    if shots:
        pg.screenshot(path=os.path.join(shots, name), full_page=full)


errors = []
with sync_playwright() as p:
    exe = "/usr/bin/google-chrome" if os.path.exists("/usr/bin/google-chrome") else None
    b = p.chromium.launch(executable_path=exe, args=["--no-sandbox"])
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    pg.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}")
          if m.type == "error" and "fonts" not in m.text and "ERR_" not in m.text else None)
    pg.goto("file://" + page_path)
    pg.wait_for_selector("#nodes .n .dot")
    pg.wait_for_timeout(1500)
    n_graph = pg.evaluate("__sim.graph().nodes.length")
    assert pg.locator("#nodes .n").count() == n_graph + 1, "dots != graph nodes + you"
    assert pg.locator("#edges line").count() == n_graph
    shot(pg, "1_start.png")

    # titles only until clicked; click -> details
    first = pg.evaluate("__sim.graph().nodes[0].id")
    assert pg.locator("#paper").is_hidden()
    pg.locator(f'#nodes .n[data-id="{first}"] .dot').click(force=True)
    assert pg.locator("#paper").is_visible() and "Relatedness" in pg.inner_text("#paper")
    shot(pg, "2_paper.png")
    pg.click('#paper [data-act="close"]')

    # drag a dot: it moves and stays pinned
    box = pg.locator(f'#nodes .n[data-id="{first}"] .dot').bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    pg.mouse.move(x, y); pg.mouse.down(); pg.mouse.move(x + 90, y + 60, steps=8); pg.mouse.up()
    pg.wait_for_timeout(1200)
    after = pg.locator(f'#nodes .n[data-id="{first}"] .dot').bounding_box()
    assert abs(after["x"] - box["x"] - 90) < 12 and abs(after["y"] - box["y"] - 60) < 12, (box, after)
    assert pg.evaluate(f"__sim.bodies()['{first}'].pin") is True

    # zoom
    t0 = pg.get_attribute("#world", "transform")
    pg.mouse.move(720, 450); pg.mouse.wheel(0, -400); pg.wait_for_timeout(100)
    assert pg.get_attribute("#world", "transform") != t0
    pg.click("#fit")

    # hops: + adds papers, typed value works
    pg.click("#hopup"); pg.wait_for_timeout(300)
    n3 = pg.evaluate("__sim.graph().nodes.length")
    assert n3 >= n_graph and pg.evaluate("__sim.graph().depth") >= 2
    pg.fill("#hops", "1"); pg.press("#hops", "Enter"); pg.locator("#hops").blur(); pg.wait_for_timeout(300)
    assert pg.evaluate("__sim.graph().depth") == 1
    pg.fill("#hops", "3"); pg.locator("#hops").blur(); pg.wait_for_timeout(1500)
    edges3 = pg.locator("#edges line").count()

    # cluster layouts keep every edge and gather clusters
    for f in ("problem", "method"):
        pg.click(f'[data-layout="{f}"]'); pg.wait_for_timeout(2600)
        assert pg.locator("#edges line").count() == edges3, "edges must be kept in cluster layouts"
        assert pg.locator("#cls text").count() >= 2
        spread = pg.evaluate("""() => { const C = __sim.clusters(), P = __sim.bodies(); let within = 0, n = 0, cent = {};
          C.groups.forEach(g => { const xs = g.members.map(i => P[i]); cent[g.id] = [xs.reduce((a,p)=>a+p.x,0)/xs.length, xs.reduce((a,p)=>a+p.y,0)/xs.length]; });
          C.groups.forEach(g => g.members.forEach(i => { within += Math.hypot(P[i].x - cent[g.id][0], P[i].y - cent[g.id][1]); n++; }));
          const cs = Object.values(cent); let between = 0, m = 0;
          for (let a = 0; a < cs.length; a++) for (let b = a + 1; b < cs.length; b++) { between += Math.hypot(cs[a][0]-cs[b][0], cs[a][1]-cs[b][1]); m++; }
          return [within / n, between / m]; }""")
        assert spread[0] < spread[1], f"{f} clusters not gathered: {spread}"
        shot(pg, f"3_cluster_{f}.png")
    pg.click('[data-layout="free"]'); pg.wait_for_timeout(1500)

    # numbered move -> manual agent round-trip
    assert pg.locator(".mv").count() >= 2
    label = pg.locator(".mv .lbl").first.inner_text()
    pg.keyboard.press("1")
    pg.wait_for_selector("#mprompt")
    assert "Reply with ONLY one JSON object" in pg.input_value("#mprompt")
    reply = {"research": {"status": [{"kind": "done", "text": "earlier result", "result": "0.81"},
                                     {"kind": "todo", "text": "Run the new experiment (AUC)"}]},
             "options": [{"label": "Next A", "kind": "data", "why": "w",
                          "projected": {"problem_tags": ["streaming-data"], "method_tags": ["k-means"], "todo": ["Measure A"]}},
                         {"label": "Next B", "kind": "method", "why": "w", "projected": {"method_tags": ["prompt-tuning"]}}],
             "add_papers": [{"title": "A suggested paper", "problem_tags": ["streaming-data"], "method_tags": ["k-means"], "why": "w"}],
             "notes": "n"}
    pg.fill("#mreply", "```json\n" + json.dumps(reply) + "\n```")
    pg.click('[data-act="applymanual"]')
    pg.wait_for_timeout(1500)
    assert pg.locator("#trail button").count() == 2
    assert label in pg.inner_text("#you")
    assert [t.strip() for t in pg.locator(".mv .lbl").all_inner_texts()] == ["Next A", "Next B"]
    assert pg.locator("#you .status .todo").count() == 1
    shot(pg, "4_after_move.png")

    # fill a TODO blank
    pg.fill("#you .blank input", "AUC 0.83"); pg.locator("#you .blank input").blur()
    assert pg.evaluate("__sim.state().nodes.find(n => n.id === __sim.state().current).research.status[1].result") == "AUC 0.83"

    # custom move
    pg.fill("#custom", "Use a learned latent context instead of rows")
    pg.press("#custom", "Enter")
    pg.wait_for_selector("#mreply")
    assert "Use a learned latent context instead of rows" in pg.input_value("#mprompt")
    pg.fill("#mreply", json.dumps({"research": {"problem": "p2", "method": "Learned latent context rows trained by gradient descent",
                                                "method_tags": ["prompt-tuning", "fine-tuning"],
                                                "status": [{"kind": "todo", "text": "Train latent rows (AUC)"}]},
                                   "options": [{"label": "C", "projected": {}}]}))
    pg.click('[data-act="applymanual"]'); pg.wait_for_timeout(1200)
    st = pg.evaluate("__sim.state().nodes.find(n => n.id === __sim.state().current)")
    assert st["move"]["custom"] and st["research"]["method_tags"] == ["prompt-tuning", "fine-tuning"]
    assert pg.locator("#trail button").count() == 3

    # back along the trail, reload restores progress
    pg.locator("#trail button").first.click()
    assert pg.evaluate("__sim.state().current") == "s0"
    pg.reload(); pg.wait_for_selector("#nodes .n .dot")
    assert len(pg.evaluate("__sim.state().nodes")) == 3

    # import plain text -> agent import prompt
    pg.click("#io"); pg.fill("#imp", "We now compress TabPFN contexts with coresets."); pg.click('[data-act="import"]')
    pg.wait_for_selector("#mprompt")
    assert "We now compress TabPFN contexts with coresets." in pg.input_value("#mprompt")
    pg.click('.ov [data-act="close"]')

    # phone width
    pg.set_viewport_size({"width": 400, "height": 860}); pg.wait_for_timeout(400)
    sw = pg.evaluate("document.documentElement.scrollWidth")
    assert sw <= 400, f"horizontal overflow at phone width: {sw}px"
    shot(pg, "5_phone.png", full=True)
    b.close()

if errors:
    print("\n".join(errors))
    sys.exit(1)
print("ui smoke: ok")
