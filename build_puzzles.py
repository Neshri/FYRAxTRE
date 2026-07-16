"""
Converts llm_selections_4cat.json (pipeline output, one entry per pivot word
with sense_ids/root_verification/reasoning) into stripped-down per-puzzle
JSON files the frontend can load directly.

Usage:
    python build_puzzles.py llm_selections_4cat.json puzzles/

Each pivot word becomes one file: puzzles/<word>.json
You still choose which word is "today's" puzzle -- either rename one to
match the date lookup in game.js, or extend that lookup to pick by date
from an index file (see build_index() below for a starting point).
"""

import json
import sys
from pathlib import Path


def convert_entry(pivot_word, entry):
    categories = []
    for cat in entry.get("categories", []):
        siblings = [s["word"] for s in cat.get("siblings", [])]
        if len(siblings) != 2:
            raise ValueError(
                f"{pivot_word} / {cat.get('sense_id')}: expected 2 siblings, got {len(siblings)}"
            )
        categories.append({
            "title": cat.get("definition", "").capitalize(),
            "words": siblings,
        })

    if len(categories) != 4:
        raise ValueError(f"{pivot_word}: expected 4 categories, got {len(categories)}")

    return {"pivot": pivot_word, "categories": categories}


def build_index(puzzle_words, out_dir):
    """Optional: writes an index.json mapping words to filenames, so a
    date-rotation script can pick one per day without touching game.js."""
    index_path = out_dir / "index.json"
    index_path.write_text(
        json.dumps({"words": puzzle_words}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main():
    if len(sys.argv) != 3:
        print("Usage: python build_puzzles.py <llm_selections_4cat.json> <output_dir>")
        sys.exit(1)

    src_path = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)

    with src_path.open(encoding="utf-8-sig") as f:
        data = json.load(f)

    ok, failed = [], []
    for word, entry in data.items():
        try:
            puzzle = convert_entry(word, entry)
        except ValueError as e:
            failed.append(str(e))
            continue
        out_path = out_dir / f"{word}.json"
        out_path.write_text(json.dumps(puzzle, ensure_ascii=False, indent=2), encoding="utf-8")
        ok.append(word)

    build_index(ok, out_dir)

    print(f"Wrote {len(ok)} puzzle files to {out_dir}")
    if failed:
        print(f"\nSkipped {len(failed)}:")
        for msg in failed:
            print(f"  {msg}")


if __name__ == "__main__":
    main()
