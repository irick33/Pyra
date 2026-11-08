"""Compare fresh process to first paint; does not flush the OS filesystem cache."""
import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("targets", nargs="+")
    parser.add_argument("--samples", type=int, default=7)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    env = os.environ.copy()
    if sys.platform == "linux" and not env.get("DISPLAY"):
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
    results = {"platform": platform.platform(), "python": sys.version, "qt_platform": env.get("QT_QPA_PLATFORM", "native"),
               "method": "Fresh process to first paint marker. OS cache NOT cleared. First sample is not a true cold-boot benchmark.",
               "targets": {}}
    with tempfile.TemporaryDirectory() as folder:
        marker = Path(folder) / "ready.json"
        for target in args.targets:
            path = Path(target).resolve()
            prefix = [sys.executable, str(path)] if path.suffix == ".py" else [str(path)]
            samples = []
            for _ in range(args.samples):
                marker.unlink(missing_ok=True)
                tick = time.perf_counter()
                process = subprocess.Popen([*prefix, "--startup-probe", str(marker)], env=env,
                                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                try:
                    deadline = tick + 30
                    while not marker.exists():
                        if process.poll() is not None:
                            raise RuntimeError(process.stderr.read().decode(errors="replace"))
                        if time.perf_counter() > deadline:
                            raise TimeoutError(str(path))
                        time.sleep(.001)
                    samples.append((time.perf_counter() - tick) * 1000)
                    process.wait(timeout=20)
                    if process.returncode:
                        raise RuntimeError(process.stderr.read().decode(errors="replace"))
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()
                    process.stderr.close()
            results["targets"][target] = {"samples_ms": [round(x, 2) for x in samples],
                "first_sample_ms": round(samples[0], 2), "median_ms": round(statistics.median(samples), 2),
                "max_ms": round(max(samples), 2), "entry_bytes": path.stat().st_size}
    Path(args.output).write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
