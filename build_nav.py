#!/usr/bin/env python3
"""Scan docs/ and build clean page titles + a grouped nav for the docs site.

Writes two files:
  * titles.yml      — an editable {filename: title} mapping (the title index).
                      Auto-filled for new docs; existing entries are preserved,
                      so manual edits survive re-runs.
  * properdocs.yml  — its `nav:` is regenerated from titles.yml, grouping the
                      documents by Regulation Part (plus "Other documents").

Run after sync.py adds/removes documents, then rebuild the site:
    ./.venv/bin/python build_nav.py
    ./.venv/bin/python sync.py --docs --no-sync
"""
from __future__ import annotations

import re
from pathlib import Path

import sync  # PART_TITLES, detect_part_*, title_candidates

DOCS = Path("docs")
TITLES_FILE = Path("titles.yml")
CONFIG_FILE = Path("properdocs.yml")

# Words kept fully uppercased; words kept lowercase (except first in a title).
ACRONYMS = {"UCI", "BMX", "MTB", "BFR", "ADR", "ADT", "TUE", "CEWC", "EN", "ENG", "ID"}
SMALL = {"of", "the", "and", "for", "to", "in", "on", "as", "a", "an", "at", "by", "or"}
# A heading starting with one of these is a section, not the document's title.
BAD_TITLE_STARTS = (
    "article", "title", "chapter", "section", "annex", "officials", "licence",
    "preamble", "equipment", "definition", "introduction", "entities subject",
    "national federations",
)

# Documents whose real title isn't a clean heading — curated by hand.
OVERRIDES = {
    "2023_UCI_ETHICS_EN_04-08-23": "UCI Code of Ethics",
    "2025_UCI_CONSTITUTION___CONGRESS_EN_sept": "UCI Constitution and Congress",
    "Restart_Protocol_for_Road_Cycling_-20250701-E-amendments_on_01.07.25":
        "Restart Protocol for Road Cycling",
    "FINAL-Cycling_Esports_Hydration_Testing_and_Weigh-In_Policy":
        "Cycling Esports Hydration Testing and Weigh-In Policy",
}

_DATE_YMD = re.compile(r"(?<!\d)(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)")
_DATE_DMY = re.compile(r"(?<!\d)(0[1-9]|[12]\d|3[01])[.\-](0[1-9]|1[0-2])[.\-](20\d{2}|\d{2})(?!\d)")
_VER_LINE = re.compile(
    r"(?im)(?:version on|applying on|amendments?\s+on|as (?:of|from))\s+"
    r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})"
)


# --------------------------------------------------------------------------- #
# Title casing
# --------------------------------------------------------------------------- #

def case_word(w: str, first: bool = False) -> str:
    if "-" in w and len(w) > 1:
        return "-".join(case_word(p, first and i == 0) for i, p in enumerate(w.split("-")))
    core = re.sub(r"[^A-Za-z]", "", w)
    if not core:
        return w
    if core.upper() in ACRONYMS:
        return w.upper()
    if not first and w.lower() in SMALL:
        return w.lower()
    out, seen = [], False
    for ch in w:  # capitalize the first alphabetic char, lowercase the rest
        if ch.isalpha():
            out.append(ch.upper() if not seen else ch.lower())
            seen = True
        else:
            out.append(ch)
    return "".join(out)


