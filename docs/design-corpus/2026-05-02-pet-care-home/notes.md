# 2026-05-02 — Pet-care home — design notes

Things to remember next time, scoped to design observation rather than
behavior.

## Moodboard misreads I made

- **Text tilt**: missed entirely on first pass. The "Hey there, / Pet
  Parent!" block tilts ~6° counterclockwise. Default-rendered upright,
  user had to call it out.
- **Line spacing**: shipped with `height: 0.85`, way too loose. Caveat
  at fontSize=40 needs `height: 0.72`.
- **"Squiggle" underline**: shipped a sine wave on first attempt. The
  actual reference is two short staggered curves, each ~30-40% of the
  text width, one upper-left and shorter, one lower-right and longer.
  Spent 8+ iterations dialing in the exact endpoints.
- **Stickers**: shipped system emoji ❤️⭐ for the heart and star. The
  reference uses thin hand-drawn coral outline + flat yellow filled
  star. Different visual language. (User later said remove all emojis
  for this design, so it was moot — but the read was still wrong.)
- **Section headers**: shipped as white pill cards with sticker. The
  reference is bare text on cream with a soft purple highlighter mark
  drawn behind via z-stack, length = full text width with end pulled
  ~3/4 stroke inside.
- **Star position**: placed it in the top header row alongside heart +
  bell. Correct position is between the two text lines on the right.

## Technique misreads

- **First attempt at the underline**: rendered as a single sine wave at
  full width. Took multiple iterations to learn it should be two
  staggered curves, not parallel — first stroke shorter and upper-left,
  second longer and lower-right, with the second stroke's bow peaking
  where the first stroke ends.
- **Pen-pressure border** on cards: started with segmented dashes only,
  no base layer. Looked too dashed. The fix was to draw a continuous
  low-alpha base FIRST, then the variation pass on top.
- **Shadows**: started with blur 12-16, looked like Material elevation.
  Tightened to blur 2-3 with alpha 25%, much more "lifted off paper".

## Final accepted spec

See `final.md`. The migrated component code is in
`pet-ops/lib/core/widgets/` and `pet-ops/lib/presentation/home/`.

## What worked well

- Once we hit the "describe → stop → wait" pattern, iterations became
  surgical. Each round was a single change with a single visual claim
  to verify.
- Dialing in coordinates by exact percentages (user said "left start
  20, peak 40, end 60") was very effective once the high-level shape
  was right.
- The schtask build helper (`scripts/_claude-windows-build.py`)
  removed the "tell me when it's running" handshake — full rebuild
  cycle was ~30s, but Claude-driven instead of user-driven.
