# Designer-mode rolling learnings

Watch-outs distilled from prior sessions. **Read this before starting
a Designer-mode session.** Refresh by hand from session-folder
`notes.md` files every 3-5 sessions.

## Common moodboard misreads

- **Text tilt** is often subtle (~3-6° counterclockwise = right-side
  up) and easy to miss when scanning. Look at whether the right edge
  of each text line sits higher than the left.
- **Line spacing** in handwritten copy is much tighter than the
  default font height. Caveat at fontSize=40 needs `height: 0.72` or
  similar — descenders of one line nearly touching ascenders of the
  next.
- **"Squiggle" underlines** are usually NOT sine waves. Common pattern:
  two short staggered strokes, one slightly higher and shorter than
  the other, each with a slight bow.
- **Stickers** in handmade designs are hand-drawn outline shapes —
  thin coral hearts, flat yellow stars with thick outlines — NOT
  system emojis. System emojis read as "I gave up" because they
  carry their own (incompatible) art style.
- **Text colors** in warm/cream designs are often a deep navy or warm
  black, not pure `#000000` or `#1F1B17`. Worth checking before
  defaulting to ink.
- **Cards have unusual layouts** — avatars hanging off the left edge,
  paper-tab stickers stuck to corners, slight per-card rotations.
  Check for any element that overflows its container.

## Common technique misreads

- **Borders that look "ink" not "digital"**. A 1.5px constant stroke
  always looks digital. Use a base layer (full path, low alpha,
  constant width) PLUS segmented pen-pressure variation (segments
  3-5px long, alpha 55-90%, width 1.4-1.8px). Cap alpha at 90% — never
  100% — or transitions read as breaks.
- **Shadow spread** is usually tighter than you'd guess. Default to
  blur 2-4px, alpha 25%, offset Y +3-4. Spread shadows (blur 12-18)
  read as Material elevation, not handmade lift.
- **Rotations on the wash / underline** apply to the whole stroke as
  a unit, not per segment. Wrap in `Transform.rotate` once.
- **Z-stacking matters for highlights**. The highlighter mark behind
  text must be drawn FIRST in the Stack — `children: [highlight,
  text]` — so text is above. Reversed = highlight covers letters.

## Layout proportions

- Greeting + pet selector spacing is tight in handmade designs — the
  squiggle's bottom-left corner sits ~12-16px above the next card,
  not 30+.
- Tab bar at the bottom is usually a floating pill (16px side
  margins, 8px above gesture nav), NOT flush like Material 3
  default.
- Section header → first card spacing is small (~6px), not the
  Material default (~12px+). Sections and their content sit close.
