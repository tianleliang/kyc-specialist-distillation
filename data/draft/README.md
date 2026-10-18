# data/draft: DRAFT cases (PROVISIONAL, legacy v0)

> **Legacy.** Since Session L the generator emits schema v1 (`step0_rules/schema/v1.json`); these 200 v0 cases are kept only as frozen fixtures for older tests (distillation and harness unit tests). `build_draft.py` now writes v1, so it no longer reproduces these files.


> **DRAFT. This is not an eval set. Do not use it for training.**
> These cases come from the overnight PROVISIONAL generator. They exist only to test the pipeline end to end: harness, metrics, prompts and serving.
> The schema (`schema/v0_provisional.json`) and the decision policy (comments at the top of `gen/project.py`) are placeholders. Tianle sets the real ones.
> Real eval sets come from separate generator configs, seeds and prompts, and are hashed and frozen. Nothing here may feed training or teacher prompts.

## Regenerate
```
python -m gen.build_draft            # n=200, seed=20261017 -> data/draft/
```
The output is deterministic. `manifest.json` records the sha256 of each file, and a rerun must reproduce those hashes.

## Files
| file | contents |
|---|---|
| `cases.jsonl` | `{case_id, schema, style, scenarios, packet, expected}`: the packet text a model sees, and the expected output under `v0_provisional` |
| `truth.jsonl` | `{case_id, truth}`: the hidden latent facts (`gen/truth.py`). Never show these to a model |
| `manifest.json` | seed, generator version, scenario/decision/tier/style counts, file hashes |

`scenarios[0]` is the case's primary difficulty item; an optional second entry is a stackable secondary. `style` is the packet layout (`kv`, `form`, `prose`, `mixed`).
Narrative `evidence_refs` cite packet section ids: `CTX`, `APP`, `ID`, `MRZ`, `POA`, `SCR`, `H1`..`Hn`.
