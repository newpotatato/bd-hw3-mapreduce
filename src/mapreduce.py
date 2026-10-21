# -*- coding: utf-8 -*-
"""Этап 3: собственный MapReduce - частоты навыков, пар и троек навыков для вакансий варианта.

Данные читаются из RustFS (S3) частями: каждый маппер получает свой диапазон байтов (Range-запрос).
Граница сплита - как в Hadoop TextInputFormat: строка принадлежит сплиту, в котором она начинается;
сплит дочитывает свою последнюю строку за пределами диапазона и пропускает обрывок строки в начале.

Режимы:
  stream    - как optimized, но сплит читается из S3 потоком по 1 МиБ, а строки отбираются по сырым байтам
              до декодирования (в str превращаются только ~2% строк) - меньше памяти и CPU;
  optimized - параллельные мапперы, предфильтр строк, комбайнер в маппере, hash-партиционирование,
              параллельные редьюсеры (по умолчанию);
  naive     - «до оптимизации»: каждая строка разбирается целиком, маппер выдает пары (ключ, 1)
              без комбайнера, shuffle - сортировка всех пар, один редьюсер.

Примеры:
  python src/mapreduce.py --workers 4
  python src/mapreduce.py --mode naive --workers 1
  python src/mapreduce.py --fail-task 3          # тест отказа маппера
"""
import argparse
import csv
import io
import json
import os
import pathlib
import re
import sys
import time
import zlib
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from itertools import combinations

from common import BUCKET, RAW_KEY, VARIANT_ROLE, VARIANT_TITLE_RE, is_variant, normalize_skills, s3_client

ROOT = pathlib.Path(__file__).resolve().parent.parent
LOOKAHEAD = 1 << 20          # сколько байт дочитывать за границей сплита, чтобы закончить строку
MAX_ATTEMPTS = 3
SIZES = (1, 2, 3)            # размер «стека»: навык, пара, тройка
HEADER = ["source", "vacancy_id", "status", "snapshot_date", "published_at", "area", "employer_id",
          "employer_inn", "employer_ogrn", "employer_name", "name", "role", "sphere", "salary_from",
          "salary_to", "currency", "gross", "experience", "schedule", "employment", "key_skills",
          "description", "url"]
I_NAME, I_ROLE, I_SKILLS = HEADER.index("name"), HEADER.index("role"), HEADER.index("key_skills")


# ------------------------------------------------------------------ чтение сплита из S3
def _get(s3, a, b):
    """Байты [a, b] включительно (HTTP Range)."""
    return s3.get_object(Bucket=BUCKET, Key=RAW_KEY, Range=f"bytes={a}-{b}")["Body"].read()


def read_split(s3, start, end, size):
    """Строки, начинающиеся в диапазоне [start, end), целиком."""
    lo = max(0, start - 1)                   # байт перед сплитом: нужен, чтобы понять, начало ли это строки
    hi = min(size, end + LOOKAHEAD)
    buf = _get(s3, lo, hi - 1)
    # конец: первый '\n' на позиции >= end-1 (заканчивает строку, начавшуюся до end)
    while True:
        nl = buf.find(b"\n", end - 1 - lo)
        if nl != -1 or hi >= size:
            break
        new_hi = min(size, hi + LOOKAHEAD)
        buf += _get(s3, hi, new_hi - 1)
        hi = new_hi
    stop = nl + 1 if nl != -1 else len(buf)
    # начало: у сплита 0 - начало файла, иначе первая строка после первого '\n' в позиции >= start-1
    if start == 0:
        begin = 0
    else:
        first = buf.find(b"\n", 0)
        begin = first + 1 if first != -1 else len(buf)
    if begin >= stop:
        return b"", len(buf)
    return buf[begin:stop], len(buf)


def iter_split_lines(s3, start, end, size):
    """Потоковое чтение сплита (режим stream): строки, начинающиеся в [start, end), без загрузки сплита целиком."""
    pos = lo = max(0, start - 1)          # pos - абсолютное смещение начала текущего куска строки
    skip_first = start > 0                # до первого '\n' - хвост строки предыдущего сплита
    tail = b""
    hi = min(size, end + LOOKAHEAD)
    while lo < hi:
        body = s3.get_object(Bucket=BUCKET, Key=RAW_KEY, Range=f"bytes={lo}-{hi - 1}")["Body"]
        for chunk in body.iter_chunks(1 << 20):
            parts = (tail + chunk).split(b"\n")
            tail = parts.pop()
            for line in parts:
                line_start, pos = pos, pos + len(line) + 1
                if skip_first:
                    skip_first = False
                    continue
                if line_start >= end:     # строка начинается в следующем сплите - конец
                    body.close()
                    return
                yield line
        lo, hi = hi, min(size, hi + LOOKAHEAD)   # строка не закончилась до LOOKAHEAD - дочитываем
    if tail and not skip_first and pos < end:
        yield tail


