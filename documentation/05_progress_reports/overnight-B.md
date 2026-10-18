# Session B report: serving infrastructure smoke test

Run Sat 2026-10-17 on the laptop against Modal workspace `tianleliang`. Branch `overnight-b`.
Full commands, numbers and gotchas: `step7_serving/README.md`.

## Done
1. **`step7_serving/modal_vllm.py`**: vLLM 0.30.0 on one L4 serving `Qwen/Qwen3.5-0.8B` (exact HF ID;
   no Qwen3-0.6B fallback needed). OpenAI-compatible `/v1/chat/completions`, `--api-key` from Modal
   secret `zorbe-vllm`, thinking off server-side, weights in volume `zorbe-hf-cache`, compile cache in
   `zorbe-vllm-cache`, scale to zero by default. **`step7_serving/proxy.py` runs in front** as a second,
   CPU-only function in the same app (caller token -> proxy -> vLLM token). Merged weights from
   `zorbe-checkpoints` deploy as their own app via env vars.
2. **`step7_serving/smoke.py`**: all checks pass on both raw vLLM and the proxy: 401 without / with a wrong
   token, `json_schema` enforced (toy enum + bounds + regex, with a negative control), no thinking.
   Cold start 288 s with warm caches (385 s first ever). Warm p50/p95 over 20 requests:
   367/377 ms raw, 412/427 ms via proxy (proxy hop ~45-60 ms).
3. **Train -> merge -> serve rehearsal**: on Qwen3.5-0.8B (the real family, not the Qwen3-0.6B toy
   config) with Session F's `step5_training.sft` / `step5_training.merge` unchanged; configs in `step7_serving/rehearsal/`.
   SFT, then merge verify (4/4 probes differ), then served merged vs served base on 6 held-out probes:
   6/6 differ, trained marker in 6/6 vs 0/6. **PASS.**
4. Skipped as instructed: `step6_evaluation/run_open_models.py`. `step2_benchmarking/run_endpoint.py` already covers it; the
   README has the exact commands for raw vLLM and the proxy.
5. **`step7_serving/README.md`**: commands, measured numbers, cost, 9 gotchas.
6. **Cost**: $1.33 metered in total (credits; $0 billed). Every app is stopped and `modal container list` is empty.

Also: `step7_serving/setup_secrets.py` (creates the 3 Modal secrets from `.env`, generates the 2 serving
tokens, prints no values) and `tests/b_serve_test.py` (6 offline tests, pass).

## Not done / open
- **The untrained base can't produce a valid KYC output.** It loops inside a free-text string until
  `max_tokens`, so the proxy returns its schema-valid escalate fallback (~30 s). This is expected
  before training, but it means **zero-shot open-model rows in Table 1 will show near-0 schema validity
  unless strings get a `maxLength`**.
- Not tested: concurrency/throughput under load, streaming through Modal, kept-warm (`min_containers=1`).

## Problems hit (all fixed, details in README gotchas)
- vLLM's JSON grammar allowed unbounded whitespace, and the 0.8B filled 2048 tokens with spaces.
  Now `disable_any_whitespace` is on by default (it needs an explicit `backend: xgrammar`).
- A vLLM process that died on a bad flag kept the L4 for the whole 20-min `startup_timeout`
  (~$0.27). Fixed with a watchdog that kills the container when vLLM exits.
- Git Bash rewrote `/vol/ckpt/...` into a Windows path; the module now refuses such paths.
- Redeploying keeps a warm container on the old flags: stop the app first.

## Questions for Tianle
1. **Schema**: add `maxLength` to free-text fields (`reason`, narrative `sentence`)? It's the only way
   to stop the string loops at decode time, and it affects the frontier APIs' structured-output limits too.
2. **JSON separators**: with `disable_any_whitespace`, vLLM forces `", "` / `": "`, but SFT targets
   are serialized with `(",", ":")`. Switch targets to the default separators (my suggestion: it's a
   one-line change in `step4_distillation/common.py`, and the grammar then matches training exactly), or serve
   trained models with `ZORBE_SERVE_NO_WS=0`?
3. **Hand-over serving**: the 288 s cold start rules out pure scale-to-zero for Zorbe's endpoint.
   Options: always-on L4 (~$19/day), or a timed warm-up window. This is part of your serving-plan decision.
4. **Training images**: for the real Qwen3.5 SFT, add `flash-linear-attention` and `causal-conv1d` to
   `step5_training/modal_infra.py` (Session F's file)? Without them transformers falls back to slow reference kernels.
