# fyra × tre — game frontend

Static HTML/JS puzzle game modeled on Hank Green's *4×3*: four categories,
three words each, one shared word (the pivot) sitting in all four.

## Files

- `index.html` / `style.css` / `game.js` — the game itself, no build step
- `puzzles/example.json` — a sample puzzle (built from the "rörelse" pivot word), kept for reference
- `build_puzzles.py` — converts pipeline output (`llm_selections_4cat.json`) into per-word puzzle files, named `<word>.json`, useful for your own triage
- `anonymize_puzzles.py` — takes a folder of word-named puzzle files and produces `puzzles_deploy/`: shuffled, numbered `1.json, 2.json, ...` plus `manifest.json`. **This is the folder the game actually loads from** — no pivot word ever appears in a filename or URL, only inside the fetched JSON once you're playing that puzzle.

## Test locally

Browsers block `fetch()` on local files opened directly, so serve the folder:

```
cd FYRAxTRE
python -m http.server 8000
```

Then open `http://localhost:8000` in a browser.

## Current mechanic

- 9 tiles in a 3×3 grid, shuffled on load, always clickable
- Click up to 3 tiles, then Submit — validity is only checked on submit, nothing is disabled beforehand
- First correct guess: those 3 tiles (pivot + 2 words) scatter randomly across the three horizontal-axis slots (both ends plus center) — the pivot isn't given away, since any of the three could be it
- Second correct guess: the pivot snaps to true center, the first category's two words settle onto the axis endpoints, and the second category claims a diagonal axis
- Third and fourth guesses each claim the remaining axes (vertical, then the other diagonal)
- The pivot tile's color gradually blends — a 2-way split after guess 2, 3-way after guess 3, full 4-way pinwheel once solved — mixing the colors of every category it's confirmed to belong to so far
- Wrong guess: tiles shake, one mistake used (3 allowed)
- Results panel lists each solved category with its words (correct-guess toast also shows them inline)

## Picking a puzzle

There's no daily rotation — pick any puzzle by number. The picker bar shows
"Pussel X av Y" and has a "Nästa" button (cycles forward, wrapping back to 1)
and a jump-to-number field.

Puzzle numbers are **stable and permanent**: each pivot word gets assigned
the next free ID the first time `anonymize_puzzles.py` sees it, recorded in
a private `puzzle_id_map.json` file that is *not* part of the deployed
folder. Running the script again after adding more solved puzzles only
appends new IDs — it never reshuffles or renumbers existing ones, so
"puzzle #12" means the same thing every time you regenerate the deploy
folder.

## Wiring up your generated puzzles

1. Convert your pipeline output into word-named files (skip if you already
   have a `puzzles/` folder of these from an earlier run):
   ```
   python build_puzzles.py llm_selections_4cat.json puzzles/
   ```

2. Anonymize them into the folder the game actually serves:
   ```
   python anonymize_puzzles.py puzzles/ puzzles_deploy/
   ```
   This writes `puzzle_id_map.json` next to wherever you run it from (or
   pass `--map some/path.json` to control that). **Keep that file and the
   word-named `puzzles/` folder out of whatever you deploy** — e.g.
   `.gitignore` them, or keep them on a branch that isn't published to
   GitHub Pages. Only `puzzles_deploy/` (numbered files + `manifest.json`,
   no words anywhere) should actually go live.

## Deploy to GitHub Pages

1. Push this folder into your `FYRAxTRE` repo (https://github.com/Neshri/FYRAxTRE),
   e.g. at the root, or under `/docs`.
2. Repo Settings → Pages → Deploy from a branch → pick the branch and
   folder (`/root` or `/docs`).
3. Live at `https://neshri.github.io/FYRAxTRE/`.

No backend, no build step — GitHub just serves the static files.

**Only push `puzzles_deploy/` (plus the game files themselves).** Keep
`puzzles/` (word-named) and `puzzle_id_map.json` out of the repo entirely —
they're build-time-only and the game never fetches them. A `.gitignore`
entry for both is included so this doesn't happen by accident even if you
run the build scripts from inside the repo folder.