"""
Converts my_results.json (llm_select_pivot_categories.py output -- one entry
per pivot word, each with a "puzzles" list) into stripped-down per-puzzle
JSON files the frontend can load directly.

Usage:
    python build_puzzles.py my_results.json puzzles/

Each puzzle becomes one file. A pivot with only one puzzle gets
puzzles/<word>.json; a pivot with several gets <word>.json, <word>-2.json,
<word>-3.json, etc. -- the numbering is stable across reruns as long as the
puzzle order in the source file doesn't change.

You still choose which puzzle is "today's" -- either rename one to match
the date lookup in game.js, or extend that lookup to pick by date from
index.json (see build_index() below for a starting point; its shape is a
flat list of puzzle descriptors, not wired into game.js yet).
"""

import json
import re
import sys
from pathlib import Path

# Matches a trailing/embedded lexicographic cross-reference like the "(2)"
# in "ärende (2)" -- LEXIN's way of pointing at a specific homonym sense.
# Deliberately narrow: only parens whose ENTIRE content is digits (optionally
# with a leading sense-number dot, e.g. "(2)" or "(2.1)") get stripped, so a
# real parenthetical like "(ibland även mat)" is left alone.
LEXIN_SENSE_REF_RE = re.compile(r"\s*\(\d+(?:\.\d+)?\)")


def clean_text(text):
    """Strips LEXIN sense-reference artifacts and normalizes whitespace."""
    if not text:
        return text
    text = LEXIN_SENSE_REF_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def convert_puzzle(pivot_word, puzzle_number, puzzle):
    """
    Converts one puzzle dict (puzzle["categories"] is a list of 4 category
    dicts, each with 2 siblings) into the frontend's flat shape.

    "title" is the category_label the LLM was explicitly asked to produce
    as a short, playable category name (e.g. "MILITÄR RANG") -- not the raw
    dictionary "definition", which is a full sentence and reads wrong as a
    Connections-style header. "definition" is kept alongside as an optional
    clue/hint field for the frontend to use or ignore; it wasn't available
    at all in the previous schema, so this is additive, not a replacement
    for anything game.js may currently read.

    Raises ValueError on anything that shouldn't ship: wrong category/
    sibling counts, or a word reused across categories within the same
    puzzle (would mean two tiles show the same word -- a game-breaking bug,
    not a quality nitpick, so this checks even though the generation
    pipeline's own gate should already prevent it).
    """
    categories = puzzle.get("categories", [])
    if len(categories) != 4:
        raise ValueError(
            f"{pivot_word} puzzle {puzzle_number}: expected 4 categories, got {len(categories)}"
        )

    out_categories = []
    seen_words = set()
    for cat in categories:
        siblings = cat.get("siblings", [])
        if len(siblings) != 2:
            raise ValueError(
                f"{pivot_word} puzzle {puzzle_number} / {cat.get('sense_id')}: "
                f"expected 2 siblings, got {len(siblings)}"
            )

        words = [clean_text(s.get("word", "")) for s in siblings]
        if not all(words):
            raise ValueError(
                f"{pivot_word} puzzle {puzzle_number} / {cat.get('sense_id')}: empty sibling word"
            )
        for w in words:
            key = w.strip().lower()
            if key in seen_words:
                raise ValueError(
                    f"{pivot_word} puzzle {puzzle_number}: word '{w}' appears in more than "
                    f"one category -- would show as a duplicate tile"
                )
            seen_words.add(key)

        title = clean_text(cat.get("category_label", "")).upper()
        if not title:
            raise ValueError(
                f"{pivot_word} puzzle {puzzle_number} / {cat.get('sense_id')}: missing category_label"
            )

        out_categories.append({
            "title": title,
            "words": words,
            "definition": clean_text(cat.get("definition", "")),
            "word_definitions": [clean_text(s.get("definition", "")) for s in siblings],
        })

    return {"pivot": pivot_word, "categories": out_categories}


def build_index(puzzle_descriptors, out_dir):
    """
    Optional: writes an index.json listing every puzzle file produced, so a
    date-rotation script can pick one per day without touching game.js.
    Flat list rather than grouped-by-word, since with multiple puzzles per
    pivot a rotation script picks *puzzles*, not words.
    """
    index_path = out_dir / "index.json"
    index_path.write_text(
        json.dumps({"puzzles": puzzle_descriptors}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main():
    if len(sys.argv) != 3:
        print("Usage: python build_puzzles.py <my_results.json> <output_dir>")
        sys.exit(1)

    src_path = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)

    with src_path.open(encoding="utf-8-sig") as f:
        data = json.load(f)

    ok_descriptors = []
    failed = []
    skipped_no_puzzles = []
    errored_words = []

    for word, entry in data.items():
        if "error" in entry:
            errored_words.append(word)
            continue

        puzzles = entry.get("puzzles", [])
        if not puzzles:
            skipped_no_puzzles.append(word)
            continue

        for i, puzzle in enumerate(puzzles, 1):
            try:
                converted = convert_puzzle(word, i, puzzle)
            except ValueError as e:
                failed.append(str(e))
                continue

            filename = f"{word}.json" if i == 1 else f"{word}-{i}.json"
            out_path = out_dir / filename
            out_path.write_text(json.dumps(converted, ensure_ascii=False, indent=2), encoding="utf-8")
            ok_descriptors.append({"word": word, "file": filename, "puzzle_number": i})

    build_index(ok_descriptors, out_dir)

    print(f"Wrote {len(ok_descriptors)} puzzle file(s) to {out_dir}")
    if skipped_no_puzzles:
        print(f"\n{len(skipped_no_puzzles)} word(s) had no puzzles to convert (not an error): "
              f"{skipped_no_puzzles[:20]}{' ...' if len(skipped_no_puzzles) > 20 else ''}")
    if errored_words:
        print(f"\n{len(errored_words)} word(s) had a recorded generation error, skipped: {errored_words}")
    if failed:
        print(f"\n{len(failed)} puzzle(s) failed conversion:")
        for msg in failed:
            print(f"  {msg}")


if __name__ == "__main__":
    main()