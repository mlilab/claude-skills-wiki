# Paper Figure

Paper Figure is a Claude Code skill for the figures people remember: a first-page teaser, a main concept figure, a method overview. It works out with you how to show the idea, then writes a long, exact image-generation prompt. An image model turns that prompt into a polished draft, and you rebuild the draft in PowerPoint so the final figure has exact text and math and does not look machine-made.

## How it works

1. You give Claude whatever you have: a description of the idea, the method section, notes, a sketch, an earlier figure, or the whole paper.
2. Claude proposes the figure's one-sentence message, two or three layouts as text sketches and a worked example whose numbers match the paper. For color, it recommends 4 to 5 popular palettes, shows each as a small figure on a preview page, and after you pick one asks which color should mark which concept. You pick and adjust.
3. Claude writes the prompt: story, composition, panel-by-panel content with exact labels, style references, hex palette, typography, micro-details, reading order, a list of things to avoid, and output settings.
4. You run the prompt in ChatGPT image generation or Gemini Nano Banana, a few times each, and pick the best draft.
5. You rebuild the draft in PowerPoint on top of a transparent copy of it, with the exact colors, fonts, labels and equations, and export a PDF.

## What it does

| Feature | What you get |
| --- | --- |
| Discussion first | The message, layout options, worked example and palette are agreed before any prompt is written. |
| Exact prompts | Hex colors with their roles, point sizes, radii, aspect ratio, and every label as an exact string. |
| Faithful content | The paper's fixed terms only, and example values recomputed from the paper's formulas. |
| Palette choice | A library of popular color combinations, a preview page that shows each candidate as a small figure on white, and a role-by-role color assignment you confirm. |
| Clean canvas | Only the listed labels are drawn, on a pure white background. The palette, fonts and instructions are written so the image model applies them instead of drawing them as a legend or sidebar. |
| Misreading guards | Explicit constraints for what an image model tends to get wrong for your method (alternatives drawn as a sequence, counts that must differ, arrows that must start on the element that moves). |
| Small figures too | A short prompt for a companion diagram that must match an existing figure, or that keeps the structure of your own sketch. |
| Rebuild guide | How to recreate the draft in PowerPoint and keep the palette for the paper's other figures. |

## Install

```bash
git clone https://github.com/mlilab/claude-skills-wiki.git "$HOME/claude-skills-wiki"
mkdir -p "$HOME/.claude/skills"
ln -s "$HOME/claude-skills-wiki/skills/paper-figure" "$HOME/.claude/skills/paper-figure"
```

No other dependencies. Image generation happens in ChatGPT or Gemini, outside Claude Code.

## Use

| Ask | Result |
| --- | --- |
| "Let's design the teaser figure for this paper (PDF attached)" | Layout options and a palette to choose from, then the full prompt |
| "Make a method overview figure for Section 3" | A worked example checked against the paper, then the prompt |
| "Here is my sketch of the plot, make it look designed and match Figure 1" | A short prompt that keeps your structure and Figure 1's palette |
| "This is the draft I got from Nano Banana" | What to keep, what to fix in the rebuild, or a prompt change |

## References

- Palette library based on popular combinations on [coolors.co](https://coolors.co/palettes/popular).
