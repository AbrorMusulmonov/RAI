# Empty private-configuration templates

These files demonstrate configuration structure only. They contain no real source, URL, item ID, collected text, observed query phrase, full taxonomy definition or accepted example. They are not runnable research settings and do not represent a populated dataset.

Keep this directory unchanged as a public reference. In a new authorized private workspace, create the corresponding files under ignored `config/` only if those destination files do not already exist. Never overwrite the existing project's configuration with these empty templates. No setup command in this directory copies files or starts collection automatically.

- `sources.example.json`: an empty source registry. Register and verify authorized sources privately; do not put a sample live source here.
- `taxonomy.example.json`: an empty taxonomy container and an unpopulated category-field template. The full private taxonomy must be supplied separately. README category summaries are not annotation definitions.
- `search_terms.example.json`: empty GEN-1 and generalized-category retrieval field templates. Their different interfaces reflect the existing processors. Empty arrays are intentional and cannot provide useful retrieval.
- `source_dispositions.example.json`: the format for private source-specific maintenance decisions. The private counterpart is `config/source_dispositions.private.json`.
- `remaining_retrieval.example.json`: empty containers for private observed-language specifications and source-quality vocabulary used by the maintenance helper. The private counterpart is `config/remaining_retrieval.private.json`; no category specifications are distributed.

The `category_template`, `gen1_category_template` and `general_category_template` keys are explanatory templates, not active runtime entries. Populate the private `subcategories` / `categories` containers after reviewing the code and the authorized taxonomy. Required verification and review decisions must never be fabricated to make a template run.

Do not force-add private files. Before publishing code or documentation changes, run the repository's path and content privacy checks. The private-evidence check additionally needs the original private corpus; a public clone cannot perform that comparison on its own.
