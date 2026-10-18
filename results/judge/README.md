# Unsupported-claims judge

The brief's metric "unsupported claims = narrative sentences not grounded in the packet", judged by
Claude Sonnet (`claude-sonnet-5-5`, effort low). Runner: `step6_evaluation/judge_claims.py`. Judging only;
the judge never produced training data.

**Two prompt versions, one folder each:**

| Folder | Prompt | Grounded in | Used in Table 1 |
|---|---|---|---|
| `eval_id/` | `judge_unsupported_claims_v2.md` | packet **+ policy v1** (`step0_rules/policy_v1.md`) | **yes** |
| `eval_id_packet_only/` | `judge_unsupported_claims.md` (v1) | packet only | no (kept for provenance) |

Why v2: v1 saw only the packet, so correct policy facts (activity thresholds, the occupation risk table, the
90-day proof-of-address window) and correctly derived risk drivers were marked unsupported. That turned the
metric into a penalty for citing the policy, not a measure of invented facts. The standard is now the information
a model is expected to decide from: the case packet plus the published policy. The 6 best-prompt baselines get
the policy in their prompt. Our students were served `student_short` (packet only) but were trained on the policy.
The 6 zero-shot baselines never saw it, so a correct policy fact from them counts as supported too: the same
standard applies to every row. The change was decided by Tianle on 2026-10-18 after reading the v1 spot-check.
It is applied identically to all runs, and no model output or label changed.

- **Scope:** `eval_id` (300 cases) for every Table 1 run with narratives: 3 frontier × {zero-shot, best},
  Qwen3.5 0.8B/2B/4B × {zero-shot, best}, final-A-s3/s4, final-B-s3/s4. The hard and OOD sets are not
  judged (cost); Table 1 shows `n/a` there.
- **Blind:** per case, the sentences of all runs are pooled, de-duplicated by text, shuffled and renamed
  S1..Sn. One call per packet. The judge never sees the producing run.
- **Denominator:** sentences from schema-valid outputs, the same ones the programmatic `evidence_refs`
  check counts (`metrics.score_case`).
- **Validation:** output checked against `step0_rules/prompts/schemas/judge_unsupported_claims.json` and
  `render.parse_judgments` (every sentence exactly once); one retry on failure. `quote_in_packet` records
  whether a "supported" verdict's quote is really in the packet (diagnostic only, it doesn't override).

Files in `eval_id/`: `verdicts.jsonl` (one row per case × unique sentence, keyed by
`(case_id, sentence_sha)`), `calls.jsonl` (tokens, cost and response ids per call), `summary.json/.md`
(per-run rates).

## Commands

The run dirs below are the `outputs/` paths used on 2026-10-18. After Session D, pass the matching
`results/runs/<run_id>` dirs instead: verdicts are keyed by sentence text, not by run name.

```bash
# full run, v2 (default --policy step0_rules/policy_v1.md; resumable; stops at --max-usd)
python -m step6_evaluation.judge_claims outputs/bench_frontier/*__eval_id outputs/bench_open/*__eval_id \
    outputs/student/final-*-s[34]__eval_id --max-usd 45
# v1 (packet only) reproduction
python -m step6_evaluation.judge_claims <same runs> --policy none --out results/judge/eval_id_packet_only

# add B-v3 later: judges only the sentences no earlier run wrote (~$1-5), same v2 prompt; other rows untouched
python -m step6_evaluation.judge_claims <path/to/B-v3__eval_id>

# Table 1 with the judge column (no API)
python -m step6_evaluation.report <runs> --config step6_evaluation/fieldmap_v1.yaml \
    --schema step0_rules/schema/v1.json --judge results/judge/eval_id/verdicts.jsonl
```

## v2 run of 2026-10-18 (packet + policy, `eval_id/`, used in Table 1)

300 calls, 3 retried once (all then valid), 0 failures, **$16.78** (policy prompt-cached: ~9.1k of ~14.5k input
tokens per call read from cache). Same 23,144 unique sentences as v1. Per-run rates: `eval_id/summary.md`.

| Run | v1 packet-only % | **v2 packet+policy %** |
|---|---:|---:|
| gpt-6-astra best / zero-shot | 7.2 / 15.1 | **7.3 / 18.2** |
| claude-opus-5-5 best / zero-shot | 8.2 / 20.5 | **8.3 / 18.5** |
| gemini-4-argon best / zero-shot | 7.6 / 21.3 | **8.8 / 22.7** |
| Qwen 0.8B best / zero-shot | 62.0 / 75.6 | **63.6 / 73.7** |
| Qwen 2B best / zero-shot | 44.2 / 64.5 | **45.9 / 64.2** |
| Qwen 4B best / zero-shot | 47.8 / 53.0 | **53.1 / 59.7** |
| final-A s3 / s4 | 14.4 / 14.4 | **15.4 / 14.9** |
| final-B s3 / s4 | 13.0 / 13.2 | **13.3 / 14.2** |

