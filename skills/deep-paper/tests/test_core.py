"""Offline tests: HTML parsing, check helpers, Notion conversion, HTML rendering helpers."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import check  # noqa: E402
import fetch  # noqa: E402
import notion_md  # noqa: E402
import render  # noqa: E402
from common import parse_arxiv_id  # noqa: E402

HTML = """<html><body><article class="ltx_document">
<h1 class="ltx_title ltx_title_document">A Test Paper</h1>
<div class="ltx_abstract"><p class="ltx_p">We test things.</p></div>
<section id="S1" class="ltx_section"><h2 class="ltx_title ltx_title_section">1  Introduction</h2>
<div id="S1.p1" class="ltx_para"><p class="ltx_p">Prior work <cite class="ltx_cite">(<a href="#bib.bib1" class="ltx_ref">Smith, 2024</a>)</cite>
uses <math alttext="x_i^2" display="inline"><mi>x</mi></math>. See Figure 1.</p></div>
<figure id="S1.F1" class="ltx_figure"><object type="image/svg+xml" data="2601.00001v1/a.svg"></object>
<figcaption><span class="ltx_tag ltx_tag_figure">Figure 1: </span>An overview.</figcaption></figure>
<section id="S1.SS1" class="ltx_subsection"><h3 class="ltx_title"><span class="ltx_tag ltx_tag_subsection">1.1 </span>Setup</h3>
<div class="ltx_para"><p class="ltx_p">Details.</p>
<ul><li><div class="ltx_para"><p class="ltx_p">Nested item.</p></div></li></ul></div>
<div class="ltx_paragraph"><h4 class="ltx_title">Problem Setup.</h4><div class="ltx_para"><p class="ltx_p">Para.</p></div>
<figure id="S1.F3" class="ltx_figure"><img src="2601.00001v1/c.png"><figcaption><span class="ltx_tag ltx_tag_figure">Figure 3: </span>In a paragraph.</figcaption></figure>
</div></section>
</section>
<section id="A1" class="ltx_appendix"><h2 class="ltx_title">Appendix A  Proofs</h2>
<div class="ltx_para"><p class="ltx_p">Proof text.</p></div>
<figure id="A1.F2" class="ltx_figure"><img src="2601.00001v1/b.png">
<figcaption><span class="ltx_tag ltx_tag_figure">Figure 2: </span>Appendix plot.</figcaption></figure></section>
<section class="ltx_bibliography"><ul>
<li id="bib.bib1" class="ltx_bibitem"><span class="ltx_tag ltx_tag_bibitem">Smith (2024)</span>
<span class="ltx_bibblock">J. Smith.</span><span class="ltx_bibblock"><span class="ltx_bib_title">A method</span>.</span>
<span class="ltx_bibblock">arXiv preprint arXiv:2401.12345.</span></li></ul></section>
</article></body></html>"""


class ParseTest(unittest.TestCase):
    def setUp(self):
        self.p = fetch.parse_html(HTML, "https://arxiv.org/html/2601.00001v1")

    def test_sections_and_numbers(self):
        secs = [(s["number"], s["title"], s["level"], s["in_appendix"]) for s in self.p["sections"]]
        self.assertIn(("1", "Introduction", 1, False), secs)
        self.assertIn(("1.1", "Setup", 2, False), secs)
        self.assertIn(("A", "Proofs", 1, True), secs)

    def test_paragraph_text(self):
        intro = next(s for s in self.p["sections"] if s["number"] == "1")
        txt = intro["paragraphs"][0]["text"]
        self.assertIn("[@bib.bib1 Smith (2024)]", txt)
        self.assertIn("$x_i^2$", txt)
        self.assertEqual(intro["paragraphs"][0]["mentions"], ["1"])
        self.assertEqual(len(intro["paragraphs"]), 1)  # the subsection paragraph is not counted here

    def test_unnumbered_paragraphs(self):
        ps = next(s for s in self.p["sections"] if s["title"] == "Problem Setup")
        self.assertEqual((ps["number"], ps["parent"], ps["level"]), ("", "1.1", 4))
        setup = next(s for s in self.p["sections"] if s["number"] == "1.1")
        self.assertEqual(len(setup["paragraphs"]), 1)  # the nested list item is part of it
        f3 = next(f for f in self.p["figures"] if f["number"] == "3")
        self.assertEqual((f3["section"], f3["top_section"]), ("1.1", "1"))

    def test_figures(self):
        f1, f2 = [f for f in self.p["figures"] if f["number"] in ("1", "2")]
        self.assertEqual((f1["number"], f1["top_section"], f1["in_appendix"]), ("1", "1", False))
        self.assertIn("https://arxiv.org/html/2601.00001v1/a.svg", f1["image_urls"][0])
        self.assertTrue(f2["in_appendix"])
        self.assertEqual(f1["caption"], "An overview.")

    def test_refs(self):
        r = self.p["refs"]["bib.bib1"]
        self.assertEqual(r["arxiv_id"], "2401.12345")
        self.assertEqual(r["url"], "https://arxiv.org/abs/2401.12345")
        self.assertIn("1", r["cited_in"])


class CheckTest(unittest.TestCase):
    def test_blocks(self):
        body = "## 1 Intro\n\nOne. Two.\n\n- a\n- b\n\n| x | y |\n|---|---|\n| 1 | 2 |\n\n> [!KEY] k\n> v\n\n![Figure 1: c](fig:1)\n"
        kinds = [b[0] for b in check.blocks(body)]
        self.assertEqual(kinds, ["heading", "prose", "list", "table", "callout", "image"])

    def test_sentences(self):
        self.assertEqual(check.sentences("이 방법은 빠르다. 그리고 정확하다. 또한 단순하다. 마지막으로 싸다."), 4)
        self.assertEqual(check.sentences("It works. It is fast."), 2)

    def test_front(self):
        front, body = check.split_front("---\ntldr: [a, b, c]\n---\n## 1 X\n")
        self.assertEqual(front["tldr"], ["a", "b", "c"])
        self.assertTrue(body.startswith("## 1 X"))


class NotionTest(unittest.TestCase):
    def test_convert(self):
        figs = {"1": {"number": "1", "image_urls": ["https://arxiv.org/html/x/a.png"], "files": []},
                "2": {"number": "2", "image_urls": [], "files": ["figures/fig_2_1.png"]}}
        up = []
        body = ("> [!RESULT] Big gain\n> +5 points\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n"
                "<details><summary>More</summary>\n\nhidden text\n\n</details>\n\n"
                "#### Para title\n\n![Figure 1: cap](fig:1)\n\n![two](fig:2)\n\n<u>key</u>")
        out = notion_md.convert_body(body, figs, up)
        self.assertIn('<callout icon="✅" color="green_bg">', out)
        self.assertIn('<table header-row="true">', out)
        self.assertIn("<summary>More</summary>", out)
        self.assertIn("\thidden text", out)
        self.assertIn("#### Para title", out)
        self.assertIn("![Figure 1: cap](https://arxiv.org/html/x/a.png)", out)
        self.assertIn("[[upload Figure 2]]", out)
        self.assertIn('<span underline="true">key</span>', out)
        self.assertEqual(up[0]["figure"], "2")

    def test_nested_list(self):
        out = notion_md.convert_body("- a\n  - b\n    - c\n1. x\n   - y", {}, [])
        self.assertIn("- a\n\t- b\n\t\t- c", out)
        self.assertIn("1. x\n\t- y", out)

    def test_inline(self):
        out = notion_md.notion_inline("Loss $a_i$ is small, a < b, ~5%. $$x^2$$ and `c<d`")
        self.assertIn("$`a_i`$", out)
        self.assertIn("a \\< b", out)
        self.assertIn("\\~5%", out)
        self.assertIn("\n$$\nx^2\n$$\n", out)
        self.assertIn("`c<d`", out)


class RenderTest(unittest.TestCase):
    def test_math_protected(self):
        h = render.body_html("## 1 Intro\n\nLoss $a_i * b_j$ and $$x_1_2$$ here.", {}, [{"number": "1", "title": "Intro", "page": 3}],
                             render.L10N["en"])
        self.assertIn("$a_i * b_j$", h)
        self.assertIn('data-page="3"', h)

    def test_callout(self):
        h = render.body_html("> [!LIMIT] Caveat\n> small scale", {}, [], render.L10N["en"])
        self.assertIn('class="callout limit"', h)


class IdTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_arxiv_id("https://arxiv.org/abs/2610.07018v2"), "2610.07018")
        self.assertEqual(parse_arxiv_id("arXiv:1706.03762"), "1706.03762")
        self.assertIsNone(parse_arxiv_id("Attention is all you need"))


if __name__ == "__main__":
    unittest.main()