def case_title(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip(" -–—:.“”\"'")
    words = s.split()
    cased = [case_word(w, first=(i == 0)) for i, w in enumerate(words)]
    return " ".join(cased)


# --------------------------------------------------------------------------- #
# Title derivation
# --------------------------------------------------------------------------- #

def clean_stem_title(stem: str) -> str:
    s = re.sub(r"\b20\d{2}([.\-]?\d{2}){0,2}\b", " ", stem)
    s = re.sub(r"\b\d{6,8}\b", " ", s)
    s = re.sub(r"[-_]+E\b|[-_]+ENG\b|[-_]+EN\b", " ", s)
    s = re.sub(
        r"\b(final|sept|merged|updated|version|amendments?|rule[_ ]?changes?|upcoming)\b",
        " ", s, flags=re.I,
    )
    return case_title(re.sub(r"[_\-]+", " ", s))


def good_content_title(cands: list[str]) -> str | None:
    for c in cands:
        if c.lower().strip().startswith(BAD_TITLE_STARTS):
            continue
        if len(re.findall(r"[A-Za-z]{2,}", c)) < 2:
            continue
        return case_title(c)
    return None


def find_date(md: str, stem: str) -> str | None:
    if (m := _VER_LINE.search(md)):
        d, mo, y = m.group(1), m.group(2), m.group(3)
        y = "20" + y if len(y) == 2 else y
        return f"{int(d):02d}.{int(mo):02d}.{y}"
    if (m := _DATE_YMD.search(stem)):
        return f"{m.group(3)}.{m.group(2)}.{m.group(1)}"
    if (m := _DATE_DMY.search(stem)):
        y = m.group(3)
        return f"{m.group(1)}.{m.group(2)}.{'20' + y if len(y) == 2 else y}"
    return None


def is_amendment(md: str, stem: str) -> bool:
    if re.search(r"(?im)rules?\s+amendments?\s+applying on|amendments?\s+to regulations", md):
        return True
    return any(k in stem.lower() for k in ("amend", "rule_change", "rule-change", "upcoming"))


def make_title(md: str, stem: str) -> str:
    if stem in OVERRIDES:
        base, part = OVERRIDES[stem], None
    else:
        cands = sync.title_candidates(md)
        part = sync.detect_part_in_title(cands) or sync.detect_part_from_stem(stem)
        base = (
            f"Part {part} — {sync.PART_TITLES[part]}" if part in sync.PART_TITLES
            else (good_content_title(cands) or clean_stem_title(stem))
        )
    date, amend = find_date(md, stem), is_amendment(md, stem)
    if amend and date:
        return f"{base} (amendments {date})"
    if amend:
        return f"{base} (amendment)"
    if date:
        return f"{base} (in force {date})" if part else f"{base} ({date})"
    return base


# --------------------------------------------------------------------------- #
# titles.yml + nav generation
# --------------------------------------------------------------------------- #

def src_stem(filename: str) -> str:
    s = filename[:-3]
    return s.split("__", 1)[1] if "__" in s else s


def yaml_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def load_titles() -> dict[str, str]:
    titles: dict[str, str] = {}
    if TITLES_FILE.exists():
        for line in TITLES_FILE.read_text(encoding="utf-8").splitlines():
            if m := re.match(r'^([^\s#][^:]*):\s+"(.*)"\s*$', line):
                titles[m.group(1)] = m.group(2).replace('\\"', '"').replace("\\\\", "\\")
    return titles


def part_of(filename: str, md: str) -> str | None:
    cands = sync.title_candidates(md)
    return sync.detect_part_in_title(cands) or sync.detect_part_from_stem(src_stem(filename))


def main() -> None:
    files = sorted(f.name for f in DOCS.glob("*.md") if f.name != "index.md")
    existing = load_titles()           # preserve manual edits
    titles, parts = {}, {}
    for name in files:
        md = (DOCS / name).read_text(encoding="utf-8", errors="ignore")
        titles[name] = existing.get(name) or make_title(md, src_stem(name))
        parts[name] = part_of(name, md)

    # Disambiguate any colliding labels with the source stem.
    seen: dict[str, int] = {}
    for t in titles.values():
        seen[t] = seen.get(t, 0) + 1
    for name, t in list(titles.items()):
        if seen[t] > 1:
            titles[name] = f"{t} · {src_stem(name)}"

    # Write titles.yml (sorted by filename → groups Parts together).
    lines = [
        "# Page titles for the docs site — edit freely; build_nav.py preserves",
        "# existing entries and regenerates properdocs.yml's nav from this file.",
        "",
    ]
    lines += [f"{name}: {yaml_str(titles[name])}" for name in files]
    TITLES_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Build a grouped nav: Home, then Parts in order, then Other.
    order = ["1", "2", "3", "4", "5", "6", "6bis", "7", "8", "9",
             "10", "11", "12", "13", "14", "15", "16", "17"]
    groups: dict[str, list[str]] = {p: [] for p in order}
    other: list[str] = []
    for name in files:
        (groups[parts[name]] if parts[name] in groups else other).append(name)

    def sort_key(name: str):  # consolidated/base first, then by title
        t = titles[name]
        return (0 if "amendment" not in t.lower() else 1, t)

    nav = ["nav:", "  - Home: index.md"]
    for p in order:
        members = sorted(groups[p], key=sort_key)
        if not members:
            continue
        nav.append(f"  - {yaml_str(f'Part {p} – {sync.PART_TITLES[p]}')}:")
        nav += [f"      - {yaml_str(titles[n])}: {n}" for n in members]
    if other:
        nav.append("  - Other documents:")
        nav += [f"      - {yaml_str(titles[n])}: {n}" for n in sorted(other, key=sort_key)]

    # Preserve everything in properdocs.yml above any existing nav: block.
    head = []
    for line in CONFIG_FILE.read_text(encoding="utf-8").splitlines():
        if line.rstrip() == "nav:" or line.startswith("nav:"):
            break
        head.append(line)
    while head and not head[-1].strip():
        head.pop()
    CONFIG_FILE.write_text("\n".join(head + nav) + "\n", encoding="utf-8")

    print(f"{len(files)} docs -> titles.yml; nav written to properdocs.yml "
          f"({sum(1 for p in order if groups[p])} Part sections, {len(other)} other)")


if __name__ == "__main__":
    main()
