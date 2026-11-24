---
name: paper-figure
description: Plan a high-quality paper figure (teaser, concept figure, method overview, small companion diagram) with the user and write a detailed image-generation prompt for it. The prompt fixes the story, layout, hex palette, typography, exact example values and what to avoid, so an image model (ChatGPT image generation, Gemini Nano Banana) produces a polished draft that the user then rebuilds in PowerPoint. Use when the user wants a figure that looks designed, or is unsure about colors, layout or how to show an idea.
---

# Paper figure prompt

This skill helps a researcher make a figure that looks designed rather than drawn in a hurry. It is most useful for the figure people remember: the first-page teaser, the main concept figure, the method overview. The work happens in three steps.

1. Discuss the figure with the user and write a detailed image prompt (this skill).
2. The user gives the prompt to an image model (ChatGPT or Gemini image generation) and gets a high-quality draft.
3. The user rebuilds the draft by hand in visualization tools (e.g., PowerPoint), keeping its layout, colors and type but with exact text, math and values. A figure generated end to end, or built by an agent in a design tool, still looks machine-made; the hand rebuild is what removes that.

Your job is step 1, and a short handoff for steps 2 and 3. Talk with the user in their language. Write the final prompt in English.

## What to collect

Take whatever the user gives: a paragraph about the idea, the method section, notes, a rough sketch, a previous figure, or the whole paper. Read all of it before proposing anything. Then make sure you know:

- Which figure this is and where it goes: teaser on page 1, method overview, a detail figure, or a small companion to an existing figure. The venue, single or double column, and the width it will occupy.
- The one sentence the figure must say. If the reader looks for five seconds, what should they remember?
- The mechanism in concrete terms: inputs, outputs, the steps, what is cheap and what is expensive, what is selected and why. Fixed terms the paper uses, written exactly.
- What must be visible, and what the user explicitly wants (a metaphor, a comparison, an asymmetry, a failure case).
- The rest of the paper's figures: if a palette or style already exists, the new figure follows it.
- A sketch or draft from the user, if any. Then the prompt keeps its structure and points and designs everything else.

Ask only for what you cannot infer. One round of questions is usually enough.

## Discuss before writing

Do not go straight to the prompt. Propose, get a reaction, then write.

