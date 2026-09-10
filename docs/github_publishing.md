# Publication and privacy policy

## Code and privacy-safe documentation

The researcher withdrew permission to publish taxonomy PDFs and collected datasets and explicitly authorized removing their copies from existing Git history. The publication target remains the existing `AbrorMusulmonov/RAI` repository and its `main` branch. Repository visibility must not be changed as part of cleanup.

The following are private local material, including filtered copies and derived artifacts:

- All of `data/`, `config/` and `notebooks/`.
- All PDFs, Excel workbooks, CSV/JSONL datasets and supported columnar/database files.
- `PROMPTS.md` and detailed research documents: `docs/methodology.md`, `docs/collection_log.md`, `docs/final50_report.md` and `docs/source_strategy.md`.
- Credentials, sessions, local backups, environment files other than the empty template, and `.publish-local/` preparation artifacts.

The researcher subsequently authorized separate public methodology and source-strategy summaries, empty configuration templates, sanitized prompt summaries and a short README category overview. These are under `docs/*_public.md`, `docs/PROMPTS.md` and `examples/config/`; the original private files remain unchanged. The public prompt document explicitly identifies itself as newly written summaries, not a verbatim historical archive. Short category descriptions are not the full PDF definitions or reference examples.

Collected source URLs must not appear in public artifacts. This includes shortened/encoded links, video or comment IDs from which a link can be reconstructed, source titles and publisher names. Actual raw text, review decisions and source-level audit decisions remain private even when the underlying content was publicly accessible. These restrictions reflect the researcher's dissemination concerns; the repository does not certify legal permission to redistribute sources.

The software implementation and general documentation may remain tracked. `.gitignore` prevents routine staging of private paths; `scripts/check_private_tracking.py` independently rejects those paths already present in the index or a specified commit. Neither filenames nor a heuristic content scan can guarantee that an arbitrary new code/documentation file contains no copied research text. Inspect content before publishing.

`scripts/check_public_content.py` reads actual Git index bytes (or a specified commit), not an unstaged sanitized working copy. It rejects concrete platform URLs and reconstructable identifiers. With `--private-evidence` it additionally compares local source metadata, identifiers, source URLs and original comments of at least 25 characters. Reports disclose only paths and finding types/counts, never matched private values. A common methodological word coinciding with a publisher name is treated as vocabulary, not attribution. Short/common text, arbitrary transformations and sources absent from the local evidence are limitations; passing is not a legal or complete privacy guarantee.

Source-specific maintenance dispositions and source-quality markers formerly embedded in a helper are now held in ignored `config/source_dispositions.private.json`. The other configuration helper loads its observed-language specifications from ignored `config/remaining_retrieval.private.json`. Their values are preserved locally; the helpers require their private inputs before doing any work and do not publish identifiers. No maintenance, collection or re-mining is run by this release. The generic pipeline is otherwise unchanged. Test-only provenance uses a reserved nonresolving `.invalid` domain and is never represented as collected evidence.

## Local preservation

Removing a file from Git tracking must not delete or rewrite its local original. Existing raw text, candidate IDs, human decisions, final ID mappings and exports must remain unchanged. Use index-only removal for tracked private files; do not use destructive checkout/reset operations on the research workspace.

The ignored pre-publication SHA-256 snapshot supports checking original configuration and research files:

```powershell
python scripts/audit_publish.py --staged --verify-snapshot
```

That snapshot is a private local prerequisite, not something supplied by a fresh clone. Backup copies of replaced general documentation are also kept locally under `.publish-local/`.

## History cleanup

Deleting files in a new commit alone leaves their earlier contents in Git history. The authorized cleanup replaces the data-containing publication commit with a code-only commit based on the original clean repository commit. The original LICENSE is retained. Before updating the remote, compare branch tips and use an explicit `--force-with-lease` for `main` so an unexpected concurrent update is not silently overwritten. Do not mirror-push, recreate the repository or modify an unrelated ancestor repository.

Verify both the resulting commit trees and remote branch tips after the push. Audit other branches, tags and pull-request references rather than assuming `main` is the only possible reference.

Rewritten branch history is not a guarantee of server-side erasure. Old commit URLs, cached views, forks or other people's clones may retain content. GitHub documents separate Support procedures for eligible sensitive-data removal and explains the limits of history rewriting. See [GitHub: removing sensitive data from a repository](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository). Do not claim those copies were purged without verification.

## Reproducibility boundary

A code-only clone cannot reproduce a private corpus or historical research checkpoint without separately authorized inputs. Fixture-based tests can run without those inputs:

```powershell
python -m pytest -q tests/test_review_state.py tests/test_generalized_pipeline.py tests/test_repository_privacy.py
```

The original local workspace retains the full regression suite and its private inputs. Existing historical tests, including `tests/test_publication.py`, are retained; their references to earlier distribution artifacts do not authorize publishing those artifacts now. Maintenance helpers that produce data still write private, ignored outputs.

Before any future publication, inspect all tracked files, run the applicable tests and privacy guards, and compare actual remote branch tips. Authentication success alone is not evidence that a push succeeded. Dataset publication, new collection and review annotation are separate tasks requiring their own authorization.
