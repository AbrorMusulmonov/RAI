# Local book extraction and deep-audit workflow

This is a separately written, source-free summary of the project's local reference-book and literary-corpus work. It is not a dataset release, a source list, a verbatim task transcript or a replacement for private provenance records. No quotations, book identities, source addresses, page-level locators or candidate identifiers are published here.

## Two distinct research tracks

The local reference-book track extracts plausible evidence from authorized language-reference material. Definitions, figurative expressions, cross-references and embedded literary quotations can help retrieval, but a negative dictionary meaning is not automatically evidence for every taxonomy boundary. Material without a defensible category remains separate from category review pools.

The literary track examines dialogue, narration, social conflict, character judgement and mockery in an explicitly limited local corpus. A prejudiced character's speech is not attributed to the author. Neutral descriptions, dialect performance and ordinary family discussion are not treated as abuse merely because they contain search vocabulary.

Both tracks have undergone iterative recovery and local page verification. Subsequent work resumes saved checkpoints rather than restarting extraction. These are candidate-retrieval workflows, not human annotation: provenance verification does not imply category acceptance, and some categories remain source-limited.

## Evidence and append-only handling

1. Inspect the current private workbook, review state, checkpoint and extracted-page indexes. Respect the current source allowlist and task scope; do not introduce external material during a local-only task.
2. Search existing text/OCR using script, spelling and contextual variants. Read surrounding scenes rather than selecting by keyword alone. OCR is a discovery aid, not authoritative quotation text.
3. Compare each retained quotation with the actual PDF page. Keep exact wording and original script, factual context, book/author identity, PDF page and printed page where available. Check page numbering individually rather than assuming a constant offset.
4. Compare new material against existing and staged quotations. Check exact text, normalized punctuation/script variants, overlapping passages and near duplicates. Do not create extra examples by paraphrasing or changing punctuation.
5. Append only verified evidence. Preserve existing example cells, identifiers, human decisions and original sources. Model-assisted retrieval must not create ACCEPT labels.
6. Save checkpoints and private audit evidence. Record completed work, selected candidates, verified additions, unresolved boundaries and the next unfinished step. Distinguish indexed pages, search windows, inspected passages and retained examples.

A Latin-script display, when explicitly requested, must remain traceable to separately preserved original-script evidence. It is not a license to rewrite quotations or silently normalize previously reviewed rows.

## Validation and limits

Source hashes, row-preservation assertions, duplicate screening, mandatory-field checks and a fresh random page recheck support integrity. Normal read-only Excel opening and structural checks help detect workbook compatibility problems. Fixture-based regression tests protect the public pipeline; private evidence checks require the authorized local inputs.

Targeted corpus-wide retrieval is not proof that every page has been manually read or that no further example exists. OCR omissions, historical usage, stance and category boundaries remain limitations. Search targets are not quotas: preserve real shortages rather than adding weak evidence. Final taxonomy decisions belong to human reviewers.

## What this release does not include

PDFs, extracted pages, workbooks, candidate tables, source registries, page images, private checkpoints, source-specific scripts and detailed book audits remain local. Existing social-platform evidence and links are also withheld. Public documentation and publication guards do not recreate the private research corpus in a fresh clone.

See [publication policy](github_publishing.md) and [sanitized prompt summaries](PROMPTS.md). No new collection or human annotation is performed by publishing this documentation.
