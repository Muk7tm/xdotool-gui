from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from typing import Callable


@dataclass(slots=True)
class RetryPolicy:
    attempts: int = 3
    delay_ms: int = 150


class XdotoolRunner:
    def __init__(self, default_policy: RetryPolicy | None = None) -> None:
        self.default_policy = default_policy or RetryPolicy()

    def run(
        self,
        argv: list[str],
        policy: RetryPolicy | None = None,
        logger: Callable[[str], None] | None = None,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        attempts = max((policy or self.default_policy).attempts, 1)
        delay_ms = max((policy or self.default_policy).delay_ms, 0)
        last_result: subprocess.CompletedProcess[str] | None = None
        for attempt in range(1, attempts + 1):
            try:
                result = subprocess.run(
                    argv,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=timeout,
                )
            except FileNotFoundError:
                raise
            except subprocess.TimeoutExpired as exc:
                result = subprocess.CompletedProcess(argv, 124, exc.stdout or "", exc.stderr or f"Timeout after {timeout}s")
            except Exception as exc:  # pragma: no cover - defensive
                result = subprocess.CompletedProcess(argv, 1, "", str(exc))
            last_result = result
            if result.returncode == 0:
                return result
            if logger is not None:
                logger(f"Attempt {attempt}/{attempts} failed: {' '.join(argv)} ({result.returncode})")
            if attempt < attempts and delay_ms:
                time.sleep(delay_ms / 1000.0)
        assert last_result is not None
        return last_result

