# Overnight report: Session G (write-up scaffolding)

Branch: `claude/gifted-gauss-u9egco`. The environment assigned this name, and the session's rules forbid pushing to any other branch, so it doesn't contain the letter "G" as `documentation/06_agent_instructions/OVERNIGHT.md` asks. The PR title says "Session G" to make up for it.

## Done
1. **`documentation/04_results/writeup_skeleton.md`**: the 4-page structure, following the brief's required contents.
   - A map from each brief requirement to its section and the scoring weight it supports.
   - A page and word budget: 2,150 body words plus 4 compact tables, with each section's budget tagged inline as `[N words]` and an explicit cut order (§4 contamination and §5 what failed are never cut, since together they carry 30 points).
   - Sections: §1 result plus a Table 1 excerpt (ID and OOD side by side); §2 choices (step0_rules/schema/policy, generator, base model + **license line**, training/serving); §3 distillation pipeline, the **invented technique**, and a Table 2 excerpt with Δ columns; §4 contamination controls written as defensible claims; §5 what failed; §6 stages 7–9; §7 **models-used table, spend table, coding assistants, ToS line**; §8 what we cut.
   - Every number and choice is a `{{PLACEHOLDER}}` (224 distinct). No model, technique or policy is filled in.
   - A **placeholder registry** naming the source of truth (file or command) for each placeholder, for the Sunday 18:00 fact-check audit.
2. **`documentation/04_results/lint_writeup.py`**: a small checker, stdlib only.
   - Scaffold mode: every body placeholder must have a registry entry (wildcards like `S_*` and ranges like `FRONTIER_1..3` are supported).
   - `--final` mode: fails on any leftover `{{...}}` or on body prose over 2,300 words.
   - Both modes print words per section against the budgets.
3. **`documentation/04_results/stages_7_9_draft.md`**: a DRAFT for Tianle to rewrite.
   - **Stage 7:** queue-level tee, three-speed scoring (deterministic checks / analyst dispositions / SARs and QA), blind QA on frontier disagreements, segment-first ramp with gates (including a hard zero on approving sanctions true matches), atomic per-request fallback triggers with reason codes, and rollback as a flag.
   - **Stage 8:** a fix ladder (route-around → re-prompt → rollback → re-tune → re-distill → rebuild), a **14-class KYC failure taxonomy** with trigger signals and fixes, and the controller's decision order.
   - **Stage 9:** automation order with reasons (outcome-joined case store with hash-assigned splits first), plus two KYC-specific constraints: true matches are too rare in production, so the synthetic generator stays in the loop; and analyst labels carry automation bias.
   - Judgment calls are flagged ⚖ throughout. A ~150-word compression of each stage, sized for §6, is included.
4. **`tests/G_writeup_test.py`**: 9 tests covering the linter and the skeleton's structure.

## Not done
- Nothing from the Session G task list is left undone.
- The long-form stage 7 and 8 drafts run about 850 and 940 words with their tables, so a little over "about a page" each. They're raw material; the ~150-word compressions are what go in the PDF.
- No PDF build step was added. `pandoc` is suggested in the writing rules but not tested here.

## Test results
`python -m pytest tests/G_writeup_test.py -q` → **9 passed**.
`python documentation/04_results/lint_writeup.py documentation/04_results/writeup_skeleton.md` → exit 0 (224 placeholders, 0 unregistered).

## Problems
- **Branch naming:** see the top of this report.
- **Test file naming:** `pytest.ini` uses pytest's default discovery pattern (`test_*.py` / `*_test.py`), so a file named `tests/G_test_*.py` would be **silently skipped**. Mine is `tests/G_writeup_test.py`. Other sessions using `tests/<letter>_*.py` should check that their tests actually run.
- Several registry sources are *(TBD)* because they depend on files that don't exist yet (eval manifest, label-audit notes, final schema path). Fill them in as Saturday's work lands.

## Questions for Tianle
1. **Headline framing (§1):** should the headline lead with OOD accuracy or ID accuracy? The skeleton puts both side by side and asks that an OOD gap be stated in the first two sentences.
2. **Stage 7:** should the specialist ever approve without a human signature, or stay a drafting assistant? This sets the tone for all of §6.
3. **Stage 8:** is the controller allowed to *act* (route-around, rollback) or only *propose*? The draft assumes it contains failures on its own and proposes every model change.
4. **Table 2 shape:** a cumulative stack (each row adds one ingredient) or leave-one-out ablations? The skeleton uses a cumulative stack and suggests at least one leave-one-out row for the invented technique.
5. **Spend reporting:** should serving be reported as spend to date plus projected spend through 10/25, or only to date?
