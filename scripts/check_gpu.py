"""Step 1 GPU check: confirms PyTorch sees the RTX 5070 Ti and supports bf16.

Run with: uv run --extra train python scripts/check_gpu.py
"""

import sys

import torch


def main() -> int:
    print(f"torch {torch.__version__} | built for CUDA {torch.version.cuda}")
    if not torch.cuda.is_available():
        print("FAIL: torch.cuda.is_available() is False (driver not loaded, or CPU-only torch wheel)")
        return 1
    name = torch.cuda.get_device_name(0)
    major, minor = torch.cuda.get_device_capability(0)
    total_gb = torch.cuda.get_device_properties(0).total_memory / 1024**3
    print(f"device: {name} | compute capability sm_{major}{minor} | {total_gb:.1f} GiB")
    print(f"bf16 supported: {torch.cuda.is_bf16_supported()}")
    # A real kernel launch catches "device visible but no kernels for this arch" errors.
    x = torch.randn(1024, 1024, device="cuda", dtype=torch.bfloat16)
    y = (x @ x).float().sum().item()
    print(f"matmul on GPU ok (checksum {y:.2f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
