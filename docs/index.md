# UCI Regulations → Markdown

Tracks the [UCI Cycling Regulations](https://www.uci.org/regulations/3MyLDDrwJCJJ0BGGOFzOat)
as searchable, diffable Markdown.

> **Updated 2026-06-08 — new UCI rules synced.**
> **21 documents added, 11 superseded versions removed** (now 99 documents).
> Highlights:
>
> - A package of amendments in force **01.07.2026** across Part 1 (General
>   Organisation), Part 2 (Road Races), Part 3 (Track), Part 8 (Indoor),
>   Part 12 (Discipline), Part 14 (Anti-Doping) and Cyclo-cross.
> - Forward-dated rule changes for **2027** and **2028** (Parts 1, 2, 3).
> - A new **UCI Testing and Investigations Regulations** (05.06.2026) and TIR
>   amendments, plus refreshed **Ad Hoc Rules** and neutral-rider annex.
>
> 👉 See **[What changed](whats-changed.md)** for an article-by-article summary.

The PDFs are published on UCI's CDN and change over time.

A script pulls the current set, detects what changed since the last run, and regenerates
only the affected Markdown — so `git diff` after a sync shows exactly which
regulations were amended.

Originally created by [jdanton](https://github.com/jdanton/ucirules)