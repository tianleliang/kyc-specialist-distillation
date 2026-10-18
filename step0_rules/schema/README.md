# schema

| File | What |
|---|---|
| `v1.json` | **The published output schema** (v1.0, Tianle's D1–D3): flat, enum reason codes per identity field, one item per screening hit echoing `hit_id`, section-enum `evidence_refs` + `hit_ids` per narrative sentence, 4–8 sentences. Every property required, closed objects, no `$ref`. This is what outputs are scored against. |
| `v1_serving.json` | `v1.json` + `maxLength` on free-text strings and `maxItems` on open arrays, so grammar-constrained decoding can't loop (Session B). Only adds constraints: valid here ⇒ valid under `v1.json` (`tests/l_schema_v1_test.py`). Used by the proxy. |
| `build_v1.py` | The single source of every code list and its one-line meaning. `python -m step0_rules.schema.build_v1` rewrites both files; `--check` fails if they're stale. **Edit codes here, never in the JSON.** |
| `v0_provisional.json` | Legacy overnight placeholder. Only `data/draft/` (frozen v0 fixtures for older tests) uses it. |

The policy that assigns every value is `step0_rules/policy_v1.md`; the code that applies it is `step1_data_generation/project.py`.

Lint: `python -m shared.frontier_api.schema_check step0_rules/schema/v1.json` (0 errors; warnings only for `minItems`/`maxItems`, which every provider we use accepts but should be checked live).
