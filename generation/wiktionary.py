#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wiktionary.py
=============
All Swedish-Wiktionary-specific code. Extracted out of
generate_multisense_json.py, which is really about the Lexin/Karp
multisense-building pipeline -- Wiktionary is only a fallback there. Other
scripts (e.g. llm_select_pivot_categories.py, which uses
get_wiktionary_senses() purely to verify a suggested sibling word during
puzzle generation, nothing to do with building multisense_words.json)
should import from here directly instead of reaching into that script.

Talks to the official MediaWiki API (raw wikitext, not scraped HTML).
Wiktionary text is CC BY-SA licensed; attribution belongs in the project's
README/credits.

This is a straight move of the existing, working code -- the only change
beyond relocation is splitting get_wiktionary_senses() into three pieces
(_fetch_wikitext, _svenska_sections, get_wiktionary_senses itself) so the
fetch-with-retry logic is defined once, not duplicated when a lemma-lookup
function is added here next.
"""

import re
import html
import time
import requests

WIKTIONARY_API = "https://sv.wiktionary.org/w/api.php"
WIKTIONARY_USER_AGENT = "AutomaticDoodleBot/1.0 (anton/automatic-doodle) python-requests"

# Swedish POS labels (Wiktionary section headings) -> SALDO/Lexin-style short
# tags, so Wiktionary-sourced senses carry the same part_of_speech convention
# as Lexin senses elsewhere in the pipeline. Only nn/vb/av/ab/pp have been
# directly confirmed against real Lexin data so far (see score_pivots.py's
# own CLOSED_CLASS_POS comment) -- the rest are reasonable-guess mappings,
# not verified, so double check if one of these classes turns up a lot.
WIKTIONARY_POS_MAP = {
    "substantiv": "nn",
    "verb": "vb",
    "adjektiv": "av",
    "adverb": "ab",
    "preposition": "pp",
    "pronomen": "pn",
    "konjunktion": "kn",
    "interjektion": "in",
}

# Only pull definitions from these Wiktionary headings -- same restriction
# as the original lookup script, so we don't pick up idiom/phrase entries
# etc. as if they were senses of the bare pivot word.
WIKTIONARY_VALID_SECTIONS = set(WIKTIONARY_POS_MAP.keys()) | {
    "räkneord", "artikel", "prefix", "suffix", "partikel", "förkortning",
    "ordstäv", "talesätt", "idiom", "egennamn", "fras", "ordspråk",
}


def _fetch_wikitext(session: requests.Session, word: str) -> dict | None:
    """
    Fetch-with-retry for the MediaWiki 'parse' action. Factored out so both
    get_wiktionary_senses() and any future lookup (e.g. a lemma/inflection
    lookup) share one rate-limit/backoff implementation instead of each
    copying it. Returns the parsed JSON response, or None on failure,
    rate-limit exhaustion, or an API-reported error.
    """
    params = {"action": "parse", "page": word.lower(), "prop": "wikitext", "format": "json"}
    headers = {"User-Agent": WIKTIONARY_USER_AGENT}

    max_retries = 4
    backoff = 5  # seconds, doubles each retry if no Retry-After header is given

    for attempt in range(max_retries + 1):
        try:
            r = session.get(WIKTIONARY_API, params=params, headers=headers, timeout=10)
            if r.status_code == 429:
                if attempt == max_retries:
                    print(f"\n[Warning] Wiktionary still rate-limiting '{word}' after {max_retries} retries, giving up.")
                    return None
                wait = int(r.headers.get("Retry-After", backoff))
                print(f"\n[Info] Wiktionary rate limit hit on '{word}', waiting {wait}s before retry "
                      f"({attempt + 1}/{max_retries})...")
                time.sleep(wait)
                backoff *= 2
                continue
            r.raise_for_status()
            data = r.json()
            break
        except requests.exceptions.HTTPError as e:
            print(f"\n[Warning] Wiktionary fetch failed for '{word}': {e}")
            return None
        except Exception as e:
            print(f"\n[Warning] Wiktionary fetch failed for '{word}': {e}")
            return None

    if "error" in data:
        return None
    return data


def _svenska_sections(wikitext: str) -> list[str]:
    """
    Splits raw wikitext into the body text of every "==Svenska==" /
    "==Svenska N==" section. Wiktionary sometimes splits genuine
    etymological homographs into "== Svenska 1 ==", "== Svenska 2 =="
    etc, instead of one "== Svenska ==" section covering all senses
    (verified directly against real pages, e.g. domain-spanning "stämma").
    All matching sections are returned so the caller can merge them -- a
    shared spelling is one printable tile in this project regardless of
    Wiktionary's etymological grouping, same principle as Lexin's rawForm
    merge in generate_multisense_json.py.

    Lenient substring search for the heading (no requirement on what
    immediately precedes/follows the '==' markers, e.g. a language-icon
    template can sit on the same line) -- a stricter exact-newline version
    was tried first and silently matched nothing on real pages.
    """
    heading_matches = list(re.finditer(r'==\s*Svenska(?:\s+\d+)?\s*==', wikitext, re.IGNORECASE))
    sections = []
    for hm in heading_matches:
        remainder = wikitext[hm.end():]
        # Bound the section at the next level-2 language heading, same
        # pattern as the original script (uppercase-starting heading on
        # its own line straight after two '=').
        next_lang = re.search(r'\n==\s*[A-Z]', remainder)
        sections.append(remainder[:next_lang.start()] if next_lang else remainder)
    return sections


def get_wiktionary_senses(session: requests.Session, word: str) -> list[dict]:
    """
    Fetches Swedish senses for `word` from Wiktionary. Returns a list of
    dicts matching the same shape as Lexin senses (id/lexin_id/raw_form/
    part_of_speech/definition/phonetic/usage/examples), tagged
    "source": "wiktionary", with synthetic ids like "wiktionary--ord..1".
    """
    data = _fetch_wikitext(session, word)
    if data is None:
        return []

    wikitext = data["parse"]["wikitext"]["*"]
    svenska_sections = _svenska_sections(wikitext)
    if not svenska_sections:
        return []

    senses = []
    for sv_text in svenska_sections:
        word_class = None
        for line in sv_text.split('\n'):
            line = line.strip()

            class_match = re.match(r'^={3,}\s*([^=]+?)\s*={3,}$', line)
            if class_match:
                heading = class_match.group(1).strip().lower()
                word_class = heading if heading in WIKTIONARY_VALID_SECTIONS else None
                continue

            if not word_class:
                continue

            def_match = re.match(r'^#+([^*:;].*)', line)
            if not def_match:
                continue

            raw_def = def_match.group(1).strip()
            raw_def = html.unescape(raw_def)
            raw_def = re.sub(r'<!--.*?-->', '', raw_def)
            while re.search(r'\{\{[^{}]*\}\}', raw_def):
                raw_def = re.sub(r'\{\{[^{}]*\}\}', '', raw_def)
            raw_def = re.sub(r'\[\[(?:[^\]|]+\|)?([^\]|]+)\]\]', r'\1', raw_def)
            raw_def = re.sub(r"'{2,}", "", raw_def)
            raw_def = re.sub(r'\[http[^\s]+\s+([^\]]+)\]', r'\1', raw_def)
            raw_def = re.sub(r'\s+', ' ', raw_def).strip()

            if raw_def:
                senses.append({
                    "id": f"wiktionary--{word.lower()}..{len(senses) + 1}",
                    "lexin_id": None,
                    "raw_form": word,
                    "part_of_speech": WIKTIONARY_POS_MAP.get(word_class, word_class),
                    "definition": raw_def,
                    "phonetic": None,
                    "usage": [],
                    "examples": [],
                    "source": "wiktionary",
                })

    return senses


def get_base_lemma(session: requests.Session, word: str, target_pos: str) -> str | None:
    """
    Resolves an inflected Swedish word form to its base lemma, scoped to a
    single target_pos (short tag, e.g. "av", "vb" -- same convention as
    part_of_speech elsewhere in this pipeline).

    POS-scoping matters because a single spelling is often ambiguous across
    parts of speech in exactly the way that breaks a naive "just grab the
    first inflection pointer on the page" approach: "begränsade" is BOTH
    the plural/definite form of the adjective "begränsad" AND the past
    tense of the verb "begränsa", as two separate Svenska/Adjektiv and
    Svenska/Verb sections on the same page (confirmed directly against
    real API output). Without knowing which POS the caller actually wants,
    which pointer to trust would depend on whichever section happens to
    come first in the wikitext -- which isn't something Wiktionary
    guarantees stays fixed. Only sections whose own heading maps to
    target_pos are inspected here, so the caller's already-known POS
    context (verify_and_correct_sibling always has one) does the
    disambiguation instead of section order.

    Within that target_pos-scoped content:
    - a genuine standalone definition (not a recognized inflection
      pointer) means this word already has its own sense for target_pos --
      no resolution needed, returns None so the caller keeps treating it
      as a real word rather than redirecting it.
    - exactly one distinct inflection pointer found, no standalone
      definition -- returns that lemma.
    - more than one DISTINCT lemma pointer for the same target_pos (rare --
      e.g. Wiktionary's etymological-homograph section splits), or nothing
      found at all -- returns None rather than guessing. Same "don't pick
      when genuinely ambiguous" principle as disambiguate_homographs() in
      llm_select_pivot_categories.py.

    Three inflection-pointer patterns are recognized:
    1. {{böjning|sv|POS|LEMMA}} (and the older {{böjningsform|...}} name)
       -- CONFIRMED against real API output.
    2. {{sv-XXX-form|LEMMA}} template family -- UNCONFIRMED. Plausible
       given Wiktionary's general template-naming conventions, but not
       verified against any real page fetched in this project. Kept
       because it's cheap and shouldn't false-positive on anything real,
       but if inflection resolution is silently missing words, this is a
       plausible reason to check whether such a template actually exists.
    3. Plain prose "böjningsform av [[lemma]]" -- UNCONFIRMED, a defensive
       fallback for older-style entries that may predate the template.
       Same caveat as #2.
    """
    data = _fetch_wikitext(session, word)
    if data is None:
        return None

    wikitext = data["parse"]["wikitext"]["*"]
    found_lemmas = []
    has_real_definition = False

    for sv_text in _svenska_sections(wikitext):
        word_class = None
        for line in sv_text.split('\n'):
            line = line.strip()

            class_match = re.match(r'^={3,}\s*([^=]+?)\s*={3,}$', line)
            if class_match:
                heading = class_match.group(1).strip().lower()
                word_class = heading if heading in WIKTIONARY_VALID_SECTIONS else None
                continue

            if not word_class or WIKTIONARY_POS_MAP.get(word_class, word_class) != target_pos:
                continue  # not the requested POS -- ignore this section's content entirely

            if not line.startswith('#') or line.startswith('#:') or line.startswith('#*'):
                continue

            m_template = re.search(r'\{\{\s*böjning(?:sform)?\s*\|\s*sv\s*\|[^|]+\|\s*([^|}]+)', line)
            m_form = re.search(r'\{\{\s*sv-[a-z]+-form\s*\|\s*([^|}]+)', line)
            clean_line = re.sub(r"'{2,}", "", line)
            m_text = re.search(
                r'böjningsform av\s+(?:\[\[([^\]|]+)(?:\|[^\]]+)?\]\]|([^\s.,;]+))',
                clean_line, re.IGNORECASE,
            )

            if m_template:
                found_lemmas.append(m_template.group(1).strip())
            elif m_form:
                found_lemmas.append(m_form.group(1).strip())
            elif m_text:
                found_lemmas.append((m_text.group(1) or m_text.group(2)).strip())
            else:
                has_real_definition = True

    if has_real_definition:
        return None
    distinct = set(found_lemmas)
    if len(distinct) == 1:
        return found_lemmas[0]
    return None  # zero or ambiguous (>1 distinct) -- don't guess


def get_base_lemma_senses(session: requests.Session, word: str, target_pos: str) -> list[dict]:
    """
    Convenience wrapper: resolves `word` to its base lemma for target_pos
    via get_base_lemma() if it's purely an inflected form, then returns
    that lemma's own senses (via get_wiktionary_senses(), filtered to
    target_pos). If `word` isn't an inflected form for target_pos (has its
    own real definition, or no inflection pointer was found or it was
    ambiguous), falls back to fetching senses for `word` itself, still
    filtered to target_pos.
    """
    lemma = get_base_lemma(session, word, target_pos)
    lookup_word = lemma if lemma else word
    return [s for s in get_wiktionary_senses(session, lookup_word) if s["part_of_speech"] == target_pos]
