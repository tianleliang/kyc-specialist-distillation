# Overnight report: Session H (wave 2, decision sheet)

Branch: `claude/clever-keller-rutk8i`. The cloud environment assigned this name, so it doesn't contain the letter H; the PR title and commits say "Session H". Writing only: every file is under `documentation/01_decisions/`, plus this report. No code, no API calls, and nothing outside H's ownership was edited.

## Done
| # | Deliverable | File | Notes |
|---|---|---|---|
| 1 | Decision sheet | `documentation/01_decisions/decision_sheet.md` | About 50 distinct wave-1 questions (A, C, D incl. its `Q-xx` index, E incl. memos and open questions, F, G) **deduplicated into 20 decisions**, ordered schema → policy → data → models → techniques → serving/repo. Each has an options table with a **code change if chosen** column (exact file and function or config key on `main`; wave-2 I/J/K files marked as such), a one-line recommendation with its reason, what it unblocks, and a deadline. The index separates the **07:45** decisions (1–6, 13 sizes, 16, 17, 20 Modal + proxy) from the ones that can wait, each with its deadline (e.g. invented technique by 15:00). It ends with a **27-row A vs D vs E side-by-side table** of every place the three policies disagree, plus the points where all three agree, and an appendix of small defaults |
| 2 | Reconciled policy | `documentation/01_decisions/policy_v1_candidate.md` | One policy taking the recommended option at every fork, each fork marked `[DEFAULT, pending Tianle: D#]`. Sections: reference date, identity findings, OCR vs tamper, screening, risk tier, 12 actions (with the A → v1 rename map), 10-step precedence, narrative, output enums, **a §10 checklist of the exact `step1_data_generation/project.py` edits**, and a ~330-word prompt version for I's `{policy}` slot |
| 3 | Morning brief | `documentation/01_decisions/morning_brief.md` | ~1 page: what exists after wave 1, what wave 2 is building, what's still missing, the first three things to run, and the hard clock items |

## Findings worth reading before 07:45
1. **The recommended policy shifts the class mix.** On A's 200 drafts, 14 of the 26 rejects are tamper cases. With tamper → escalate (decision 4, recommended by D and E), the mix becomes 36% / 58% / 6% and always-escalate scores 58%. Decision 13 proposes rebalancing the generator mix to about 38 / 47 / 15.
2. **A's Problem 1 is large:** 142 of 200 drafts carry the render-time `poa_address_format_variant` code. The candidate collapses it to a single code.
3. **Serving is the biggest gap.** Session B was laptop-only and none of its files (`step7_serving/modal_vllm.py`, `step7_serving/smoke.py`, `step6_evaluation/run_open_models.py`) are on `main`, so R0 depends on the laptop.
4. **A's v0 schema uses `$defs`/`$ref`**, which `05` and D's constraints warn against for small models. Decision 1 recommends D's flat option B.
5. E's (Jaccard 0.8 / 13-gram) and F's (0.7 / 8-gram containment 0.5) overlap thresholds differ. The sheet recommends F's, since they're implemented and stricter.
6. `00 Deliverables` §G says the weights link must work "without our login", while E recommends a private HF repo + token. The sheet flags this (decision 20).

## Not done
- Nothing from H's task list is undone.
- Sessions I, J and K hadn't pushed when this was written, so their file and config names are taken from `documentation/06_agent_instructions/OVERNIGHT2.md` and marked *(I)*, *(J)*, *(K)*. Check the exact keys on their branches.

## Test results
Writing-only session, so no H tests. For the brief I ran `python -m pytest -q` on this branch (identical code to `main`): **220 passed, 3 skipped, 1 failed**. The failure is `tests/f_llm_clients_test.py::test_missing_key_errors_cleanly`, caused by `No module named 'openai'` in this container. That test is in Session I's fix list.

## Problems
- None blocking. The draft-mix numbers were computed from `data/draft/cases.jsonl` with a throwaway script, not saved; they're reproducible in one pass over the file's `expected` fields.

## Questions for Tianle
All of them are in `decision_sheet.md`. The ones that block the most: decisions **1 (schema), 4 (what rejects), 6 (OCR vs tamper), 16 (base model), 17 (panel)**, and **19 (invented technique) by 15:00**.
