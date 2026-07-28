#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_multisense_json.py
===========================
Reads words from `multisense_words.txt`, queries the Karp API for Lexin entries,
extracts and formats their Swedish senses, and writes them to a JSON dictionary
where the word is the key and the list of its senses is the value.

PATCHED (lexinID): senses are grouped by lexinID, Lexin's own identifier for
a distinct dictionary entry — NOT by baseform string matching. Verified
directly against raw API output that baseform can be identical for two
unrelated entries (noun "stämma" and verb "stämma" both have
baseform="stämma" but different lexinID: 1144651 vs 1144673), which would
otherwise silently merge them into one pivot.

PATCHED (rawForm re-merge): lexinID groups that share an identical rawForm
(the actual citation spelling) are re-merged before the 4-sense threshold
is applied. lexinID correctly separates genuinely distinct dictionary
entries, but some splits still print IDENTICALLY in-game (e.g. "plan"
splits into an adjective entry + two different-gender noun entries, all
spelled "plan") — checking the 4-sense minimum per lexinID was dropping
each of those individually even though the combined word had enough senses
and would render as one indistinguishable tile. Only entries whose rawForm
actually differs (e.g. noun "stämma" vs verb "stämmer") stay split, since
those can't share one tile.

PATCHED (Wiktionary fallback): if a rawForm group still falls short of the
4-sense minimum on Lexin data alone, additional senses are pulled from
Swedish Wiktionary (via the official MediaWiki API, not scraping) and
appended before giving up on the word. Wiktionary text is CC BY-SA
licensed, which explicitly permits this kind of reuse (unlike SAOL/SO,
which are not open data) — attribution belongs in the project's
README/credits. Lexin is left untouched as the primary source when it
already clears the threshold on its own; Wiktionary only fills the gap.
Each sense is tagged with "source": "lexin" or "source": "wiktionary" so
downstream steps (which need embeddings per sense) know which senses
still need to be embedded before they can flow through score_pivots.py.

