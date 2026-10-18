"""Modal images, volumes and secrets shared by step5_training/sft.py, step5_training/dpo.py and step5_training/merge.py.

Two images, because Unsloth pins its own torch/transformers and can fight plain TRL:
  unsloth_image  Unsloth + TRL (default backend; 16-bit LoRA, NOT QLoRA)
  trl_image      plain Transformers v5 + TRL + PEFT (fallback, and used for merging)

Version floors only. After the first successful run, freeze the container's `pip freeze`
into the run metadata and pin exact versions here.

Volumes (created on first use):
  zorbe-hf-cache     HF_HOME, so base weights download once
  zorbe-checkpoints  adapters, merged weights, run metadata (mounted at /vol/ckpt)

Secret: a Modal secret named `huggingface` holding HF_TOKEN (needed for push_to_hub and
for any gated model). Create it once:  modal secret create huggingface HF_TOKEN=...
"""

import modal

HF_CACHE = "/vol/hf"
CKPT = "/vol/ckpt"

hf_cache = modal.Volume.from_name("zorbe-hf-cache", create_if_missing=True)
checkpoints = modal.Volume.from_name("zorbe-checkpoints", create_if_missing=True)
VOLUMES = {HF_CACHE: hf_cache, CKPT: checkpoints}
SECRETS = [modal.Secret.from_name("huggingface")]

_ENV = {"HF_HOME": HF_CACHE, "HF_HUB_ENABLE_HF_TRANSFER": "1", "TOKENIZERS_PARALLELISM": "false"}

trl_image = (
    modal.Image.debian_slim(python_version="3.11")
    .uv_pip_install(
        "torch>=2.8",
        "transformers>=5.20,<6",  # Qwen3.5 needs v5 (tooling traps); 5.20 passed step5_training.cpu_smoke
        "trl>=1.16,<2",           # 1.16 passed step5_training.cpu_smoke
        "peft>=0.21",
        "accelerate>=1.10",
        "datasets>=4.0",
        "huggingface_hub[hf_transfer]>=0.35",
        "pyyaml",
    )
    # Qwen3.5's linear-attention layers: without these transformers falls back to slow
    # reference kernels (Session B). causal-conv1d builds against the torch installed above.
    .uv_pip_install("packaging", "ninja", "wheel")
    .uv_pip_install("flash-linear-attention")  # causal-conv1d dropped: needs nvcc, image build failed (2026-10-17)
    .env(_ENV)
    .add_local_python_source("step5_training", "step6_evaluation", "shared")
)

unsloth_image = (
    modal.Image.debian_slim(python_version="3.11")
    .uv_pip_install(
        "unsloth",                # pulls compatible torch / transformers / trl / peft
        "unsloth_zoo",
        "datasets>=4.0",
        "huggingface_hub[hf_transfer]>=0.35",
        "pyyaml",
    )
    .uv_pip_install("packaging", "ninja", "wheel")
    .uv_pip_install("flash-linear-attention")  # causal-conv1d dropped: needs nvcc, image build failed (2026-10-17)
    .env(_ENV)
    .add_local_python_source("step5_training", "step6_evaluation", "shared")
)

IMAGES = {"unsloth": unsloth_image, "trl": trl_image}
