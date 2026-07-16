# fyra × tre — game frontend

Static HTML/JS puzzle game modeled on Hank Green's *4×3*: four categories,
three words each, one shared word (the pivot) sitting in all four.

## Files

- `index.html` / `style.css` / `game.js` — the game itself, no build step
- `puzzles/example.json` — a sample puzzle (built from the "rörelse" pivot word)
- `build_puzzles.py` — converts pipeline output (`llm_selections_4cat.json`) into game-ready puzzle files

## Test locally

Browsers block `fetch()` on local files opened directly, so serve the folder:

```
cd automatic-doodle-game
python -m http.server 8000
```

Then open `http://localhost:8000` in a browser.

## Current mechanic

- 9 tiles in a fixed 3×3 grid, shuffled on load
- Click up to 3 tiles, then Submit
- Correct guess: those 3 tiles lock and take that category's color
- Wrong guess: tiles shake, one mistake used (3 allowed)
- Once all 4 categories are solved, the pivot tile gets a 4-color pinwheel background
- Results panel lists each category with its words, pivot underlined

This deliberately mirrors what the two screenshots showed of the real game.
Anything past that (share cards, streaks, history) wasn't visible in the
screenshots, so it's not implemented yet — freestyle territory for later.

## Wiring up your generated puzzles

1. Run your pipeline through `build_puzzles.py`:
   ```
   python build_puzzles.py llm_selections_4cat.json puzzles/
   ```
   This writes one `puzzles/<word>.json` per usable pivot word, plus an
   `index.json` listing all of them.

2. `game.js` currently always loads `puzzles/example.json` (see the
   `PUZZLE_PATH` constant at the top). For a real daily rotation you'll want
   to swap that for date-based logic — e.g. read today's date, look it up
   against `index.json` or a `puzzles/YYYY-MM-DD.json` file. Not built yet
   since it depends on how you want to handle "no puzzle for today" and
   replaying past puzzles — worth deciding deliberately rather than
   guessing at your intent here.

## Deploy to GitHub Pages

1. Push this folder into your `automatic-doodle` repo (e.g. at the root, or
   under `/docs`).
2. Repo Settings → Pages → Deploy from a branch → pick the branch and
   folder (`/root` or `/docs`).
3. Live at `https://<username>.github.io/automatic-doodle/`.

No backend, no build step — GitHub just serves the static files.
