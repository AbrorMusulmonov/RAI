# RAI - Uzbek real-world abuse and hate research pipeline

RAI supports collection, provenance tracking, candidate retrieval and human review of naturally occurring Uzbek-language abuse and discriminatory language.

This repository distributes **code and privacy-safe documentation**, not the research dataset. Taxonomy PDFs, full extracted definitions, source registries, real search configurations, collected comments, review decisions, Excel files, notebooks and detailed research records remain private local inputs. They are intentionally excluded from Git, including filtered or previously prepared distribution copies. Collected source links, reconstructable platform identifiers, titles and publisher names are not release material.

## Research principles

AI may assist source discovery, retrieval, ranking and audits. It must not generate, rewrite, paraphrase or automatically ACCEPT research examples. New candidates remain PENDING until human review. Source-topic relevance alone does not qualify a comment.

Candidates preserve original text, source identity, verified source URL, exact platform item ID and retrieval metadata. URL reachability and source identity verification are separate checks. A direct Content URL is recorded only when genuinely returned by the platform; otherwise the source URL plus exact item ID provides provenance.

The privately supplied `RAI_in_Full.pdf` remains the taxonomy source of truth. This release does not reproduce the document, its reference examples or the research corpus, and does not claim the dataset is complete.

## Taxonomy at a glance

The following independently worded summaries describe the 16 category scopes. They are not full annotation definitions, legal classifications, research examples or substitutes for the private boundary rules. Category names describe the targets of abuse; they do not endorse it.

| Code | Category | Short scope |
|---|---|---|
| GEN-1 | General misogyny | Degrading women or imposing subordination through patriarchal expectations. |
| GEN-2 | Marital-status policing | Devaluing women because of marriage, divorce, widowhood or childlessness. |
| GEN-3 | Modesty and appearance policing | Shaming women's clothing, appearance or public visibility through modesty expectations. |
| GEN-4 | Kelin role enforcement | Enforcing a daughter-in-law's obedience, silence or compulsory service within the household. |
| GEN-5 | Masculinity-failure attacks | Degrading men for not meeting prescribed provider, authority or masculine-role expectations. |
| REG-1 | Rural origin and internal migrants | Treating rural background or internal-migrant status as a reason for contempt or exclusion. |
| REG-2 | Region and ethnicity stereotyping | Attacking people through hostile regional or ethnic generalizations. |
| REG-3 | Language variety and loyalty | Using dialect or language choice to ridicule people or question their belonging and loyalty. |
| REG-4 | Labor migrants | Degrading Uzbek workers abroad because of migrant status. |
| STA-1 | Class and poverty | Assigning personal worth through poverty or wealth, including class-based contempt in either direction. |
| STA-2 | Profession | Degrading or excluding people because of an occupation's perceived social status. |
| STA-3 | Disability | Attacking disabled people or using disability-related language as a personal insult. |
| STA-4 | Age | Dismissing or humiliating people through age-based claims of worthlessness or incapacity. |
| STA-5 | Education and literacy | Using schooling or literacy to demean people or deny their participation. |
| REL-1 | Extremism labeling of religious practice | Stigmatizing ordinary Muslim observance by attaching extremist labels to people. |
| REL-2 | Insufficient religiosity and apostasy attacks | Condemning people over perceived lack of religious practice, secular identity, conversion or religious covering. |

Neutral discussion is not automatically abuse. Stance, target and context matter; overlapping categories require the private annotation rules and human judgment. A source's topic is never a label for every comment beneath it.

## Code layout

- `src/`: collection, retrieval, review-state, export and audit implementations.
- `scripts/`: bounded maintenance and publication checks.
- `tests/`: fixture-based regression tests and additional private-workspace integrity tests.
- `docs/`: public methodology, source-selection principles, sanitized prompt summaries and publication policy.
- `examples/config/`: empty structural templates, with no actual source or research evidence.

The runtime expects privately supplied `config/` and `data/` directories for research workflows. Obtain those inputs separately with permission; a fresh clone is not a populated research workspace. Do not commit local inputs or generated outputs.

## Public research documentation

- [Methodology](docs/methodology_public.md): evidence preservation, retrieval, quality audits and human review.
- [Source-selection strategy](docs/source_strategy_public.md): selection and verification principles, without a source list.
- [PROMPTS](docs/PROMPTS.md): newly written summaries of task patterns, not verbatim private chat history.
- [Empty configuration templates](examples/config/README.md): interfaces for privately supplied inputs; never overwrite existing configuration with them.

The original detailed documents and root-level `PROMPTS.md` remain private and unchanged. Public summaries contain no actual collected example or source address. The researcher has withheld sources over dissemination concerns; technical availability is not a redistribution permission or legal clearance.

## Development

Python 3.12 is used for validation. From the repository root:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

The following tests use self-contained fixtures and do not require the private corpus:

```powershell
python -m pytest -q tests/test_review_state.py tests/test_generalized_pipeline.py tests/test_repository_privacy.py
```

In the original private research workspace, run the full existing suite:

```powershell
python -m pytest -q
```

Historical integrity and publication-evidence tests still require private files. Their presence in the code does not mean those files are distributed. Do not regenerate baselines or skip assertions to conceal missing inputs.

`.env.example` contains empty optional API settings. Never commit credentials. Collection commands access external services and append data; run them only for an explicitly scoped collection task.

## Local human review

In the authorized research workspace, the Excel interface is at `data/exports/FINAL_HUMAN_REVIEW.xlsx`. This file is local only and is not downloadable from this repository.

Human reviewers may set PENDING, ACCEPT, REJECT, UNSURE or MOVE_TO_OTHER_CATEGORY and add notes. Do not rewrite Example or change Candidate ID. Excel edits must be merged into the canonical local `data/reviewed/*.review_queue.csv` files before regenerating workbooks. The accepted-only local export, `data/exports/data_collection.xlsx`, must never contain new PENDING candidates.

## Publication safeguards

Before committing, inspect the index and run:

```powershell
python scripts/check_private_tracking.py
python scripts/check_public_content.py
python scripts/audit_publish.py --staged
```

The path check rejects tracked private research files; the content check reads actual index bytes and rejects concrete platform links or identifiers. The credential audit is heuristic. In the original private workspace also run `python scripts/check_public_content.py --private-evidence` to compare against known source identifiers, source metadata and original comments without printing matched values. These checks do not substitute for reviewing staged content. See [publication and privacy policy](docs/github_publishing.md) for limitations.

## License

The existing [LICENSE](LICENSE) is preserved. Withheld third-party research content is not distributed or relicensed by this code release. Any future dataset transfer or release requires separate authorization and appropriate privacy, research-ethics and source-rights review.
