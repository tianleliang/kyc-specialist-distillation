# Overnight report: Session C (evaluation metrics)

Branch: `claude/wonderful-archimedes-on7j73`. The environment forced this branch name, so it can't be `overnight-c`.

## Done

### `step6_evaluation/metrics.py`: schema-agnostic scoring
Driven by a `FieldMap` config (YAML/JSON, unknown keys rejected). The config says where each quantity lives, using dotted paths with `[i]` and `[key=value]` selectors (e.g. `identity.findings[field=dob].status`). The real schema needs a new FieldMap only, not code changes.

| Brief metric | Key(s) | Notes |
|---|---|---|
| Decision accuracy + confusion matrix | `decision_accuracy`, `confusion_matrix()` | the matrix has `(absent)` / `(invalid)` / `(other)` columns |
| Screening macro-F1 | `screening_macro_f1` (+ `screening_accuracy`) | hits joined by id (`screening_id_key`), or by position if `null`; classes absent from both gold and prediction are excluded |
| Per-identity-field accuracy | `field_accuracy.<name>`, `field_accuracy_mean` | any number of fields, incl. `verified` |
| Risk tier exact / within one | `risk_exact`, `risk_within_one` | ordered labels from config |
| Required actions recall (+ precision) | `actions_recall`, `actions_precision` | micro-pooled over cases; list of codes or of objects (`actions_item_key`) |
| Schema validity | `schema_validity` | JSON Schema (any draft, via `validator_for`); strict parse by default, `strip_code_fences` optional |
| Adversarial escalation | `adv_escalation_rate[.<subset>]` (+ `adv_decision_accuracy`) | subsets = gold tags from config; the union is not double-counted |
| Latency p50/p95, cost per 1k | `latency_p50_ms`, `latency_p95_ms`, `cost_per_1k_usd` | per-token prices or GPU $/h × latency ÷ concurrency; batch multiplier; accepts OpenAI `prompt_tokens`/`completion_tokens` |
| Unsupported claims (scaffold) | `unsupported_rate` | `ClaimChecker` protocol plus a programmatic `EvidenceRefChecker` (refs must be known packet IDs or verbatim packet spans). No LLM judge yet |

**Scoring rule:** the gold file is the denominator. A missing, unparseable or schema-invalid prediction scores zero on every quality metric; it is never dropped. A value missing from a valid output counts as wrong. A value missing from gold drops that case from that one metric only.

### `step6_evaluation/report.py`: one command, no API calls
`python -m step6_evaluation.report outputs/` scans for `*/predictions.jsonl` plus an optional `run.json`, and emits:
- **Table 1:** models × metrics with case counts, 95% bootstrap CIs (case resampling, seeded), p50/p95 and $/1k
- **Table 1b:** per-field accuracy, adversarial subsets with n, hit, sentence and missing-prediction counts
- **Table 2:** stage deltas per `pipeline`, ordered by `stage_order` (or an explicit `compare_to`), with **paired** bootstrap CIs on the shared case ids
- Decision confusion matrices, the gold-file sha256 in the header, and data warnings (missing, duplicate or unknown case ids)

Options: `--config` (FieldMap), `--schema`, `--gold`, `--prices`, `--n-boot`, `--seed`, `--out`, `--json`. Output is deterministic: identical inputs give byte-identical markdown.

### Phase 2: harness check, on Session A's real draft data
- `tests/c_fakes.py` has 6 schema-driven fakes: oracle, random, always_escalate, broken_json, corrupted (p = 0.2) and hallucinated_refs. They walk the JSON Schema (including `$ref`/`$defs`), so they work on any schema.
- A's `step0_rules/schema/v0_provisional.json` and `data/draft/` appeared on `origin/claude/zorbe-kyc-overnight-a-2zfyja` at the 2nd poll (commit `c0f4b28`). I copied them **read-only** into a scratch dir with `git archive`. A's branch was not merged, and none of A's files are in this branch.
- **On A's 200 draft cases:** the oracle scores 100% on every quality metric with 0.0% unsupported claims (1,224 sentences). Broken JSON scores 0%. always_escalate scores 51.0% (= 102/200 gold escalates). random scores ~1/3 on 3-way labels; corrupted ~80%; hallucinated_refs 51% unsupported. All as expected. The only adaptation was a FieldMap YAML (`tests/fixtures/c_fieldmap_v0_provisional.yaml`) plus one generic option, `packet_ref_id_regex`, which reads valid section ids (CTX/APP/…/H1) from the packet. Without that option the oracle showed 31.3% unsupported claims. That would have been a harness bug, and the oracle-must-be-100 rule caught it.
- The same fakes on C's 60-case stand-in fixture also behave as expected.
- Full tables and commentary: `documentation/05_progress_reports/overnight-C-harness-check.md`.
- Side-checks of A's data that came out of this: all 200 `expected` outputs validate against A's schema, and every gold evidence ref resolves to a packet section.

## Not done / blocked
- Nothing from the task list is blocked.
- An LLM judge for unsupported claims. Only the interface exists; building the judge waits on the schema and judge-model decisions.

## Test results
`python -m pytest tests/c_metrics_test.py tests/c_report_test.py`: **36 passed, 1 skipped**. The skipped test, `test_fakes_on_session_a_draft`, runs automatically once A's `data/draft/` and `step0_rules/schema/v0_provisional.json` are on the branch; it passed when run against a temporary copy. Runtime is about 2 s. The full `python -m pytest tests/` on this branch gives the same result.

## Problems / notes
- `pytest.ini` doesn't set `python_files`, so pytest's default `test_*.py` / `*_test.py` applies. `tests/c_*.py` files are only collected if they end in `_test.py`. Mine are named `c_metrics_test.py` and `c_report_test.py`. Any `tests/<letter>_foo.py` file that doesn't end in `_test.py` is silently not collected (A's files follow the `_test.py` pattern).
- Prices in `DEFAULT_PRICES` are copied from `documentation/00_case_brief_and_plan/05` (agent-reported). Verify them before reporting. Override with `--prices prices.yaml`.
- The prediction record format (`case_id`, `output`, `latency_ms`, `usage`) is defined here. Session B's `step6_evaluation/run_open_models.py` should write it, or Tianle can pick a different shape; the key names are configurable on the FieldMap.

## Questions for Tianle
1. **Escalation as the "right answer" on adversarial cases.** The brief's metric is an escalation *rate*. If a packet has an injected instruction *and* a clear true sanctions match, is the correct decision `reject` or `escalate`? The harness reports both the rate and the decision accuracy on the subset; which one goes in Table 1?
2. **Lenient parsing.** Should outputs wrapped in ```` ```json ```` fences count as valid? Default: no (strict). Frontier models in structured-output mode won't produce fences, but open baselines without constrained decoding might.
3. **Hit join key.** Should the schema echo a hit id per screening disposition (recommended for scoring), or should hits be matched by position?
4. **Unsupported claims.** What should an `evidence_ref` be: packet field IDs (precise, needs IDs in the packet), verbatim spans (works on any packet, including Zorbe's hidden set), or both? The checker supports all three.
5. **Macro-F1 convention.** Classes absent from both gold and prediction are excluded (so a perfect model scores 100 on a subset missing a class). Should we use that, or sklearn's default of counting them as 0?
6. **Field accuracy headline.** Table 1 shows the mean over fields (including `verified`) and Table 1b shows each field. Should `verified` be counted in the mean?
