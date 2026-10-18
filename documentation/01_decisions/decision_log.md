# Decision log

Every design decision, in order, with its reason. Decisions are Tianle's; where Claude proposed the option, that's noted. Times are US Eastern, Oct 16–18 2026. The original 20-question sheet behind the Saturday-morning decisions is [`decision_sheet.md`](decision_sheet.md); numbers come from [`../04_writeup/writeup_evidence_log.md`](../04_writeup/writeup_evidence_log.md).

## Setup (Sat morning)
| # | Decision | Why |
|---|---|---|
| D1 | Schema: flat object with enum reason codes | Fixed codes cover nearly every case and make every decision traceable; true edge cases go to the narrative and escalate |
| D2 | Identity: the 3 statuses (consistent / mismatch / unreadable) per field; `verified` = all five consistent; expiry as a reason code | Match the task definition exactly |
| D3 | Evidence: section enum + per-sentence `hit_ids` | Keeps narrative grounding checkable on any packet |
| D4 | Reject only on a sanctions true match or **clear** tampering (overrode the sheet's recommendation) | Not everything can be "escalate"; matches desk practice and frontier behaviour (decision mix ≈ 36 / 51 / 13) |
| D5 | Injected instructions → always escalate (a sanctions true match still rejects) | A security control can't be overridden by the packet |
| D6 | OCR vs tamper is three-way: readable noise / ambiguous → escalate / clear tamper → reject | The task's "OCR that looks like tampering and tampering that looks like OCR" needs a middle class |
| D7–12 | Disposition, PEP / adverse media, expired ID + 90-day proof of address, risk-tier table, 12-code action catalog, policy text in best / teacher / student prompts but not zero-shot | Defaults from the policy candidate, approved after a coverage check |
| D13 | Sizes: train 3,000 (+1,000 twins), dev 150, eval_id 300, OOD 200 | ±4 pts at n=300 within budget |
| D16 | Base: Qwen3.5 0.8B / 2B / 4B; ship the smallest within 2 pts of 4B on dev with ≥ 99% valid JSON | One family, clean size steps, Apache 2.0 |
| D17 | Frontier roles: Astra / Opus / Argon baselines; teachers picked by a pilot (Claude never teaches); Sonnet judges | Separation of roles; provider terms |
| D21 | Student gets a short prompt (613 chars) and learns the policy from training; teachers and baselines get the full rulebook (~16k tokens) | The rulebook doesn't fit the 4,096-token training window; "learn the policy instead of renting it" |

## Data, teachers, size (Sat afternoon)
| # | Decision | Why |
|---|---|---|
| — | Fix the rule, not the case, when the pilot disagreed with a label | All four frontier models disagreed with gold on the proof-of-address addressee: the rule was ambiguous; clarified in `policy_v1.md`, every split rebuilt |
| — | Freeze all test sets by sha256 before any teacher call | Contamination control from the start; 0/500 overlap |
| — | Build eval_hard (150, 2–3 stacked difficulties) | Zero-shot frontier was 100% on half the case types; we wanted a stress set |
| — | Sol becomes the main teacher, Argon second | Sol 100% on the 100-case pilot at the lowest cost; Gemini's rate cap throttled Argon |
| — | Ship small model + code pre-checker (report with and without) | The students' remaining errors were arithmetic (MRZ check digits, date windows) |

## Distillation and final runs (Sat night)
| # | Decision | Why |
|---|---|---|
| — | 4B (rule: 2B was 3.3 pts behind 4B on dev) | Pre-set size rule |
| — | Cut adversarial hard-case mining (Claude proposed) | Brief minimum met (floor + rejection + arbitration + invented); residual errors were arithmetic, which hard cases don't fix |
| — | Name the invented technique: **Counterfactual Twin Distillation** | Pairs identical except one decision-flipping fact make the student find the deciding fact |
| — | Ship twins over rejection (post-hoc, stated as such) | Dev decision was a 1-case tie; twins had the best actions recall (+6.3) and half the wrong approvals (6 vs 11) |
| — | Stage 4 = SFT on exact labels + teacher narratives, not DPO / RL | Labels are exact; DPO lacked rejected answers (~30); RL too slow for the deadline |
| — | Pre-checker v2: policy §3 integrity class per field, 0 wrong on train + dev | v1 couldn't separate ambiguous (escalate) from clear tamper (reject) |
| — | Keep the halfway checkpoint score | It is the only "before" number for stage 4 and isolates the adapter |

## Diagnosis and fix (Sun)
| # | Decision | Why |
|---|---|---|
| — | Report Final B (90.8% on the frozen 500) as the clean pre-diagnosis result | Dev said 98%; the frozen sets exposed the pre-checker reader's overfitting to training layouts |
| — | Rebuild the reader (v3) on train-process data only + a format fuzzer with a held-out family; never touch eval or the LLM-rewrite process | Fix without contaminating the remaining clean tests |
| — | Retrain B with 25% blank pre-check blocks (B-run2) | With an empty block B fell below A; it must learn to fall back |
| — | Generate a fresh eval_id v2 and re-run the frontier on it | The reader fix used what the frozen sets showed; v2 gives an untouched re-test |
| — | Headline = in-distribution (eval_id v2); OOD reported beside it | A specialist for a desk's known formats; OOD shows where to route to the frontier |
| — | Freeze reader v3 for training; build v3.1 in parallel and swap it in at serving | The model learns the block's format; result: identical scores, so ship v3 |
| — | Ship B-run2 final (with post-train) over the halfway model | Statistically tied; it is the pipeline designed beforehand |
| — | Hand-over endpoint on an L4; measure an H100 sample | L4 is cheapest for an always-on endpoint; the H100 sample shows the latency we can buy (3.3 s p50) |
| — | Public repo from a clean snapshot (fresh history) | Old history held private planning notes |
