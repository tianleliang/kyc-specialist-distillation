# Progress reports

These are the reports that each build session wrote when it finished, listed in session order (overnight wave 1, overnight wave 2, then lunch).

Notes:
- Order inside a wave follows the session letter. The sessions in a wave ran in parallel, so the letter does not tell you which one finished first.
- Only one report gives a calendar date. The time windows in the "session" column come from the matching instruction file in [../06_agent_instructions](../06_agent_instructions/README.md).
- There are no reports here for the Saturday-evening and Sunday sessions (4B training, final runs, reader v3, the B2 retrain). Their results are in [../04_results/findings_log.md](../04_results/findings_log.md) (sections 5b and 5c) and in the instruction files themselves.

| File | Session | Date if stated | What it did | Key result |
|---|---|---|---|---|
| [overnight-A.md](overnight-A.md) | Wave 1, Session A (Fri 10/16 night to Sat 07:00 ET) | Not stated (questions are for 07:45) | KYC building blocks (MRZ, names, matching, addresses, OCR and tamper noise, watchlists) and a PROVISIONAL draft generator | 97 tests pass; 200 draft cases, approve 72 / escalate 102 / reject 26; corpus download blocked (403) |
| [overnight-A-samples.md](overnight-A-samples.md) | Wave 1, Session A (companion file) | Not stated (draft seed 20261017) | 10 draft cases, one per difficulty type, with packet, expected v0 output and hidden truth, for review | 10 cases across 4 layout styles; review aid only, no metrics |
| [overnight-B.md](overnight-B.md) | Wave 1, Session B (laptop) | Sat 2026-10-17 | Serving smoke test: vLLM on a Modal L4 with Qwen3.5-0.8B, proxy, auth, schema check, and a train, merge, serve rehearsal | All checks pass; cold start 288 s; warm p50/p95 367/377 ms; rehearsal 6/6 outputs differ from base; cost $1.33 |
| [overnight-C.md](overnight-C.md) | Wave 1, Session C | Not stated | Schema-agnostic eval metrics (`metrics.py`) and the one-command report (`report.py`) | 36 tests pass, 1 skipped; on A's 200 drafts the oracle scores 100% and broken JSON 0% |
| [overnight-C-harness-check.md](overnight-C-harness-check.md) | Wave 1, Session C (companion file) | Not stated | Full harness check with 6 fake models on A's drafts and on a 60-case stand-in fixture | All fakes score as expected (always-escalate 51.0%, corrupted about 80%); no harness bugs in the final run |
| [overnight-D.md](overnight-D.md) | Wave 1, Session D | Not stated | Research writing: KYC primer, draft decision policy, 3 schema options, distillation options | 12 tests pass; 27 flagged policy questions; 4 invented technique candidates |
| [overnight-E.md](overnight-E.md) | Wave 1, Session E | Not stated | Design writing: decision memos, data design, contamination protocol, experiment plan | 6 memos; proposed a 150-case dev set; found 7 gaps in the plan |
| [overnight-F.md](overnight-F.md) | Wave 1, Session F | Not stated | Frontier API client, batch runner, SFT/DPO/merge Modal jobs, eval freeze and overlap guard (mocks only) | 70 tests pass; CPU smoke SFT loss 6.22 to 5.25; overlap check runs 5,000 x 450 in about 3.4 s |
| [overnight-G.md](overnight-G.md) | Wave 1, Session G | Not stated | Write-up skeleton with placeholders, a linter, and a stages 7-9 draft | 9 tests pass; 224 placeholders, 0 unregistered |
| [overnight-H.md](overnight-H.md) | Wave 2, Session H (Sat 10/17, 01:00 to 07:00 ET) | Not stated (findings are for 07:45) | Decision sheet: about 50 wave-1 questions merged into 20 decisions, a reconciled policy candidate, a morning brief | 20 decisions; full suite 220 pass, 3 skipped, 1 fail (missing `openai` module) |
| [overnight-I.md](overnight-I.md) | Wave 2, Session I | Not stated | Prompt templates, the OpenAI-compatible serving proxy, the endpoint runner, Windows encoding fixes | 274 pass, 3 skipped; live-socket smoke on 20 cases scores 100% with 0 fallbacks |
| [overnight-J.md](overnight-J.md) | Wave 2, Session J | Not stated | Generator v1: as-of date, knob vector, split configs with disjoint entities, plausibility rules, twins and knockouts | 283 pass, 3 skipped, 1 fail (pre-existing); 0 overlap between train/dev and eval |
| [overnight-K.md](overnight-K.md) | Wave 2, Session K | Not stated | Distillation data steps: SFT floor, rejection sampling, arbitration, hard-case mining, DPO pairs, on-policy loop | 28 tests pass; full suite 247 pass, 3 skipped, 1 fail (pre-existing) |
| [lunch-L.md](lunch-L.md) | Lunch, Session L (Sat 10/17, about 13:00 to 14:15 ET) | Not stated | Turned the decisions into schema v1, policy v1, v1 labels and all datasets | 392 pass, 1 skipped; independent re-labelling matches 600/600; train mix 38.0 / 47.3 / 14.7% |
| [lunch-L-harness-v1.md](lunch-L-harness-v1.md) | Lunch, Session L (companion file) | Not stated | Harness check with fake models on schema v1 (dev 150, train 3,000) | Oracle 100% on every metric, broken JSON 0%; always-escalate 55.3% on dev, 47.3% on train |
| [brief_compliance.md](brief_compliance.md) | Lunch, Session L (companion file) | Not stated | Audit with one row per input, output value, hard case and metric in the brief, with counts per split | Every hard-case item is at least 4.6% of train; 16 finer cuts flagged THIN (under 3%) |
| [lunch-M.md](lunch-M.md) | Lunch, Session M | Not stated | 50 hand-written OOD packets in 6 new styles, the LLM OOD writer, and the domain adapter code | 411 pass, 0 skipped; adapter CPU smoke perplexity 602.2 to 537.5 (plumbing only) |
| [v1_data_samples.md](v1_data_samples.md) | No session named; written after lunch (it includes the hand OOD set) | Not stated | One example case per data pile, with packet and correct answer | 7 piles shown (train, dev, eval_id, eval_ood_template, eval_ood_hand, train_twins, train_knockout) |
