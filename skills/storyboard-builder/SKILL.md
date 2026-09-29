---
name: storyboard-builder
description: >
  Turn a character reference sheet and a one-line scene description into a complete
  multi-panel storyboard image prompt, ready to paste into an image generator and then
  feed to a video model. Use whenever someone asks for a storyboard, a storyboard sheet,
  a panel breakdown, a shot sheet, or says "storyboard this scene". Works for any visual
  style: cel anime, 3D cartoon, photoreal cinematic, toy brick, stop-motion, comic, or
  anything else. Also accepts an existing storyboard or a locked-storyboard grid-input.json
  handoff: preserve its original shots, durations and frame descriptions. Reference images
  are optional; existing storyboard text alone is sufficient for a complete grid-image prompt.
---

# Storyboard Builder

## Select the input mode first

- **Idea mode:** only a scene idea / character sheet is supplied. Follow the original workflow below.
- **Locked storyboard mode:** an existing storyboard or a `grid-input.json` handoff is supplied; reference images are optional. Follow [references/locked-storyboard.md](references/locked-storyboard.md) and use [references/locked-grid-template.txt](references/locked-grid-template.txt).

**Locked storyboard constraints override the free-creation defaults below:** do not force 15 panels, equal-duration panels, alternating shot sizes, new escalation, or a new 16:9 crop. Never rewrite the supplied shot order or generate replacement standalone keyframes. Deliver one complete grid-image prompt grounded in the existing frame descriptions and any optional references. Do not require pre-generated images or a video prompt.

The original user-supplied skill is preserved in [references/original-storyboard-skill.md](references/original-storyboard-skill.md).

## Original workflow — idea mode

You write ONE thing: a single image prompt that produces a complete multi-panel storyboard
sheet. That sheet is then fed to a video model, which reads it and animates the whole
sequence in one generation.

## What you need from the user

1. **A character reference sheet** (an uploaded image). Optional but strongly preferred.
   If they have not attached one, ask once, then proceed from text.
2. **A scene description** in plain English. One line is enough: who, where, what happens.
3. **A duration.** Default 30 seconds. Ask if unclear.

Do not ask for anything else. Do not ask them to approve a beat sheet first. Write the prompt.

## Panel count

**Default: 15 panels at 2 seconds each = 30 seconds.**

| Duration | Panels | Grid |
|---|---|---|
| 15s | 15 | 5 across x 3 down |
| 30s | 15 | 5 across x 3 down |
| 60s | 30 | 6 across x 5 down |

Derive the count from the duration. Never default it downward: a denser sheet carries more
of the story in one generation, which is the whole point.

## The five rules that decide whether this works

These are not style preferences. Each one fixes a specific, repeatable failure.

### 1. Geometry first, style last
State what the image IS, then the grid row by row, then the panels, and only then the
visual style, subordinated as "INSIDE EACH PANEL". Close with an explicit render mandate.

**If you put style first**, the model produces one large cinematic frame instead of a
sheet. It obeys the loudest, most repeated instruction, and rich style language shouts
louder than a single line about a grid.

### 2. Nothing inside the panel images
The video model reproduces whatever sits inside a panel frame. A panel number burned into
the corner comes back burned into the finished video.

Panel numbers, timecodes and captions all go in the caption block BELOW each panel, on the
board, outside the image area. State this explicitly and forcefully in the prompt.

### 3. Captions carry a scene note, not just a shot size
Write `WIDE ESTABLISHING. Cottage in the valley, smoke from the chimney.` not `WIDE.`

Captions sit outside the frame, so the video model reads them but never draws them. That
makes a richer caption free story signal. Never shorten this to a shot size alone.

### 4. Write every timecode out explicitly
List each panel's timecode range in the prompt as a single instruction line. Without it,
panels collide on the same timecode and the pacing signal is corrupted.

### 5. Style is described by TECHNIQUE, plus hard negatives
Mood words fail. "Hand-painted", "painterly" and "muted earthy palette" produce a graphic
novel illustration when hand-drawn cel animation was wanted, because models have a strong
illustration prior and any ambiguity resolves toward it.

Technique words work: "completely flat colour fills", "no texture anywhere on the
character", "thin uniform ink outlines of even weight". Then add an explicit negative list
of what it must NOT look like.

**Never name a studio, film, toy brand or car marque.** Named-IP requests come back less
consistently and are often refused outright. Describe the traits instead: it is the better
prompt as well as the safer one.

## The prompt skeleton

Fill this in. Keep the structure exactly.

```
A single flat image of a printed film production storyboard sheet. This is a document, not
a movie frame. One presentation page divided into [N] small rectangular panels arranged in
a strict [C]x[R] grid: [R] rows down, [C] panels across each row. Every panel is identical
in size and evenly spaced, with clean gutters and a thin border.

Row 1 contains panels 1, 2, 3, 4 and 5 from left to right. Row 2 contains panels 6, 7, 8,
9 and 10. Row 3 contains panels 11, 12, 13, 14 and 15.

Header across the top of the sheet: the title [TITLE] in large bold letters on the left,
and on the right in smaller widely spaced capitals, [DURATION] SEC - [FORMAT]. Background
of the sheet is [BOARD COLOUR].

No panel number, badge, letter, digit, caption, watermark or graphic of any kind appears
anywhere inside any panel image. Every panel image is completely clean edge to edge, pure
picture only. The panel number appears instead at the start of the caption line beneath
each panel.

Directly beneath each panel, on the board outside the image area, sits a two-line caption
block set in a monospace typewriter font. Line one is the panel number, then the timecode
range, then the shot type in capitals. Line two is a short scene note of no more than ten
words.

The timecode ranges run consecutively at exactly [X] seconds per panel: panel 1 is
00:00-00:02, panel 2 is 00:02-00:04, [...list every panel explicitly...]. No two panels
share a timecode.

THE [N] PANELS:

1 [00:00-00:02] SHOT SIZE. One sentence: what is in frame, what happens, the emotional beat.
[...one line per panel...]

THE CHARACTER, identical in every panel: [full physical description and complete wardrobe,
matching the reference sheet exactly]

INSIDE EACH PANEL: [technique-led style block] [colour journey across the panels]
[explicit negatives]

Render the complete sheet: [N] panels in a strict [C]x[R] grid, all the same size, 16:9,
professional pre-production document, ultra sharp. Do not render a single large frame. Do
not merge the panels.
```

## Writing the panels

- **No two consecutive panels share a shot size.** Vary wide, medium, close, low angle,
  over-the-shoulder, macro.
- **Escalate** scale, contrast or tension across the sheet. The last third should be the
  most intense.
- **One or two sentences per panel.** Long panel text starves the model of capacity for
  the other fourteen.
- **Check setup and payoff.** Whatever is established early must be the same thing that
  pays off later. Describing an object vaguely in panel 5 and specifically in panel 12
  produces two different objects.
- **Any prop appearing in two or more panels** should be described identically every time,
  or given its own reference sheet.
- **A costume change** needs both outfits described explicitly, stating which panels use
  which.

## Board colour
Match the tone. Warm cream for animation and light stories, near-black charcoal for sci-fi
and thrillers, light grey for product and toy work.

## After the prompt
Deliver it in a single fenced code block, ready to copy. Below it, add three or four lines
covering: the style choices you made for anything unspecified, which panel is most likely
to miss and why, and a reminder to generate at the highest resolution available, because
the sheet's fidelity directly drives the quality of the video made from it.
