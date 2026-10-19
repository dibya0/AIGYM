"""Merge the best-validation LoRA checkpoint into the base model so vLLM can serve it for the held-out eval.

    uv run python scripts/merge_adapter.py results/train/<run>

Uses best_checkpoint.json written by the training callback (chosen on the validation split only). If the
best step is 0, no checkpoint beat the starting policy on validation; that is reported, not hidden.
Writes results/train/<run>/merged/ (weights are git-ignored).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main(run_dir: Path) -> None:
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    cfg = json.loads((run_dir / "config.json").read_text())
    best = json.loads((run_dir / "best_checkpoint.json").read_text())
    if best["best_step"] in (0, None):
        print("no checkpoint beat the base policy on validation (best_step=0): evaluate the base model; report this")
        return
    adapter = run_dir / best["checkpoint"]
    base = AutoModelForCausalLM.from_pretrained(cfg["model"], torch_dtype="bfloat16")
    merged = PeftModel.from_pretrained(base, str(adapter)).merge_and_unload()
    out = run_dir / "merged"
    merged.save_pretrained(out)
    AutoTokenizer.from_pretrained(cfg["model"]).save_pretrained(out)
    (out / "SOURCE.json").write_text(json.dumps({"base": cfg["model"], "adapter": str(adapter), **best}, indent=2))
    print(f"merged {adapter} -> {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
