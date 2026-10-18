# prompts

Prompt templates, parameterized by `{schema}`, `{policy}` and `{packet}`. **No schema or policy is hardcoded**: both are files passed in at render time (`tests/i_prompts_test.py` fails if a case template names any v0 schema token).

| Template | Used for | Variables |
|---|---|---|
| `student.md` | the long student prompt (early experiments) | policy, schema, packet |
| `student_short.md` | **the student prompt actually used** for training, evaluation and serving (613 characters; the proxy injects it when a caller sends a bare packet) | packet |
| `baseline_zero_shot.md` | Stage 1 zero-shot rows: task description + schema only | schema, packet |
| `baseline_best.md` | Stage 1 "best prompt" rows: policy + field guide + 2 few-shot examples | policy, schema, field_guide, examples, packet |
| `teacher.md` | teacher calls for distillation: best prompt + complete `evidence_refs` | policy, schema, field_guide, examples, packet |
| `judge_unsupported_claims.md` | LLM judge for the unsupported-claims metric, v1: packet only (output schema: `schemas/judge_unsupported_claims.json`) | packet, sentences, output_schema |
| `judge_unsupported_claims_v2.md` | v2 judge (used for Table 1): packet **and** policy v1, policy in the system part for prompt caching | policy, packet, sentences, output_schema |
| `ood_renderer.md` | **eval-only** generator: a frontier model writes a packet in a novel style from a truth object | truth, style, required_strings |

## Format
YAML front matter (`name`, `description`, `variables`), then `@@system` and `@@user` parts. Only declared `{name}` placeholders are substituted, in a single pass, so JSON braces are safe and a packet containing `{schema}` stays literal. Unused or undeclared placeholders are load errors.

## Usage
```python
from step0_rules.prompts.render import PromptBuilder, load_examples
ex = load_examples("data/dev/cases.jsonl", k=2, seed=0, purpose="teacher",
                   eval_manifests=["data/eval_id/manifest.json"])
pb = PromptBuilder("teacher", schema="step0_rules/schema/v1.json", policy="step0_rules/policy_v1.md", examples=ex)
messages = pb.messages(packet)          # OpenAI-style [{system}, {user}]
pb.provenance()                         # hashes for run.json (template, system, policy, schema, few-shot ids)
```
The policy is `step0_rules/policy_v1.md` (the published v1 policy); the schema is `step0_rules/schema/v1.json` (or `v1_serving.json` where decoding is grammar-constrained, e.g. the proxy). `--policy module:<dotted.module>` still works and uses that module's docstring.

Eyeball a prompt: `python -m step0_rules.prompts.render student --schema step0_rules/schema/v1.json --policy step0_rules/policy_v1.md --packet-file x.txt`

## Contamination rules built in
- `load_examples` refuses any pool under an `eval*` directory, and for `purpose="teacher"` also `draft` (`data/draft/README.md`: nothing there may feed teacher prompts). With `eval_manifests`, every picked example is checked against the frozen eval set with `step6_evaluation/split_guard.EvalGuard`.
- `ood_renderer` and its outputs are eval-only. Never reuse them for training or teacher data. After rendering, run `check_ood_packet(packet, required_strings)` and drop any packet where the frontier model "fixed" a deliberate error, because its gold label may no longer hold.

## Judge bias controls
`render_judge(packet, [(hidden_key, sentence), ...], seed)` pools sentences from every model under neutral IDs (`S1..Sn`) in a seeded random order; the judge never sees model names or case ids. `parse_judgments` maps verdicts back and raises if the judge skipped, duplicated or invented an ID. `quote_in_packet` double-checks a "supported" verdict's quote programmatically.
