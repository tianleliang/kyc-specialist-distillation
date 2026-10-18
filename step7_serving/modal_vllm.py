"""vLLM on a Modal L4, with step7_serving/proxy.py in front. Two web functions in one Modal app:

    vllm   (GPU, L4)   raw vLLM OpenAI server, `--api-key` from the `zorbe-vllm` secret.
                       https://<workspace>--<app>-vllm.modal.run/v1/chat/completions
    proxy  (CPU)       step7_serving/proxy.py: caller bearer token, prompt + schema injection,
                       validation, one retry, escalate fallback. Calls `vllm` over HTTPS
                       with VLLM_API_KEY.
                       https://<workspace>--<app>-proxy.modal.run/v1/chat/completions

    caller --Bearer PROXY_API_KEY--> proxy (CPU) --Bearer VLLM_API_KEY--> vllm (L4)

Deploy / run (settings are read at deploy time and baked into the image env, so the
container re-imports the module with the same values):

    modal deploy -m step7_serving.modal_vllm                                   # base Qwen3.5-0.8B
    ZORBE_SERVE_MODEL=/vol/ckpt/merged/<run> ZORBE_SERVE_APP=zorbe-serve-<run> \\
        modal deploy -m step7_serving.modal_vllm                               # merged weights
    modal app stop zorbe-serve                                         # tear down

Env knobs (all optional):
    ZORBE_SERVE_MODEL      HF id or a path on the zorbe-checkpoints volume (/vol/ckpt/...)
    ZORBE_SERVE_NAME       model name vLLM serves (default: last path component)
    ZORBE_SERVE_APP        Modal app name (default zorbe-serve)
    ZORBE_SERVE_MIN        min_containers for vllm (default 0 = scale to zero; 1 = kept warm)
    ZORBE_SERVE_SCALEDOWN  idle seconds before a container stops (default 300)
    ZORBE_SERVE_EAGER      1 = --enforce-eager (faster cold start, slower decode)
    ZORBE_SERVE_MAX_LEN    --max-model-len (default 8192)
    ZORBE_SERVE_NO_WS      1 (default) = structured outputs without free whitespace
    ZORBE_PRECHECKS        1 = the proxy adds the PRE-CHECKS block (Final B); default 0
    ZORBE_PROXY_MIN        min_containers for the CPU proxy (default 0; 1 for the hand-over endpoint)

Weights are cached in the `zorbe-hf-cache` volume (same one step5_training/ uses), vLLM's
torch.compile cache in `zorbe-vllm-cache`. Thinking is off server-side
(`--default-chat-template-kwargs`) and again per request by the proxy.
Secrets: run `python -m step7_serving.setup_secrets` once.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path

import modal

MODEL = os.environ.get("ZORBE_SERVE_MODEL", "Qwen/Qwen3.5-0.8B")
if ":" in MODEL or "\\" in MODEL:
    # Git Bash rewrites /vol/ckpt/... into C:/Program Files/Git/vol/ckpt/... on Windows.
    raise SystemExit(f"ZORBE_SERVE_MODEL looks like a Windows path ({MODEL!r}); "
                     "in Git Bash set MSYS_NO_PATHCONV=1, or deploy from PowerShell")
SERVED = os.environ.get("ZORBE_SERVE_NAME") or MODEL.rstrip("/").split("/")[-1]
APP = os.environ.get("ZORBE_SERVE_APP", "zorbe-serve")
MIN = int(os.environ.get("ZORBE_SERVE_MIN", "0"))
SCALEDOWN = int(os.environ.get("ZORBE_SERVE_SCALEDOWN", "300"))
EAGER = os.environ.get("ZORBE_SERVE_EAGER", "0") == "1"
MAX_LEN = int(os.environ.get("ZORBE_SERVE_MAX_LEN", "8192"))
GPU = os.environ.get("ZORBE_SERVE_GPU", "L4")              # L4 (default, cheapest) | L40S | H100
NO_WS = os.environ.get("ZORBE_SERVE_NO_WS", "1") == "1"
PROXY_MIN = int(os.environ.get("ZORBE_PROXY_MIN", "0"))
VLLM_VERSION = "0.30.0"
PORT = 8000

HF_CACHE, CKPT, VLLM_CACHE = "/vol/hf", "/vol/ckpt", "/root/.cache/vllm"
hf_cache = modal.Volume.from_name("zorbe-hf-cache", create_if_missing=True)
checkpoints = modal.Volume.from_name("zorbe-checkpoints", create_if_missing=True)
vllm_cache = modal.Volume.from_name("zorbe-vllm-cache", create_if_missing=True)

_BAKED = {"ZORBE_SERVE_MODEL": MODEL, "ZORBE_SERVE_NAME": SERVED, "ZORBE_SERVE_APP": APP,
          "ZORBE_SERVE_MIN": str(MIN), "ZORBE_SERVE_SCALEDOWN": str(SCALEDOWN),
          "ZORBE_SERVE_EAGER": "1" if EAGER else "0", "ZORBE_SERVE_MAX_LEN": str(MAX_LEN),
          "ZORBE_SERVE_NO_WS": "1" if NO_WS else "0", "ZORBE_PROXY_MIN": str(PROXY_MIN), "ZORBE_SERVE_GPU": GPU}

vllm_image = (
    modal.Image.from_registry("nvidia/cuda:12.9.1-devel-ubuntu22.04", add_python="3.12")
    .entrypoint([])
    .uv_pip_install(f"vllm=={VLLM_VERSION}", "huggingface_hub[hf_transfer]")
    .env({"HF_HOME": HF_CACHE, "HF_HUB_ENABLE_HF_TRANSFER": "1", "VLLM_NO_USAGE_STATS": "1",
          **_BAKED})
)

ROOT = Path(__file__).resolve().parents[1]
_SKIP = ["**/__pycache__/**", "**/*.pyc"]
proxy_image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_pip_install("fastapi>=0.110", "httpx>=0.27", "jsonschema>=4", "pyyaml>=6",
                    "pydantic>=2", "numpy>=1.26", "rapidfuzz>=3")
    .env({**_BAKED, "ZORBE_PRECHECKS": os.environ.get("ZORBE_PRECHECKS", "0")})  # proxy only (Final B)
    .add_local_python_source("step7_serving", "step0_rules", "step1_data_generation", "shared", ignore=_SKIP)
    )

app = modal.App(APP)


def vllm_cmd(api_key: str) -> list[str]:
    cmd = ["vllm", "serve", MODEL, "--served-model-name", SERVED, "--host", "0.0.0.0",
           "--port", str(PORT), "--api-key", api_key, "--max-model-len", str(MAX_LEN),
           "--gpu-memory-utilization", "0.90", "--uvicorn-log-level", "warning",
           "--default-chat-template-kwargs", json.dumps({"enable_thinking": False}),
           # Qwen3.5 checkpoints are multimodal; we only send text, so skip vision profiling.
           "--limit-mm-per-prompt", json.dumps({"image": 0, "video": 0})]
    if NO_WS:
        # The JSON grammar otherwise allows unbounded whitespace, and an untrained 0.8B model
        # fills max_tokens with spaces (60% whitespace, finish=length, invalid JSON).
        cmd += ["--structured-outputs-config", json.dumps({"backend": "xgrammar", "disable_any_whitespace": True})]
    if EAGER:
        cmd.append("--enforce-eager")
    return cmd


@app.function(image=vllm_image, gpu=GPU, timeout=24 * 3600,
              volumes={HF_CACHE: hf_cache, CKPT: checkpoints, VLLM_CACHE: vllm_cache},
              secrets=[modal.Secret.from_name("zorbe-vllm"), modal.Secret.from_name("huggingface")],
              min_containers=MIN, max_containers=1, scaledown_window=SCALEDOWN)
@modal.concurrent(max_inputs=64)
@modal.web_server(port=PORT, startup_timeout=20 * 60)
def vllm():
    if MODEL.startswith(CKPT):
        checkpoints.reload()
    # list form: the key never goes through a shell or into our logs
    proc = subprocess.Popen(vllm_cmd(os.environ["VLLM_API_KEY"]))

    def watchdog():
        # If vLLM dies (bad flag, OOM), kill the container now instead of holding the GPU
        # until startup_timeout (observed: a rejected flag kept an L4 for 20 minutes).
        code = proc.wait()
        print(f"vLLM exited with code {code}; stopping container")
        os._exit(1)

    threading.Thread(target=watchdog, daemon=True).start()


@app.function(image=proxy_image, secrets=[modal.Secret.from_name("zorbe-proxy")],
              min_containers=PROXY_MIN, max_containers=1, scaledown_window=SCALEDOWN, timeout=3600)
@modal.concurrent(max_inputs=128)
@modal.asgi_app()
def proxy():
    import logging

    from step7_serving.proxy import ProxyConfig, create_app

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    os.chdir("/root")  # relative schema / prompt paths in the config resolve from the repo root
    cfg = ProxyConfig.load("/root/step7_serving/proxy_config.example.yaml",
                           upstream_url=vllm.get_web_url().rstrip("/") + "/v1",
                           upstream_model=SERVED, upstream_api_key_env="VLLM_API_KEY")
    return create_app(cfg)
