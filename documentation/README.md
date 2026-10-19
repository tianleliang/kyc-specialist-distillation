# documentation — requirements, decisions, research, design, write-up and the session record

Everything written around the code: what was required, what was decided and why, the research and design drafts, the write-up with its evidence, and the record of each agent session. Author: Tianle (with Claude agent sessions; every decision is Tianle's).

## Start here
| File | Why |
|---|---|
| **[04_results/benchmark_report_submission.md](04_results/benchmark_report_submission.md)** | **The headline tables**: final model B2 vs open and frontier models (Table 1), gain per pipeline stage (Table 2), A / B / B2 on every test set |
| [04_results/benchmark_report.md](04_results/benchmark_report.md) | Full generated report: every model × every eval set, CIs, confusion matrices. Rebuilt by `bash make_tables.sh` |
| **[04_results/full_writeup.md](04_results/full_writeup.md)** | **The long write-up**: every decision, realization and failure, and the full stage 7–9 answers |
| [04_results/findings_log.md](04_results/findings_log.md) | Every finding with its numbers and the reasoning behind it (data, contamination, teachers, students, diagnosis, pre-checker, cost) |
| [01_decisions/decision_log.md](01_decisions/decision_log.md) | Every design decision in order, with its reason |
| [00_requirements/](00_requirements/) | The case requirements (paraphrased) and where each one is met |

## Subfolders
| Folder | What is in it | Key files |
|---|---|---|
| [00_requirements/](00_requirements/) | Our own checklist of the case requirements, mapped to where each is satisfied | [REQUIREMENTS.md](00_requirements/REQUIREMENTS.md) |
| [01_decisions/](01_decisions/) | The decision log, plus the Saturday-morning decision material (morning summary, 20-decision sheet, policy candidate) | **[decision_log.md](01_decisions/decision_log.md)**, [decision_sheet.md](01_decisions/decision_sheet.md), [morning_brief.md](01_decisions/morning_brief.md), [policy_v1_candidate.md](01_decisions/policy_v1_candidate.md) |
| [02_research/](02_research/) | Background research drafts (options, not decisions): KYC primer, draft policy, schema options, distillation options | [kyc_primer.md](02_research/kyc_primer.md), [distillation_options.md](02_research/distillation_options.md), [schema_options.md](02_research/schema_options.md) (+ `schema_options/` example schemas), [decision_policy_draft.md](02_research/decision_policy_draft.md) |
| [03_design/](03_design/) | Design drafts written before the build: decision memos, data design, contamination protocol, experiment plan | [contamination_protocol.md](03_design/contamination_protocol.md), [data_design.md](03_design/data_design.md), [experiment_plan.md](03_design/experiment_plan.md), [decision_memos.md](03_design/decision_memos.md) |
| [04_results/](04_results/) | The benchmark reports and the findings log (every number with its source) | **[benchmark_report_submission.md](04_results/benchmark_report_submission.md)**, **[benchmark_report.md](04_results/benchmark_report.md)**, **[findings_log.md](04_results/findings_log.md)** |
| [05_progress_reports/](05_progress_reports/) | One report per build session (overnight waves 1–2, lunch), plus data samples and the brief-coverage audit | [index](05_progress_reports/README.md) |
| [06_agent_instructions/](06_agent_instructions/) | The instruction files each agent session ran from, Friday night to Sunday | [index](06_agent_instructions/README.md) |

## Notes
- The 02_research and 03_design files are drafts from before the decisions. Where they differ from the code, the code, `step0_rules/policy_v1.md` and the decision log win.
- Progress reports cover the build sessions up to Saturday lunch. The Saturday-night and Sunday runs (4B recipes, finals A and B, the diagnosis, reader v3, B2) are recorded in the evidence log (§5b, §5c) and in the instruction files.
- Model names: A = `final-A-s4` (no pre-checks), B = `final-B-s4` (pre-checker v2, before the diagnosis), B2 = `final-Brun2-s4` (the final model). Some files call B2 "B-run2" or "B-v3".
- Per-folder READMEs for the code (`step0_rules/` … `step7_serving/`, `data/`, `results/`) link back to the relevant files here.
