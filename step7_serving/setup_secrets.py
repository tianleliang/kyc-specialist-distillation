"""One-time setup of the Modal secrets the serving stack needs. Prints no secret values.

    python -m step7_serving.setup_secrets

* Generates `VLLM_API_KEY` (vLLM's own --api-key) and `PROXY_API_KEY` (the bearer token
  callers use) if `.env` lacks them, and appends them to `.env` (gitignored).
* Creates / overwrites three Modal secrets from `.env`:
    huggingface   HF_TOKEN                          (step5_training/*, gated downloads, HF push)
    zorbe-vllm    VLLM_API_KEY                      (step7_serving/modal_vllm.py)
    zorbe-proxy   PROXY_API_KEYS, VLLM_API_KEY      (step7_serving/modal_vllm.py proxy function)
"""
from __future__ import annotations

import os
import secrets
import subprocess
import tempfile
from pathlib import Path

ENV = Path(__file__).resolve().parents[1] / ".env"


def read_env() -> dict[str, str]:
    out = {}
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def ensure_tokens(env: dict[str, str]) -> list[str]:
    added = [k for k in ("VLLM_API_KEY", "PROXY_API_KEY") if not env.get(k)]
    if added:
        text = ENV.read_text(encoding="utf-8")
        with open(ENV, "a", encoding="utf-8") as f:
            if text and not text.endswith("\n"):
                f.write("\n")
            for k in added:
                env[k] = "zk-" + secrets.token_urlsafe(32)
                f.write(f"{k}={env[k]}\n")
    return added


def create_secret(name: str, values: dict[str, str]) -> None:
    fd, path = tempfile.mkstemp(suffix=".env")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.writelines(f"{k}={v}\n" for k, v in values.items())
        r = subprocess.run(["modal", "secret", "create", name, "--from-dotenv", path, "--force"],
                           capture_output=True, text=True)
    finally:
        os.unlink(path)
    print(f"{name}: {'ok' if r.returncode == 0 else 'FAILED (exit %d)' % r.returncode} "
          f"[{', '.join(values)}]")


def main() -> None:
    env = read_env()
    if not env.get("HF_TOKEN"):
        raise SystemExit("HF_TOKEN missing from .env")
    added = ensure_tokens(env)
    if added:
        print(f"added to .env: {added}")
    create_secret("huggingface", {"HF_TOKEN": env["HF_TOKEN"]})
    create_secret("zorbe-vllm", {"VLLM_API_KEY": env["VLLM_API_KEY"]})
    create_secret("zorbe-proxy", {"PROXY_API_KEYS": env["PROXY_API_KEY"],
                                  "VLLM_API_KEY": env["VLLM_API_KEY"]})


if __name__ == "__main__":
    main()
