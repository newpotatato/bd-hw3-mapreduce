# -*- coding: utf-8 -*-
"""Этап 4: построчная сверка результатов MapReduce и DuckDB (оба набора читаются из hh-lake)
и проверка роста числа пар/троек через число сочетаний навыков внутри вакансии."""
import csv
import io
from math import comb

import duckdb

from common import BUCKET, RAW_KEY, VARIANT_SQL, duckdb_s3_setup, s3_client, skill_sql

s3 = s3_client()
NAMES = {1: "skills_k1.csv", 2: "pairs_k2.csv", 3: "triples_k3.csv"}


def load(prefix, k):
    body = s3.get_object(Bucket=BUCKET, Key=f"results/{prefix}/{NAMES[k]}")["Body"].read().decode("utf-8")
    rows = list(csv.reader(io.StringIO(body)))[1:]
    return {tuple(r[:k]): int(r[k]) for r in rows}


print(f"{'k':<3}{'MapReduce: ключей':>19}{'сумма':>9}{'DuckDB: ключей':>16}{'сумма':>9}"
      f"{'только MR':>11}{'только DDB':>12}{'разные числа':>14}")
all_equal = True
for k in (1, 2, 3):
    mr, dd = load("mapreduce", k), load("duckdb", k)
    only_mr, only_dd = mr.keys() - dd.keys(), dd.keys() - mr.keys()
    diff = [key for key in mr.keys() & dd.keys() if mr[key] != dd[key]]
    all_equal &= not (only_mr or only_dd or diff)
    print(f"{k:<3}{len(mr):>19}{sum(mr.values()):>9}{len(dd):>16}{sum(dd.values()):>9}"
          f"{len(only_mr):>11}{len(only_dd):>12}{len(diff):>14}")
print("ИТОГ:", "результаты полностью совпадают" if all_equal else "ЕСТЬ РАСХОЖДЕНИЯ")

# рост числа пар и троек: вакансия с n навыками дает C(n,2) пар и C(n,3) троек
con = duckdb.connect()
duckdb_s3_setup(con)
dist = con.execute(f"""
    SELECT n, count(*) FROM (
        SELECT len(list_distinct(list_filter(list_transform(string_split(key_skills, ';'), lambda s: {skill_sql('s')}),
                                             lambda s: s <> ''))) AS n
        FROM read_csv('s3://{BUCKET}/{RAW_KEY}', header = true, all_varchar = true)
        WHERE {VARIANT_SQL} AND coalesce(key_skills, '') <> '')
    GROUP BY n ORDER BY n""").fetchall()
s1 = sum(n * c for n, c in dist)
s2 = sum(comb(n, 2) * c for n, c in dist)
s3_ = sum(comb(n, 3) * c for n, c in dist)
print()
print("Распределение числа навыков в вакансии (n: вакансий):", ", ".join(f"{n}: {c}" for n, c in dist))
print(f"сумма n = {s1};  сумма C(n,2) = {s2};  сумма C(n,3) = {s3_}")
print(f"вакансия с максимумом навыков (n = {dist[-1][0]}): C(n,2) = {comb(dist[-1][0], 2)}, "
      f"C(n,3) = {comb(dist[-1][0], 3)}")
