"""Upload a merged model from the Modal checkpoints volume to the Hugging Face Hub (runs ON Modal:
nothing is downloaded to the laptop). Public by default, so the link works without a login.

    python -m modal run -m step7_serving.upload_hf --run final-Brun2-s4 --repo tianle-terrence-liang/zorbe-kyc-specialist-4b
    python -m modal run -m step7_serving.upload_hf ... --dry-run      # list what would be uploaded
    python -m modal run -m step7_serving.upload_hf --repo <repo> --adapters [--dry-run]   # the 3 LoRA adapters

Uploads /vol/ckpt/merged/<run>/ (weights, config, tokenizer, verify.json) plus the model card
step7_serving/MODEL_CARD.md as README.md. Uses the Modal secret `huggingface` (HF_TOKEN).
"""
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import modal

from step5_training.modal_infra import CKPT, SECRETS, VOLUMES, checkpoints

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install("huggingface_hub[hf_transfer]>=0.35")
    .add_local_python_source("step5_training", ignore=["**/__pycache__/**"])
)
app = modal.App("zorbe-upload-hf")


@app.function(image=image, volumes=VOLUMES, secrets=SECRETS, timeout=3600,
              env={"HF_HUB_ENABLE_HF_TRANSFER": "1"})
def upload(run: str, repo: str, card: str, private: bool, dry_run: bool) -> dict:
    import os
    from huggingface_hub import HfApi
    checkpoints.reload()
    src = Path(CKPT) / "merged" / run
    files = sorted(str(p.relative_to(src)) for p in src.rglob("*") if p.is_file())
    if not (src / "config.json").exists():
        raise FileNotFoundError(f"no merged model at {src}")
    size = sum((src / f).stat().st_size for f in files)
    out = {"src": str(src), "files": files, "bytes": size, "repo": repo, "private": private}
    if dry_run:
        return out
    api = HfApi(token=os.environ["HF_TOKEN"])
    out["whoami"] = api.whoami()["name"]
    api.create_repo(repo, private=private, exist_ok=True, repo_type="model")
    api.upload_folder(folder_path=str(src), repo_id=repo, repo_type="model",
                      commit_message=f"{run}: merged weights (Qwen3.5-4B + adapter + twins distillation + post-train)")
    api.upload_file(path_or_fileobj=card.encode("utf-8"), path_in_repo="README.md", repo_id=repo,
                    commit_message="model card")
    out["url"] = f"https://huggingface.co/{repo}"
    return out


@app.function(image=image, volumes=VOLUMES, secrets=SECRETS, timeout=3600,
              env={"HF_HUB_ENABLE_HF_TRANSFER": "1"})
def upload_adapters(repo: str, items: list, dry_run: bool) -> dict:
    """Upload LoRA adapter folders from the volume into subfolders of an existing model repo."""
    import os
    from huggingface_hub import HfApi
    checkpoints.reload()
    out = {}
    api = None if dry_run else HfApi(token=os.environ["HF_TOKEN"])
    for src, dst in items:
        p = Path(CKPT) / src
        files = sorted(str(f.relative_to(p)) for f in p.rglob("*") if f.is_file())
        out[dst] = {"src": str(p), "files": len(files), "bytes": sum((p / f).stat().st_size for f in files)}
        if api is not None:
            api.upload_folder(folder_path=str(p), repo_id=repo, repo_type="model", path_in_repo=dst,
                              commit_message=f"LoRA adapter: {dst}")
    return out


ADAPTERS = [("adapter/adapter-qwen35-4b/adapter", "adapters/domain_adapter"),
            ("sft/final-Brun2-s3/adapter", "adapters/stage3_distillation"),
            ("sft/final-Brun2-s4/adapter", "adapters/stage4_posttrain")]


@app.local_entrypoint()
def main(run: str = "", repo: str = "", private: bool = False, dry_run: bool = False, adapters: bool = False):
    if adapters:
        print(upload_adapters.remote(repo, ADAPTERS, dry_run))
        return
    card_path = Path(__file__).with_name("MODEL_CARD.md")
    card = card_path.read_text(encoding="utf-8") if card_path.exists() else f"# {repo}\n"
    r = upload.remote(run, repo, card, private, dry_run)
    print({k: (v if k != "files" else f"{len(v)} files") for k, v in r.items()})