# предфильтр по сырым байтам (режим stream): должен быть строго ШИРЕ точного условия is_variant
ROLE_B = VARIANT_ROLE.encode("utf-8")
TITLE_B = re.compile(rb"(c#|\xd1\x81#|\xd0\xa1#|\.net|dotnet)", re.IGNORECASE)   # \xd1\x81 = «с», \xd0\xa1 = «С»


def map_task_stream(task_id, start, end, size, fail_task, attempt, reducers):
    if task_id == fail_task and attempt == 1:
        raise RuntimeError(f"имитация сбоя маппера {task_id} (попытка {attempt})")
    t0 = time.perf_counter()
    s3 = s3_client()
    stats = Counter()
    combined = {k: Counter() for k in SIZES}
    for line in iter_split_lines(s3, start, end, size):
        stats["lines"] += 1
        if ROLE_B not in line or not TITLE_B.search(line):
            continue
        row = next(csv.reader([line.decode("utf-8")]))
        if len(row) != len(HEADER) or not is_variant(row[I_ROLE], row[I_NAME]):
            continue
        stats["vacancies"] += 1
        skills = normalize_skills(row[I_SKILLS])
        if not skills:
            continue
        stats["with_skills"] += 1
        for k in SIZES:
            combined[k].update(combinations(skills, k))
    parts = [{k: {} for k in SIZES} for _ in range(reducers)]
    for k, cnt in combined.items():
        for key, v in cnt.items():
            parts[zlib.crc32("\x1f".join(key).encode()) % reducers][k][key] = v
    stats["emitted"] = sum(len(c) for c in combined.values())
    stats["bytes_fetched"] = 0
    stats["map_sec"] = round(time.perf_counter() - t0, 3)
    return task_id, parts, dict(stats)


# ------------------------------------------------------------------ map
def _rows(text, prefilter):
    for line in text.splitlines():
        if prefilter:
            # дешевая проверка до разбора CSV: роль и C#/.NET должны встречаться в строке
            if VARIANT_ROLE not in line or not VARIANT_TITLE_RE.search(line.lower()):
                continue
        yield next(csv.reader([line]))


def map_task(task_id, start, end, size, mode, fail_task, attempt, reducers):
    if mode == "stream":
        return map_task_stream(task_id, start, end, size, fail_task, attempt, reducers)
    if task_id == fail_task and attempt == 1:
        raise RuntimeError(f"имитация сбоя маппера {task_id} (попытка {attempt})")
    t0 = time.perf_counter()
    s3 = s3_client()
    data, fetched = read_split(s3, start, end, size)
    text = data.decode("utf-8")
    lines = text.count("\n")
    stats = Counter(lines=lines, bytes_fetched=fetched)
    optimized = mode == "optimized"

    if optimized:
        combined = {k: Counter() for k in SIZES}          # комбайнер: суммирование прямо в маппере
    else:
        emitted = []                                      # naive: список пар (ключ, 1)

    for row in _rows(text, prefilter=optimized):
        if row[:1] == ["source"] or len(row) != len(HEADER):   # заголовок файла
            continue
        if not is_variant(row[I_ROLE], row[I_NAME]):
            continue
        stats["vacancies"] += 1
        skills = normalize_skills(row[I_SKILLS])
        if not skills:
            continue
        stats["with_skills"] += 1
        for k in SIZES:
            if optimized:
                combined[k].update(combinations(skills, k))
            else:
                emitted.extend(((k, key), 1) for key in combinations(skills, k))

    if optimized:
        # партиционирование для shuffle: номер редьюсера = crc32(ключ) mod R
        parts = [{k: {} for k in SIZES} for _ in range(reducers)]
        for k, cnt in combined.items():
            for key, v in cnt.items():
                parts[zlib.crc32("\x1f".join(key).encode()) % reducers][k][key] = v
        out = parts
        stats["emitted"] = sum(len(c) for c in combined.values())
    else:
        out = emitted
        stats["emitted"] = len(emitted)
    stats["map_sec"] = round(time.perf_counter() - t0, 3)
    return task_id, out, dict(stats)


# ------------------------------------------------------------------ reduce
def reduce_partition(r, part_list):
    res = {k: Counter() for k in SIZES}
    for part in part_list:
        for k in SIZES:
            res[k].update(part[k])
    return r, res


