# -*- coding: utf-8 -*-
"""Профилирование: каждая конфигурация запускается отдельным процессом N раз (по умолчанию 3);
время - по часам, пик памяти - максимум суммарного RSS дерева процессов (мастер + мапперы),
замер каждые 25 мс через psutil."""
import argparse
import json
import pathlib
import statistics
import subprocess
import sys
import time

import psutil

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY = sys.executable
CONFIGS = {
    "mr_naive_w1": [PY, "src/mapreduce.py", "--mode", "naive", "--workers", "1", "--out-prefix", "profile/naive_w1"],
    "mr_opt_w1": [PY, "src/mapreduce.py", "--workers", "1", "--out-prefix", "profile/opt_w1"],
    "mr_opt_w4": [PY, "src/mapreduce.py", "--workers", "4", "--out-prefix", "profile/opt_w4"],
    "mr_stream_w1": [PY, "src/mapreduce.py", "--mode", "stream", "--workers", "1", "--out-prefix", "profile/stream_w1"],
    "mr_stream_w4": [PY, "src/mapreduce.py", "--mode", "stream", "--workers", "4", "--out-prefix", "profile/stream_w4"],
    "mr_stream_w8": [PY, "src/mapreduce.py", "--mode", "stream", "--workers", "8", "--out-prefix", "profile/stream_w8"],
    "duckdb": [PY, "src/duckdb_skills.py"],
}


def tree_rss(p):
    total = 0
    try:
        procs = [p] + p.children(recursive=True)
    except psutil.NoSuchProcess:
        return 0
    for q in procs:
        try:
            total += q.memory_info().rss
        except psutil.NoSuchProcess:
            pass
    return total


def run_once(cmd):
    t0 = time.perf_counter()
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    ps = psutil.Process(proc.pid)
    peak = 0
    while proc.poll() is None:
        peak = max(peak, tree_rss(ps))
        time.sleep(0.025)
    out = proc.stdout.read().decode("utf-8", "replace")
    if proc.returncode != 0:
        raise RuntimeError(f"{cmd} failed:\n{out}")
    return time.perf_counter() - t0, peak / 2**20, out


ap = argparse.ArgumentParser()
ap.add_argument("--runs", type=int, default=3)
ap.add_argument("configs", nargs="*", default=list(CONFIGS))
args = ap.parse_args()

results = {}
for name in args.configs:
    times, peaks = [], []
    for i in range(1, args.runs + 1):
        t, m, _ = run_once(CONFIGS[name])
        times.append(t)
        peaks.append(m)
        print(f"{name:<12} попытка {i}: время {t:6.2f} с, пик памяти {m:7.1f} МиБ", flush=True)
    results[name] = {"times": times, "peaks_mib": peaks}

print(f"\n{'конфигурация':<14}{'команда':<52}{'время, с (мин/медиана/макс)':>30}{'пик памяти, МиБ (медиана)':>28}")
for name, r in results.items():
    t = r["times"]
    cmd = " ".join(c for c in CONFIGS[name][1:] if not c.startswith("profile/") and c != "--out-prefix")
    print(f"{name:<14}{cmd:<52}{min(t):>10.2f} /{statistics.median(t):>6.2f} /{max(t):>6.2f}"
          f"{statistics.median(r['peaks_mib']):>28.1f}")
(ROOT / "results" / "profile.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
