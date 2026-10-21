# -*- coding: utf-8 -*-
"""Этап 3, способ 2: те же частоты навыков, пар и троек - SQL-запросом DuckDB к объекту в RustFS."""
import json
import pathlib
import time

import duckdb

from common import BUCKET, RAW_KEY, VARIANT_SQL, duckdb_s3_setup, skill_sql

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = f"s3://{BUCKET}/{RAW_KEY}"
OUT = f"s3://{BUCKET}/results/duckdb"

t0 = time.perf_counter()
con = duckdb.connect()
duckdb_s3_setup(con)

# вакансии варианта и их навыки: нижний регистр, обрезка пробелов, без повторов внутри вакансии
con.execute(f"""
CREATE TEMP TABLE skills AS
WITH v AS (
    SELECT vacancy_id, key_skills
    FROM read_csv('{SRC}', header = true, all_varchar = true)
    WHERE {VARIANT_SQL}
)
SELECT DISTINCT vacancy_id, {skill_sql('s')} AS skill
FROM v, unnest(string_split(coalesce(key_skills, ''), ';')) AS t(s)
WHERE lower(trim(s)) <> ''
""")
t_load = time.perf_counter()

queries = {
    1: "SELECT skill AS skill_1, count(*) AS count FROM skills GROUP BY ALL",
    2: """SELECT a.skill AS skill_1, b.skill AS skill_2, count(*) AS count
          FROM skills a JOIN skills b ON a.vacancy_id = b.vacancy_id AND a.skill < b.skill
          GROUP BY ALL""",
    3: """SELECT a.skill AS skill_1, b.skill AS skill_2, c.skill AS skill_3, count(*) AS count
          FROM skills a
          JOIN skills b ON a.vacancy_id = b.vacancy_id AND a.skill < b.skill
          JOIN skills c ON b.vacancy_id = c.vacancy_id AND b.skill < c.skill
          GROUP BY ALL""",
}
names = {1: "skills_k1.csv", 2: "pairs_k2.csv", 3: "triples_k3.csv"}
local = ROOT / "results" / "duckdb"
local.mkdir(parents=True, exist_ok=True)
summary = {}
for k, q in queries.items():
    cols = ", ".join(f"skill_{j + 1}" for j in range(k))
    con.execute(f"CREATE TEMP TABLE r{k} AS {q}")
    con.execute(f"COPY (SELECT * FROM r{k} ORDER BY count DESC, {cols}) TO '{OUT}/{names[k]}' (HEADER)")
    con.execute(f"COPY (SELECT * FROM r{k} ORDER BY count DESC, {cols}) TO '{(local / names[k]).as_posix()}' (HEADER)")
    distinct, total = con.execute(f"SELECT count(*), sum(count) FROM r{k}").fetchone()
    top = con.execute(f"SELECT * FROM r{k} ORDER BY count DESC, {cols} LIMIT 5").fetchall()
    summary[f"k{k}"] = {"distinct": distinct, "total_count": int(total), "top5": top}

vac, with_sk = con.execute(
    f"SELECT count(*), count(*) FILTER (WHERE coalesce(key_skills,'') <> '') "
    f"FROM read_csv('{SRC}', header = true, all_varchar = true) WHERE {VARIANT_SQL}").fetchone()
summary.update(vacancies=vac, with_skills=with_sk, sec_load=round(t_load - t0, 2),
               sec_total=round(time.perf_counter() - t0, 2))
(local / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

print(f"DuckDB {duckdb.__version__}; источник {SRC}")
print(f"чтение + фильтр варианта: {summary['sec_load']} s; всего: {summary['sec_total']} s")
print(f"вакансий варианта: {vac}; с навыками: {with_sk}")
for k in (1, 2, 3):
    s = summary[f"k{k}"]
    print(f"k={k}: уникальных ключей {s['distinct']}, сумма частот {s['total_count']}; топ-3: {s['top5'][:3]}")
print(f"результаты: {OUT}/")
