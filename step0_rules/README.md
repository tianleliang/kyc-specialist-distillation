# step0_rules — output schema, decision policy and prompt templates (setup, used by every stage of the brief)

## What it does
- Defines the answer format every model must return: `schema/v1.json` (scored) and `schema/v1_serving.json` (same schema plus length caps, for grammar-constrained decoding).
- Writes down the decision policy behind every label: `policy_v1.md` (dates, identity, OCR-vs-tamper integrity, screening, risk tier, actions, decision precedence, narrative). The code that applies it is `step1_data_generation/project.py`; the two must agree.
- Holds every prompt sent to any model (baselines, teachers, the student, the judge, the OOD renderer) as templates, plus `prompts/render.py` to fill them.
- Pure Python. No API, no GPU.

## Key files
| File | What it is |
|---|---|
| `policy_v1.md` | KYC adjudication policy v1: dates, identity findings, screening, integrity classes, risk, actions, rule precedence |
| `schema/build_v1.py` | Single source of every enum code and its meaning. Rewrites both schema files; `--check` fails if they are stale |
| `schema/v1.json` | Published output schema v1.0. Outputs are scored against it |
| `schema/v1_serving.json` | `v1.json` + `maxLength` / `maxItems`, so constrained decoding cannot loop. Used by the proxy and open-model benchmark |
| `schema/v0_provisional.json` | Legacy placeholder; only the frozen v0 fixtures in `data/draft/` use it |
| `prompts/render.py` | `PromptBuilder`, `load_examples` (refuses eval pools), judge helpers, provenance hashes, small CLI |
| `prompts/student_short.md` | Production prompt for the trained specialist (decision D21b). Used in final SFT records and by the proxy |
| `prompts/baseline_zero_shot.md`, `prompts/baseline_best.md` | Stage 1 baseline prompts (schema only / policy + field guide + 2 examples) |
| `prompts/teacher.md` | Teacher prompt for distillation (best prompt + complete `evidence_refs`) |
| `prompts/judge_unsupported_claims_v2.md` | Blind LLM judge for the unsupported-claims metric (v1 also kept); output schema in `prompts/schemas/` |

## How to use
```bash
python -m step0_rules.schema.build_v1 --check                          # are v1.json / v1_serving.json up to date?
python -m step0_rules.schema.build_v1                                  # rewrite both after editing codes in build_v1.py
python -m shared.frontier_api.schema_check step0_rules/schema/v1.json   # lint for OpenAI / Anthropic / Gemini structured output
```
Eyeball a rendered prompt (no API call):
```bash
python -m step0_rules.prompts.render student_short --packet-file packet.txt
python -m step0_rules.prompts.render baseline_best --schema step0_rules/schema/v1.json \
    --policy step0_rules/policy_v1.md --pool data/train/cases.jsonl --packet-file packet.txt
python -m step0_rules.prompts.render teacher --schema step0_rules/schema/v1.json \
    --policy step0_rules/policy_v1.md --pool data/train/cases.jsonl --hashes   # provenance hashes only
```
The judge and OOD-renderer templates are rendered from Python only (`render_judge`, `render_ood`).

From Python:
```python
from step0_rules.prompts.render import PromptBuilder
pb = PromptBuilder("baseline_best", schema="step0_rules/schema/v1.json", policy="step0_rules/policy_v1.md")
messages = pb.messages(packet)   # [{system}, {user}]
pb.provenance()                  # template / policy / schema / few-shot hashes for run.json
```
Tests: `python -m pytest -q tests/i_prompts_test.py tests/l_schema_v1_test.py`

## Outputs / where results live
- This folder is an input, not a run. Its files are hashed into every run's metadata (`run.json` / `endpoint_run.json` under `results/runs/<run>/`).
- The serving proxy reads `prompts/student_short.md` and `schema/v1_serving.json` (see `step7_serving/proxy_config.example.yaml`).

## Reports and evidence
- [lunch-L.md](../documentation/05_progress_reports/lunch-L.md): schema v1, policy v1, v1 labels; an independent re-labelling from the policy alone matched on 600/600 cases.
- [lunch-L-harness-v1.md](../documentation/05_progress_reports/lunch-L-harness-v1.md): harness check on schema v1 with fake models.
- [overnight-I.md](../documentation/05_progress_reports/overnight-I.md): prompt templates and `render.py`.
- [overnight-D.md](../documentation/05_progress_reports/overnight-D.md) and [overnight-H.md](../documentation/05_progress_reports/overnight-H.md): schema options, draft policy, decision sheet that led to v1.
- [LUNCH.md](../documentation/06_agent_instructions/LUNCH.md): decisions D1–D16 the schema and policy implement.
- [decision_log.md](../documentation/01_decisions/decision_log.md): why each schema and policy choice was made.
- [findings_log.md](../documentation/04_results/findings_log.md) §1: data, labels and the rulebook.
- Sub-READMEs: [schema/README.md](schema/README.md), [prompts/README.md](prompts/README.md).

## Details
**Template format.** YAML front matter (`name`, `description`, `variables`), then `@@system` and `@@user` parts. Only declared `{name}` placeholders are substituted, in one pass, so JSON braces are safe and a packet containing `{schema}` stays literal. No schema or policy is hardcoded: both are files passed at render time. `--policy module:<dotted.module>` uses that module's docstring.

**Which prompt is used where.**
| Template | Used for |
|---|---|
| `student_short.md` | trained specialist: final SFT records and serving (policy and schema learned in training; serving grammar enforces the shape) |
| `student.md` | long student prompt (policy + schema + packet). Still the proxy's code default (`template: str = "student"`), but the production config sets `student_short` |
| `baseline_zero_shot.md` / `baseline_best.md` | stage 1 rows, identical text for frontier and open models |
| `teacher.md` | teacher calls in stage 3 |
| `judge_unsupported_claims.md` / `_v2.md` | unsupported-claims judge; v2 adds policy v1 in the system part (prompt caching) |
| `ood_renderer.md` | eval-only: a frontier model writes a packet in a novel style from a truth object |

**Contamination rules built in.** `load_examples` refuses any pool under an `eval*` directory and, for teacher prompts, under `draft`. With `eval_manifests`, each picked example is checked against the frozen eval set with `step6_evaluation.split_guard.EvalGuard`. `ood_renderer` and its outputs are eval-only.

**Judge bias controls.** `render_judge` pools sentences from every model under neutral IDs (`S1..Sn`) in a seeded random order; the judge never sees model names or case ids. `parse_judgments` raises if the judge skips, duplicates or invents an ID. `quote_in_packet` checks a "supported" verdict's quote in code.

**Schema lint.** `schema_check` reports 0 errors on `v1.json`; warnings only for `minItems` / `maxItems`. Anthropic structured output rejects some bounds, so `step2_benchmarking/run_frontier.py` sends Anthropic a relaxed copy; every prediction is still scored against full `v1.json`.