# ------------------------------------------------------------------ master
def run(args):
    s3 = s3_client()
    size = s3.head_object(Bucket=BUCKET, Key=RAW_KEY)["ContentLength"]
    chunk = args.chunk_mb * 2**20
    splits = [(i, a, min(size, a + chunk)) for i, a in enumerate(range(0, size, chunk))]
    log = lambda *m: print(*m, flush=True)
    log(f"object s3://{BUCKET}/{RAW_KEY}: {size} bytes; splits: {len(splits)} x {args.chunk_mb} MiB; "
        f"mode={args.mode}; workers={args.workers}; reducers={args.reducers}")

    t_start = time.perf_counter()
    results, stats_all = {}, {}
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        pending = {pool.submit(map_task, i, a, b, size, args.mode, args.fail_task, 1, args.reducers): (i, a, b, 1)
                   for i, a, b in splits}
        while pending:
            for fut in as_completed(list(pending)):
                i, a, b, attempt = pending.pop(fut)
                try:
                    tid, out, st = fut.result()
                    results[tid], stats_all[tid] = out, st
                    if attempt > 1:
                        log(f"  map task {tid}: успешно с попытки {attempt}")
                except Exception as e:                       # отказ маппера -> перезапуск задачи
                    log(f"  map task {i}: ОТКАЗ на попытке {attempt}: {e}")
                    if attempt >= MAX_ATTEMPTS:
                        raise
                    pending[pool.submit(map_task, i, a, b, size, args.mode, args.fail_task, attempt + 1,
                                        args.reducers)] = (i, a, b, attempt + 1)
                break
        t_map = time.perf_counter()

        totals = {k: Counter() for k in SIZES}
        if args.mode in ("optimized", "stream"):
            # shuffle: редьюсер r получает свою партицию от каждого маппера
            futs = [pool.submit(reduce_partition, r, [results[t][r] for t in sorted(results)])
                    for r in range(args.reducers)]
            for f in as_completed(futs):
                _, res = f.result()
                for k in SIZES:
                    totals[k].update(res[k])
        else:
            # naive shuffle: все пары (ключ, 1) в один список, сортировка, группировка подряд идущих ключей
            allpairs = [p for t in sorted(results) for p in results[t]]
            allpairs.sort(key=lambda kv: kv[0])
            prev, acc = None, 0
            for key, v in allpairs:
                if key != prev and prev is not None:
                    totals[prev[0]][prev[1]] = acc
                    acc = 0
                prev, acc = key, acc + v
            if prev is not None:
                totals[prev[0]][prev[1]] = acc
            del allpairs
    t_reduce = time.perf_counter()

    # --------------------------------------------------------------- проверка покрытия и запись
    lines = sum(s["lines"] for s in stats_all.values())
    summary = {
        "mode": args.mode, "workers": args.workers, "splits": len(splits), "reducers": args.reducers,
        "lines_read": lines, "data_rows": lines - 1,
        "vacancies": sum(s.get("vacancies", 0) for s in stats_all.values()),
        "with_skills": sum(s.get("with_skills", 0) for s in stats_all.values()),
        "emitted_from_mappers": sum(s["emitted"] for s in stats_all.values()),
        "distinct": {f"k{k}": len(totals[k]) for k in SIZES},
        "total_count": {f"k{k}": sum(totals[k].values()) for k in SIZES},
        "sec_map": round(t_map - t_start, 2), "sec_reduce": round(t_reduce - t_map, 2),
    }
    out_dir = ROOT / "results" / args.out_prefix
    out_dir.mkdir(parents=True, exist_ok=True)
    names = {1: "skills_k1.csv", 2: "pairs_k2.csv", 3: "triples_k3.csv"}
    for k in SIZES:
        rows = sorted(totals[k].items(), key=lambda kv: (-kv[1], kv[0]))
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow([f"skill_{j + 1}" for j in range(k)] + ["count"])
        w.writerows(list(key) + [v] for key, v in rows)
        body = buf.getvalue().encode("utf-8")
        (out_dir / names[k]).write_bytes(body)
        if not args.no_upload:
            s3.put_object(Bucket=BUCKET, Key=f"results/{args.out_prefix}/{names[k]}", Body=body)
        summary[f"top5_k{k}"] = [[*key, v] for key, v in rows[:5]]
    summary["sec_total"] = round(time.perf_counter() - t_start, 2)
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    if not args.no_upload:
        s3.put_object(Bucket=BUCKET, Key=f"results/{args.out_prefix}/summary.json",
                      Body=json.dumps(summary, ensure_ascii=False, indent=1).encode("utf-8"))

    log(f"map: {summary['sec_map']} s; shuffle+reduce: {summary['sec_reduce']} s; total: {summary['sec_total']} s")
    log(f"строк прочитано мапперами: {lines} (данных {lines - 1}); вакансий варианта: {summary['vacancies']}; "
        f"с навыками: {summary['with_skills']}")
    log(f"пар (ключ, значение) от мапперов: {summary['emitted_from_mappers']}")
    for k in SIZES:
        log(f"k={k}: уникальных ключей {summary['distinct'][f'k{k}']}, сумма частот {summary['total_count'][f'k{k}']}; "
            f"топ-3: {summary[f'top5_k{k}'][:3]}")
    dest = f"s3://{BUCKET}/results/{args.out_prefix}/" if not args.no_upload else str(out_dir)
    log(f"результаты: {dest}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["stream", "optimized", "naive"], default="optimized")
    ap.add_argument("--workers", type=int, default=max(1, min(8, (os.cpu_count() or 2) // 2)))
    ap.add_argument("--reducers", type=int, default=4)
    ap.add_argument("--chunk-mb", type=int, default=64)
    ap.add_argument("--fail-task", type=int, default=-1, help="номер маппера, который упадет на первой попытке")
    ap.add_argument("--out-prefix", default="mapreduce")
    ap.add_argument("--no-upload", action="store_true")
    a = ap.parse_args()
    if a.mode == "naive":
        a.reducers = 1
    sys.exit(run(a))
