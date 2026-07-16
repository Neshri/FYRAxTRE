"""
Takes your working puzzles/ folder (files named <pivot>.json, human-readable
for triage) and produces a deploy-ready copy where puzzles are identified by
a stable integer ID instead -- so no filename or URL ever gives away the
pivot word before it's actually fetched during play.

IDs are permanent: each word gets assigned the next free integer the first
time it's seen, recorded in a private mapping file that is NOT part of the
deployed folder (keep it out of anything served by GitHub Pages). Re-running
this script after adding more solved puzzles only appends new IDs -- it
never reshuffles or renumbers existing ones.

Usage:
    python anonymize_puzzles.py puzzles/ puzzles_deploy/

Optional:
    python anonymize_puzzles.py puzzles/ puzzles_deploy/ --map puzzle_id_map.json

Only puzzles_deploy/ should be pushed to the folder GitHub Pages serves.
Keep puzzles/ and the id map file out of that folder (e.g. .gitignore them,
or just don't commit them to the deployed branch).
"""

import argparse
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source_dir", type=Path)
    ap.add_argument("deploy_dir", type=Path)
    ap.add_argument("--map", type=Path, default=Path("puzzle_id_map.json"),
                     help="Private word->id mapping file (default: ./puzzle_id_map.json)")
    args = ap.parse_args()

    args.deploy_dir.mkdir(parents=True, exist_ok=True)

    id_map = {}
    if args.map.exists():
        with args.map.open(encoding="utf-8") as f:
            id_map = json.load(f)

    files = sorted(args.source_dir.glob("*.json"))
    files = [f for f in files if f.name != "index.json"]  # skip old build_puzzles.py index, if present
    words = [f.stem for f in files]

    new_words = sorted(w for w in words if w not in id_map)
    next_id = (max(id_map.values()) + 1) if id_map else 1
    for w in new_words:
        id_map[w] = next_id
        next_id += 1

    with args.map.open("w", encoding="utf-8") as f:
        json.dump(id_map, f, ensure_ascii=False, indent=2, sort_keys=True)

    # clear out any stale numbered files from a previous run before writing
    for old in args.deploy_dir.glob("*.json"):
        if old.name != "manifest.json":
            old.unlink()

    current_ids = []
    for path, word in zip(files, words):
        puzzle_id = id_map[word]
        with path.open(encoding="utf-8") as f:
            puzzle = json.load(f)
        out_path = args.deploy_dir / f"{puzzle_id}.json"
        out_path.write_text(json.dumps(puzzle, ensure_ascii=False, indent=2), encoding="utf-8")
        current_ids.append(puzzle_id)

    current_ids.sort()
    manifest_path = args.deploy_dir / "manifest.json"
    manifest_path.write_text(json.dumps({"ids": current_ids}, indent=2), encoding="utf-8")

    print(f"Wrote {len(current_ids)} puzzle files to {args.deploy_dir}")
    print(f"{len(new_words)} new word(s) assigned IDs this run" if new_words else "No new words this run")
    print(f"ID map: {args.map} (keep this private -- do not deploy it)")


if __name__ == "__main__":
    main()