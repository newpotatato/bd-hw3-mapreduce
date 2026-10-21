# -*- coding: utf-8 -*-
"""Проверка: не создают ли «повышающие» пары несколько работодателей с массой одинаковых вакансий."""
import sys

import duckdb

sys.path.insert(0, "src")
from common import BUCKET, RAW_KEY, VARIANT_SQL, duckdb_s3_setup, skill_sql  # noqa: E402

con = duckdb.connect()
duckdb_s3_setup(con)
con.execute(f"""CREATE TEMP TABLE sal AS
SELECT vacancy_id, employer_id, employer_name, name, area, salary_from, salary_to, gross, key_skills,
       CASE WHEN salary_from IS NOT NULL AND salary_to IS NOT NULL THEN (salary_from::DOUBLE + salary_to::DOUBLE)/2
            ELSE coalesce(salary_from, salary_to)::DOUBLE END * CASE WHEN gross='true' THEN 0.87 ELSE 1 END AS salary
FROM read_csv('s3://{BUCKET}/{RAW_KEY}', header=true, all_varchar=true)
WHERE {VARIANT_SQL} AND currency='RUR' AND (salary_from IS NOT NULL OR salary_to IS NOT NULL)""")
con.execute("DELETE FROM sal WHERE salary < 15000 OR salary > 1000000")
con.execute(f"""CREATE TEMP TABLE sk AS SELECT DISTINCT s.*, {skill_sql('x')} AS skill
FROM sal s, unnest(string_split(coalesce(s.key_skills,''), ';')) t(x) WHERE lower(trim(x)) <> ''""")

for a, b in [("solid", "ооп"), ("c#", "ddd"), (".net", "c#"), ("c#", "unity"), ("c#", "css")]:
    print(f"\n=== {a} + {b}: работодатели (вакансий, медиана) ===")
    rows = con.execute("""
        SELECT x.employer_name, x.employer_id, count(*) n, median(x.salary) med,
               min(x.salary_from) f, max(x.salary_to) t, count(DISTINCT x.name) names
        FROM sk x JOIN sk y ON x.vacancy_id = y.vacancy_id
        WHERE x.skill = ? AND y.skill = ? GROUP BY ALL ORDER BY n DESC LIMIT 5""", [a, b]).fetchall()
    for r in rows:
        print("  ", r)

print("\nТоп работодателей по числу вакансий варианта с зарплатой:")
for r in con.execute("SELECT employer_name, employer_id, count(*), median(salary), count(DISTINCT name) "
                     "FROM sal GROUP BY ALL ORDER BY 3 DESC LIMIT 8").fetchall():
    print("  ", r)
