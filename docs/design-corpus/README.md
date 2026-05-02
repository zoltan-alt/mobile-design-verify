# Design corpus

Self-improvement layer for Designer mode. Each Designer-mode session
ends by writing a structured log here. Future sessions read this corpus
to prime moodboard-reading and avoid repeating mistakes.

## Structure

```
docs/design-corpus/
  README.md                    # this file
  _learnings.md                # rolling summary, refreshed by hand or by tooling
  <YYYY-MM-DD-slug>/
    moodboard.md               # what the user shared (image refs, vibes, copy)
    iterations.jsonl           # every (attempt, feedback, change) tuple
    final.md                   # accepted spec — element-by-element
    notes.md                   # things to remember next time
```

## Per-session contract

When Designer mode wraps:

1. **`moodboard.md`** — describe the source: a verbal summary of the
   image(s), the user's stated vibes, any copy they want preserved, and
   any constraints (e.g. "must use existing AppColors").
2. **`iterations.jsonl`** — append-only log, one JSON object per
   iteration:
   ```json
   {"step": 1, "attempt": "drew underline as sine wave", "user_feedback": "it's two parallel curves, not squiggly", "change": "rewrote painter to use two staggered quadratic Beziers"}
   ```
3. **`final.md`** — the accepted design as a structured spec. Every
   element gets:
   - **rect** (% of viewport)
   - **color tokens** referenced (`AppColors.primarySoft`, etc.)
   - **typography** (font, size, height, weight)
   - **rotations** if any
   - **special treatment** (washi tape, pen border, brush wash)
4. **`notes.md`** — short list of "next session, watch out for X". Free
   form, scoped to design observations, not generic Claude lessons (those
   go in user memory).

## How to use the corpus

When starting a new Designer-mode session, **before describing the
moodboard back**:

```
1. Read docs/design-corpus/_learnings.md
2. Read the 2-3 most recent docs/design-corpus/<...>/notes.md files
3. THEN do the moodboard-reading checklist from SKILL.md
```

The point of step 1-2 is so you walk into the moodboard read with prior
context: "in past sessions, you missed text tilt 4 times — check that
explicitly." Without this corpus, the skill stays at a constant baseline
and doesn't get better at reading designs.

## Updating `_learnings.md`

After every 3-5 sessions, distill `notes.md` files into the rolling
`_learnings.md`. Pattern: cluster repeated observations, drop any that
were one-off, keep what's likely to recur.

This is the human-curated layer. Don't append every observation
mechanically.