**What changed between versions:** the verdicts agree on 87.9% of sentences. 1,244 flipped unsupported → supported
(correct policy facts: thresholds, Table A occupations, the 90-day window, derived drivers). 1,554 flipped
supported → unsupported: with the policy in hand the judge also catches *misapplied* policy (a wrong tier, a driver
the policy doesn't fire, "civil servant is high-risk" when Table A says low). The two effects roughly cancel, so the
ranking and the gap (finals ~14-15% vs frontier best-prompt ~7-9%) do not depend on the prompt version.

**Judge noise:** 2.5% of v2 "unsupported" verdicts (203 of 8,224; v1: 1.0%) carry a reason that talks itself back
into "fine / supported actually". They're left as is (no post-hoc edits to verdicts); at most ~0.4 points on any rate.
93.5% of "supported" quotes are verbatim in the packet (the rest are mostly policy quotes, which v2 allows).

### Hand spot-check, v2 (10 verdicts: random seed 7 over the v1 file, 5 v1-supported, 5 v1-unsupported)

| Case | v2 | Sentence (short) | Hand |
|---|---|---|---|
| …105 | supported | approval rests on consistent identity + sole hit false positive | agree |
| …048 | supported | bank statement 2026-03-24 matches address, within 90 days (as-of 2026-05-04) | agree |
| …129 | supported | medium risk from possible alteration; cross-border (ARE national, lives in Jaipur) | agree |
| …210 | supported | passport unexpired as of 2026-04-09 | agree |
| …016 | supported | H1, H2 false positives on DOB (1966, 1991 vs 1971), nationality matches | agree (H3 is the true match) |
| …021 | unsupported | doc number L12364499 "conflicts" with the identical L12364499 | agree |
| …256 | unsupported | civil servant "is a high-risk occupation" | agree (Table A: low) |
| …166 | unsupported | applicant "flagged as a PEP", position "in Germany" | agree (hit is a false positive; position is domestic) |
| …028 | unsupported | expiry "consistent with the application form" | agree (application has no expiry) |
| …115 | unsupported | restaurant owner adds "cash-intensive-business risk" | agree (no such driver in policy) |

Agreement 10/10. The two v1 errors from the v1 spot-check below (…007 tampering-absence and …078 high-risk
occupation) were both policy/derivation cases, the kind v2 was meant to fix.

## v1 run of 2026-10-18 (packet only, `eval_id_packet_only/`)

300 calls, 0 retries, 0 failures, **$16.42** (Sonnet list price, sync API). 23,144 unique sentences
(29,004 across the 16 runs). 99.8% of "supported" quotes are verbatim in the packet. Per-run rates: `eval_id/summary.md`.

### Hand spot-check (10 verdicts: 5 supported, 5 unsupported, random seed 7)

| Case | Judge | Sentence (short) | Hand | Note |
|---|---|---|---|---|
| …051 | supported | mobile bill 24 APR 2026 within 90 days | agree | as-of 17 Jul 2026, 84 days |
| …023 | supported | tenancy agreement within 90-day window | agree | 07.03 vs as-of 17.03 |
| …062 | supported | passport expired 2026-02-08 | agree | |
| …008 | supported | H1 false positive (name, DOB 1982 vs 2004, MYS vs FRA) | agree | every value checks |
| …011 | supported | H2 true match (name, age 44 in 2018, Dubai, civil servant) | agree | |
| …013 | unsupported | POA matches the address "on the passport" | agree | passport has no address |
| …057 | unsupported | "risk is low (no risk drivers)" | agree | MRZ doc-number check digit fails (7 vs 4) |
| …032 | unsupported | passport consistent with application | agree | GUO FENG vs Liu Feng |
| …007 | unsupported | "no tampering or inconsistencies detected" | **disagree** | all fields consistent; conclusion follows |
| …078 | unsupported | "medium (address unverified, high risk occupation, cross border)" | **disagree** | correct per policy Table A; judge has no policy |

Agreement 8/10 (5/5 supported, 3/5 unsupported). **Known bias:** the judge sees the packet only, not
`step0_rules/policy_v1.md`, so policy facts (activity thresholds, the high-risk occupation table, the 90-day
POA window) are often marked unsupported. 66% of final-B-s4's unsupported sentences and 57% of Argon-best's
mention risk/actions/decision. The rate is an upper bound on hallucination and penalizes narratives that cite
policy (our students do this more than the frontier baselines).
