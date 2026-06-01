# UCI Regulations → Markdown

Tracks the [UCI Cycling Regulations](https://www.uci.org/regulations/3MyLDDrwJCJJ0BGGOFzOat)
as searchable, diffable Markdown.

The PDFs are published on UCI's CDN and change over time.

A script pulls the current set, detects what changed since the last run, and regenerates
only the affected Markdown — so `git diff` after a sync shows exactly which
regulations were amended.

Originally created by [jdanton](https://github.com/jdanton/ucirules)