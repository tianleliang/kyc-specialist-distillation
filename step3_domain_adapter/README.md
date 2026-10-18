# step3_domain_adapter — continued pretraining on public KYC/AML text, and a test of whether it moved anything (pipeline stage 2 of the brief)

## What it does
- Trains a 16-bit LoRA with plain next-token loss on public regulatory and format text in `corpus/` (FATF, FinCEN CDD rule, ICAO 9303 MRZ parts, OFAC, Wolfsberg, sanctions list structure, address formats). No cases in it.
- Holds out about 1 in 10 corpus chunks (by hash) and never trains on them.
- Measures base vs base + adapter: held-out perplexity (overall and per document) and a 30-item multiple-choice KYC probe. A fixed rule prints the verdict ("moved" or "did not move").
- For the final model, the 4B adapter was merged into Qwen3.5-4B. The merged "adapted base" is the starting point for stage 3 distillation.

## Key files
| File | What it is |
|---|---|
| `corpus/*.txt`, `corpus/SOURCES.md` | Extracted text of the public documents, with sources and licensing notes (PDFs are gitignored) |
| `corpus/fetch_corpus.sh` | Re-fetches the documents (several URLs each, PDF check, sha256), converts with `pdftotext` |
| `common.py` | `AdapterCfg`, deterministic corpus split (~4k-char chunks, 1 in 10 held out), `verdict()` |
| `train_adapter.py` | Modal job: LoRA continued pretraining; held-out loss before and after. Reuses `step5_training` images and LoRA loader |
| `measure_adapter.py` | Modal job: held-out perplexity + probe, base vs adapter, verdict → `measure.json` |
| `probe.py` | 30 synthetic items (10 MRZ, 10 PEP / CDD, 10 lists / aliases / addresses), cloze-scored; `answerability()` checks the corpus can answer each |
| `cpu_smoke.py` | Train → measure on a tiny offline model and a corpus slice (CPU, about 1 minute) |
| `configs/adapter_4b.yaml` | The run used for the final model (`adapter-qwen35-4b`, Qwen3.5-4B, TRL backend, A100-80GB) |
| `configs/merge_adapter_4b.yaml` | Merge of the 4B adapter into Qwen3.5-4B (run by `step5_training/merge.py`) |
| `configs/adapter_2b.yaml`, `adapter_toy.yaml`, `adapter.yaml` | 2B variant; Qwen3-0.6B rehearsal (under $1); template with PLACEHOLDERs |

## How to use
```bash
python -m step3_domain_adapter.cpu_smoke                    # CPU pre-flight, free (needs torch, transformers, peft, trl)
bash step3_domain_adapter/corpus/fetch_corpus.sh            # re-fetch the corpus (network; needs curl, pdftotext)
```
Train, measure and merge the 4B adapter (Modal GPU, costs money):
```bash
modal run -m step3_domain_adapter.train_adapter --config step3_domain_adapter/configs/adapter_4b.yaml --dry-run
modal run -m step3_domain_adapter.train_adapter --config step3_domain_adapter/configs/adapter_4b.yaml
modal run -m step3_domain_adapter.measure_adapter --config step3_domain_adapter/configs/adapter_4b.yaml
python -m modal run -m step5_training.merge --config step3_domain_adapter/configs/merge_adapter_4b.yaml
```
`measure_adapter` also takes `--adapter-dir /vol/ckpt/adapter/<run>/adapter`. In the final pipeline, `step5_training/launch_final.sh` runs the merge as its step 0 if the merged weights are missing.

Tests: `python -m pytest -q tests/m_adapter_test.py` (the CPU smoke part is skipped without the training libraries).

## Outputs / where results live
- On the Modal volume `zorbe-checkpoints`: `adapter/<run_name>/` (adapter + `run.json` + `measure.json`); merged weights at `/vol/ckpt/merged/adapter-qwen35-4b` (with `verify.json`).
- Local copy of the measurement: `outputs/adapter/<run_name>/measure.json` (gitignored).
- Committed logs: `step5_training/results/logs/merge_adapter_4b.log` (merge proof: base vs merged generations differ). `step5_training/results/logs/adapter_4b_measure.log` is meant to hold the measurement table but contains only a shell error line (see Details).

## Reports and evidence
- [writeup_evidence_log.md](../documentation/04_writeup/writeup_evidence_log.md) §5b: 4B result. Held-out perplexity 7.39 → 5.52 (−25%), down on all 10 documents; probe 61% → 65% on 23 answerable items (1 item, within noise). It learned the domain's language, not measurably its knowledge.
- [benchmark_report_submission.md](../documentation/04_writeup/benchmark_report_submission.md) Table 2: the adapter is reported together with twins distillation as one stage row.
- [TONIGHT_4B.md](../documentation/06_agent_instructions/TONIGHT_4B.md): the 4B adapter check; the result is written into the file.
- [FINAL_RUN_INFRA.md](../documentation/06_agent_instructions/FINAL_RUN_INFRA.md): the merge into the 4B base.
- [lunch-M.md](../documentation/05_progress_reports/lunch-M.md): how the adapter code, probe and verdict rule were built; CPU smoke.
- [LUNCH.md](../documentation/06_agent_instructions/LUNCH.md) (Session M), [overnight-A.md](../documentation/05_progress_reports/overnight-A.md) (first corpus attempt, blocked).
- [REQUIREMENTS.md](../documentation/00_requirements/REQUIREMENTS.md): stage 2 requirement mapped here.

## Details
**Verdict rule** (`common.verdict`): "moved" requires held-out perplexity to fall by at least 2% **and** probe accuracy on the answerable items not to fall. Report whatever it prints, including "did not move".

**Perplexity** is token-weighted over non-overlapping `max_seq_len` windows of each held-out chunk, and also per corpus file, so a gain on one dominant document is visible as such. `max_chars_per_file: 400000` caps the large FinCEN rule.

**Probe.** Multiple choice, 4 options, scored by length-normalised option log-likelihood, so it needs no instruction following and works the same before and after training. Each item names its source file and an evidence phrase. The check-digit items use `step1_data_generation.lib.mrz.check_digit` on invented strings.

**Contamination.** The corpus is public regulatory text with no cases. Probe questions are synthetic, and a test checks they are not in the training text. Held-out chunks are never trained on.

**Corpus history.** The first cloud session could not reach the publishers (HTTP 403), so the corpus was fetched on the laptop with `fetch_corpus.sh`. FATF and ICAO PDFs say "no reproduction without permission", so only extracted text is kept. `SOURCES.md` still has some pre-fetch notes (file names and "in repo? no" marks) that no longer match the files in `corpus/`.

**Known gap.** The committed `adapter_4b_measure.log` holds one line (`launch_4b_batch.sh: line 18: r_4b.yaml: command not found`), not the before/after table. The quoted numbers come from the session's own record in `TONIGHT_4B.md`.