REFACTORED: all Wiktionary-specific code (API details, POS mapping,
wikitext parsing) now lives in wiktionary.py -- this script only calls
get_wiktionary_senses() as a fallback data source, same as before, but no
longer defines any of it. See wiktionary.py for anything Wiktionary-related.
"""

import json
import os
import time
from collections import defaultdict
import requests

from wiktionary import get_wiktionary_senses

KARP_API = "https://spraakbanken4.it.gu.se/karp/v7/query/lexin"
INPUT_FILE = "generation\\multisense_words.txt"
OUTPUT_FILE = "generation\\multisense_words.json"
MIN_SENSES = 4


def fetch_senses(session: requests.Session, word: str) -> list[dict]:
    """
    Queries the Karp API for the given word and parses the Swedish senses.
    Groups by lexinID, not baseform string — baseform can be identical for
    two genuinely different dictionary entries (e.g. noun "stämma" and verb
    "stämma" share baseform="stämma" but have different lexinID: 1144651
    vs 1144673). lexinID is Lexin's own authoritative "this is one specific
    headword entry" identifier, and rawForm is the actual citation spelling
    for that entry (verbs are cited by present tense in Lexin, e.g.
    "stämmer" for the verb vs "stämma" for the unrelated noun) — both
    verified directly against raw API output, not inferred.
    """
    params = {
        "q": f"languages(and(equals|lang|swe||equals|baseform|{word}))",
        "size": 50
    }

    try:
        r = session.get(KARP_API, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"\n[Warning] Error fetching '{word}': {e}. Retrying once...")
        time.sleep(2)
        r = session.get(KARP_API, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()

    senses = []
    hits = data.get("hits", [])
    for hit in hits:
        entry = hit.get("entry", {})
        sense = entry.get("sense", {})

        languages = entry.get("languages", [])
        swe = next((l for l in languages if l.get("lang") == "swe"), None)
        if not swe:
            continue

        baseform = swe.get("baseform")
        if isinstance(baseform, list):
            baseform = baseform[0] if baseform else None

        if not baseform or not isinstance(baseform, str):
            continue

        if baseform.strip().lower() != word.strip().lower():
            continue

        sense_id = sense.get("senseid")
        if not sense_id:
            continue

        definition = sense.get("definition", {}).get("text", "").strip()
        if not definition:
            continue

        part_of_speech = swe.get("partOfSpeech", "?")
        phonetic = swe.get("phoneticForm")
        lexin_id = swe.get("lexinID")       # groups senses into distinct dictionary entries
        raw_form = swe.get("rawForm", baseform)  # actual citation spelling for this entry

        examples = []
        for ex in sense.get("examples", []):
            if ex.get("lang") == "swe" and ex.get("text"):
                examples.append(ex["text"])

        usage = sense.get("usg", [])

        senses.append({
            "id": sense_id,
            "lexin_id": lexin_id,
            "raw_form": raw_form,
            "part_of_speech": part_of_speech,
            "definition": definition,
            "phonetic": phonetic,
            "usage": usage,
            "examples": examples,
            "source": "lexin",
        })

    return senses

def main():
    if not os.path.exists(INPUT_FILE):
        print(f"Error: Input file '{INPUT_FILE}' not found.")
        return

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        words = [line.strip() for line in f if line.strip()]

    print(f"Loaded {len(words)} words from {INPUT_FILE}.")
    result = {}
    split_count = 0
    dropped_after_split = 0
    wiktionary_rescued = 0

    session = requests.Session()
    start_time = time.time()

    for i, word in enumerate(words, 1):
        print(f"\r[{i}/{len(words)}] Fetching senses for '{word}'...", end="", flush=True)
        try:
            senses = fetch_senses(session, word)

            # Deduplicate by sense ID
            unique_senses = []
            seen_ids = set()
            for s in senses:
                if s["id"] not in seen_ids:
                    seen_ids.add(s["id"])
                    unique_senses.append(s)

            # Group by lexinID first -- Lexin's own ground-truth "distinct
            # dictionary entry" identifier. Two senses can share an
            # identical baseform string while belonging to unrelated
            # entries (verified directly: noun "stämma" and verb "stämma"
            # both have baseform="stämma" but lexinID 1144651 vs 1144673)
            # -- grouping by baseform alone would silently merge them.
            by_lexin_id = defaultdict(list)
            for s in unique_senses:
                by_lexin_id[s["lexin_id"]].append(s)

            # Second pass: re-merge lexinID groups that share an identical
            # rawForm -- see module docstring.
            by_raw_form = defaultdict(list)
            for lexin_id, entry_senses in by_lexin_id.items():
                raw_form = entry_senses[0]["raw_form"]
                by_raw_form[raw_form].extend(entry_senses)

            multi_entry = len(by_raw_form) > 1
            if multi_entry:
                split_count += 1

            for raw_form, entry_senses in by_raw_form.items():
                key = raw_form

                if len(entry_senses) < MIN_SENSES:
                    # Lexin alone isn't enough -- try Wiktionary to fill
                    # the gap before giving up on this word.
                    wiktionary_senses = get_wiktionary_senses(session, raw_form)
                    if wiktionary_senses:
                        # Skip near-duplicate definitions of what Lexin
                        # already gave us, rather than padding the count
                        # with restatements of the same sense.
                        existing_defs = {s["definition"].strip().lower() for s in entry_senses}
                        for ws in wiktionary_senses:
                            if ws["definition"].strip().lower() not in existing_defs:
                                entry_senses.append(ws)
                                existing_defs.add(ws["definition"].strip().lower())
                    time.sleep(0.5)

                    if len(entry_senses) >= MIN_SENSES and any(s["source"] == "wiktionary" for s in entry_senses):
                        wiktionary_rescued += 1

                if len(entry_senses) >= MIN_SENSES:
                    result[key] = entry_senses
                else:
                    if multi_entry:
                        dropped_after_split += 1
                    print(f"\n[Warning] '{key}' has only {len(entry_senses)} valid senses "
                          f"(Lexin + Wiktionary combined) "
                          f"{'(one of multiple distinct spellings under this word) ' if multi_entry else ''}, skipping...")
        except Exception as e:
            print(f"\n[Error] Failed to process word '{word}': {e}")

        # Polite delay between requests
        time.sleep(0.05)

    print(f"\nFinished fetching. Writing data to {OUTPUT_FILE}...")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    duration = time.time() - start_time
    print(f"Successfully compiled {len(result)} pivots to {OUTPUT_FILE} in {duration:.1f} seconds.")
    print(f"  {split_count} queried words mapped to >1 distinct rawForm and were split.")
    print(f"  {dropped_after_split} split-off entries fell below the 4-sense minimum even with Wiktionary.")
    print(f"  {wiktionary_rescued} entries were rescued above the 4-sense minimum by Wiktionary.")

if __name__ == "__main__":
    main()