1. The story. State the figure's message in one or two sentences and the reading order you intend (problem, failure, idea, result; or step, decision, outcome). For a method figure, say which part is the protagonist and which parts are context.
2. Two or three layout options. Sketch each in a few lines of ASCII or plain text: the bands or zones, their rough proportions, where the eye starts and ends, and which visual device carries the idea (a detail callout that zooms into one step, a timeline ribbon, a left-to-right narrative, a 2-axis plot, a before/after pair). Recommend one and say why.
3. The worked example. Most strong method figures show one concrete instance: real tokens, real numbers, a real image. Propose it and check that every value satisfies the paper's definitions (counts, sums, ranks, normalizations). A figure whose numbers do not add up is worse than a figure without numbers.
4. Color. Choose the palette with the user in three short rounds.
   - Recommend 4 to 5 palettes from `references/palettes.md` that suit the paper and the figure (a calm, editorial set for a method overview; a warmer or bolder set for a teaser; the existing palette if the paper's other figures already have one). For each, give its id, the hex values and one line on why it fits. Keep at least two of them clearly different in mood so the user has a real choice.
   - Show them as a figure, not as hex codes. Write a small HTML page that draws each candidate on a pure white page: the swatches with their hex values, three concept cards with light tinted fills and colored borders, one arrow, one highlighted element and a row of cells, with body text in neutral dark gray. Share the file (or publish it as a page if the session can). Include any palette the user brings.
   - When the user picks one, list the roles this figure needs (each recurring concept such as a model, a path, a branch; the hero or accent; accepted and rejected or success and failure, if they appear; any secondary marker) and ask which color goes to which role. Propose a mapping first so the user only has to correct it. Then derive the rest: light fills and highlight tints of each role color (about 85 to 92% toward white), a darker shade where a light color must carry text or a thin line, and the neutrals.
   Give each concept one hue and keep it everywhere. The background is pure white; tints appear only where they mark a concept, and the darkest palette color is not used for body text, which stays neutral dark gray.
5. Constraints. List what the image model is likely to get wrong for this method: two alternatives drawn as a sequence, a sub-step drawn as an equal step, a count that must differ between rows, a check that must not appear in some panel. These become explicit lines in the prompt.

When the user agrees on the story, layout, example and the color roles, write the prompt.

## The prompt

Follow this structure. Section headers are written as `=== NAME ===`. Fill every section with specifics for this paper; nothing generic should survive.

Opening paragraph. One sentence on what to create: figure type and number if known, venue and year, the paper's topic and method name. Then one or two sentences on the target feel, named with two or three concrete references ("must read like an editorial illustration from Quanta Magazine or Distill.pub, not a generic flowchart"; "a technical schematic, not a teaser illustration"). End with the requirement that every design choice feels intentional. Then state the canvas rule in so many words: the image contains only the figure, on a pure white background; the only text drawn is the list under TEXT ON THE CANVAS; the palette, hex codes, font names, sizes, section names and the instructions themselves are never drawn (no legend, swatch sheet or style-guide sidebar).

`=== WHAT THE METHOD DOES ===` or `=== CONCEPT ===`. The story in plain prose, with the paper's fixed terms in the paper's capitalization. Then the worked example with exact values, step by step, including what changes on the canvas after each step. State what does not happen as clearly as what does.

`=== OVERALL COMPOSITION ===` (or `OVERALL VISUAL STRATEGY`). Aspect ratio, physical width (for example "full text width of a two-column paper, about 7 in"), and the bands or zones with their share of height or width. Name the main visual device. Add a `CRITICAL CONCEPTUAL CONSTRAINTS` block when the method has relations the model could misdraw.

Panel-by-panel specification (`=== PANEL-BY-PANEL SPECIFICATION ===` or per-band paragraphs). For each panel: position and size, header text, caption text, what sits inside from left to right or top to bottom, exact cell contents, arrow colors and labels, and which element carries the highlight. Every arrow starts on the element that moves or sends and ends where it goes; say so when an arrow could be read as a link between two elements.

`=== TEXT ON THE CANVAS ===`. Every string the figure shows, grouped by panel, each in double quotes, and nothing else. End with "No other text appears in the image." If the prompt names elements only to place them (code A, point B), say here that those names are not drawn.

`=== STYLE REFERENCES ===`. Four to seven references from different fields so no single cliché dominates: editorial illustration (Quanta Magazine, The New Yorker science section), explanatory diagrams (Distill.pub, Google DeepMind or Anthropic research blogs), product graphics (Apple keynote diagrams, Linear), information design (Edward Tufte), minimalism (Kenya Hara). Say which one dominates.

`=== COLOR PALETTE ===`. Start the section with "Apply these colors; do not display them." Then write each color as an instruction that puts it on an element ("Draw every reconstruction-loss arrow in #0D6B73", "Fill the accepted-token cells with #DDF0E4"), never as a "name: value" list. Hex-exact and semantic: for each concept a primary color and, where needed, mid, fill and highlight tints; accent colors with the exact places they may appear. The canvas is pure white #FFFFFF. Panel and card fills only where needed, in a neutral or cool light gray such as #F6F7F9; hairlines and dashed borders in a neutral gray such as #DDE2E7; body text dark but not pure black; a muted gray for annotations. Never give the background a cream, beige, ivory, sand, parchment or warm off-white tone: image models drift toward it, and it looks stained on a white paper page. This is about the background only; light tints of a concept's own color, warm ones included, are fine for fills. Say where gradients are allowed, usually nowhere or in one place with a meaning.

`=== TYPOGRAPHY ===`. Start the section with "Apply these type settings; do not display font names or sizes." and keep the rest as instructions. Two typefaces plus a mono: a sans for labels and titles (for example Inter, Figtree, ABC Diatype), the same or a second face for captions, a mono for numbers and indices (JetBrains Mono, IBM Plex Mono), and italic math for variables. Then a size hierarchy: header tabs, labels, captions, cell text, numerals, with point sizes and case. Minimum size at print. Fixed terms keep their capitalization.

`=== COMPOSITIONAL DETAILS ===` and `=== MICRO-DETAILS ===`. Container style (corner radius scale, border weight and color, one shadow style used everywhere), cell sizes and gaps, arrow weights, heads and colors, marker and pill sizes, icon design (custom, with one small asymmetric detail; never stock icons or faces), alignment rules (shared x-positions across bands so rows can be compared), and which element carries the strongest visual weight.

`=== NARRATIVE READING ORDER ===`. Numbered, one line per stop, saying what the reader takes in at that point, without quotation marks. End with "This order must be evident from layout and arrows alone; none of these sentences appear in the image."

`=== AVOID ABSOLUTELY ===`. One line per item, specific to this figure first (the misreadings from the discussion, wrong colors for this palette, labels that must not appear), then the usual ones: a color-palette legend, swatches, hex codes, font names or any other spec text drawn in the image; any sidebar, legend or panel beyond the requested ones; a cream, beige, ivory or other warm-tinted background, paper texture or vignette; checkmarks, checkboxes, toggles or other UI widgets unless the figure needs them; flowchart decision diamonds, robots or mascots, cartoon proportions, clip-art or stock icons, rainbow or unmotivated gradients, 3D or photorealism, heavy shadows, pure black text, crowded text.

`=== OUTPUT ===`. Resolution (at least 4800 to 5400 px wide for a full-width figure, about 3000 px for a small one), a pure white #FFFFFF canvas that the requested panels fill edge to edge with nothing beside them, vector-quality edges, SVG or PDF preferred, and "ready to trace over in a vector editor".

For a small companion figure, or when the user attaches a draft, the prompt is shorter: name the figure it must match and repeat that palette, list what the draft shows and must be kept, state the story in two or three sentences, then design, typography, composition, avoid and output in a few lines each.

## Writing the prompt

Separate drawn text from instructions. Image models draw text they find in the prompt, so double quotes mark text that appears on the canvas and nothing else: never quote style words, reader thoughts or section names, and never write the palette or type settings as a spec sheet.
Be exact. Hex values, point sizes, pixel radii, opacities, aspect ratio, percentages of width and height. Exact strings for every label, in quotes.
Be semantic. Every color, weight and glow has a meaning, and the prompt says what it marks.
Repeat the hero. The element that carries the idea (the winning trajectory, the accepted tokens, the new axis) gets one accent that appears in two or three linked places and nowhere else.
Keep the math true. Recompute every number in the worked example from the paper's formula before writing it down, and write the formula in the prompt when the figure shows it.
Use the paper's terms only. If the paper says "FULL forward", the figure never says "full pass".
Leave room. Prefer fewer labels with more space; say so in the prompt.
Write it as instructions to a designer, in plain imperative sentences. The prompt is long by design (a full-width figure usually needs 1,000 to 2,500 words); a short prompt gives a generic picture.

## After the prompt

Give the prompt in one code block so it can be copied. Then add a short handoff in the user's language:

- Run it on two image models (ChatGPT image generation and Gemini Nano Banana) and a few times each; pick the draft with the best layout and color, not the best text. Image models misspell labels and break math, which is fine because the text is redone by hand.
- If a draft gets the structure wrong, fix the prompt (usually a constraint line or the panel spec) rather than asking for edits in chat.
- Rebuild in PowerPoint: place the draft on a locked bottom layer at about 50% transparency, set the slide to the figure's aspect ratio, enter the palette as theme colors, and redraw shapes, arrows and cells on top with the exact hex values and fonts. Retype every label and insert math as equations. Delete the draft layer and export as PDF.
- Keep the PowerPoint file; the same palette and type settings make the paper's other figures match.

If the user comes back with a draft image, compare it with the prompt and say what to keep, what to fix in the rebuild, and whether a prompt change would be faster. If the draft shows spec text (hex codes, font names, a palette sidebar) or internal names used only for placement, do not ask for fixes in chat: first check the prompt against the rules above, in particular the quotes, TEXT ON THE CANVAS, and the instruction form of the palette and typography sections, and rewrite those parts.
