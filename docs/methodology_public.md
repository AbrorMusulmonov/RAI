# Public methodology

This document describes the workflow, not the private corpus. It contains no collected examples, source registry entries, platform item identifiers, detailed taxonomy definitions or private audit results. The short category overview in the project README is explanatory, not a replacement for the privately supplied annotation specification.

## Collection and evidence

Work begins with a human-authorized category scope and existing evidence. Re-mine private raw content before considering new collection. Only actually retrieved public content may become research evidence; a failed request, empty result or inaccessible discussion must remain a recorded limitation.

Keep original text unchanged. Normalization of script, spelling and apostrophe variants is for comparison only. Collection is append-only and deduplicates platform identifiers without deleting the original evidence already held locally.

Public accessibility is not permission to redistribute a source or its content. The researcher has identified dissemination concerns and has withheld the complete corpus and source registry from this release. This repository makes no claim that any particular source is lawful to redistribute. Publication review is separate from technical source verification.

## Two-stage retrieval

The first stage searches for plausible category relevance using lexical signals, morphology, script variants and supported semantic or contextual evidence. The second stage ranks plausible candidates by relevance, stance, evidence completeness, uniqueness and diversity.

- PRIMARY: strongly plausible category matches.
- SECONDARY: plausible but context-dependent, ambiguous or stance-uncertain matches.
- Broad discovery: topic-relevant material without sufficient evidence in the comment itself. This is separate from the primary review queue.

A relevant title alone is insufficient. Similarity to a taxonomy reference alone cannot establish PRIMARY. Neutral discussion, unrelated insults, copied spam and clear counter-speech must be distinguished from an attack; uncertain cases are for human review, not automatic acceptance.

Model reasoning may assist retrieval and ranking of real text. Any evidence span must be an exact substring of the retrieved text. A model score is never a human decision and must not change Review Status.

## Provenance, kept private

The private workspace retains platform, verified source identity, exact source URL, returned item identifier, retrieval time and available factual thread context. Reachability is a separate property from source identity: a successful HTTP response alone does not verify the page's identity.

Do not invent a direct comment URL, parent comment or contextual interpretation. Store a direct Content URL only if genuinely obtained from platform metadata or an official API. Otherwise leave it blank and retain the verified source URL plus exact item identifier privately.

None of those source-level values are included in public documentation, prompts, templates or notebooks. Generic field names describe the interface; they are not dataset records.

## Deduplication, audits and diversity

Keep raw occurrences intact while suppressing exact and near duplicates in the active review pool. Audit source concentration and linguistic diversity rather than using raw volume as a quality measure. Inspect both selected candidates and high-ranking exclusions to identify false positives and false negatives.

Estimated relevance and expected accepted yield are provisional research judgments, not final annotations. Document unsuccessful attempts and real shortages; never manufacture examples to meet a target. This public document does not publish corpus counts, per-source statistics or private audit selections.

## Human decisions and exports

New candidates remain PENDING. Canonical private review queues preserve Candidate ID, reviewer notes and existing ACCEPT, REJECT, UNSURE and MOVE_TO_OTHER_CATEGORY decisions. Human-reviewed rows must not be removed by a later automated cleanup.

Excel is a human interface, not an independent competing source of truth. Merge saved edits using stable Candidate IDs before regenerating workbooks. Accepted-only exports contain only human ACCEPT records. Review workbooks may contain PENDING candidates but remain private, as do all historical exports.

## Validation and limitations

Run fixture-based tests without the private corpus and the full historical suite in the authorized private workspace. Check preserved files against local hashes. Publication checks inspect tracked paths and content; the private evidence comparison is an additional check available only where the corpus exists.

No collection or annotation is performed by this documentation release. Coverage, source availability, platform bias, dialect variation, missing thread context and model error remain limitations. The public code and empty templates do not recreate the withheld study.
