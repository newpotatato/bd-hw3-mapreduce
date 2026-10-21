# -*- coding: utf-8 -*-
"""Этап 5: какие пары и тройки навыков сильнее всего повышают и понижают медианную зарплату.

Зарплата вакансии: только RUR; середина вилки (или одна граница); gross -> «на руки» (* 0.87);
выбросы вне [15 000; 1 000 000] отброшены.
Прибавка пары (a, b) = медиана(вакансии с a и b) - медиана(вакансии с базовым навыком),
где базовый - БОЛЕЕ ЧАСТЫЙ навык пары (то есть прибавка от добавления менее частого навыка).
Прибавка тройки = медиана(тройки) - медиана(самой частой из трех входящих в нее пар).

Защита от массовых публикаций (по умолчанию):
  * одинаковые вакансии одного работодателя (название, зарплата, навыки) считаются один раз;
  * сочетание попадает в рейтинг, если встречается у >= 10 (пары) / >= 8 (тройки) разных работодателей.
--naive отключает обе защиты (первая версия расчета, для сравнения в отчете).
"""
import argparse
import json
import pathlib

import duckdb

from common import BUCKET, RAW_KEY, VARIANT_SQL, duckdb_s3_setup, skill_sql

ROOT = pathlib.Path(__file__).resolve().parent.parent
ap = argparse.ArgumentParser()
ap.add_argument("--naive", action="store_true")
args = ap.parse_args()
MIN_PAIR, MIN_TRIPLE, TOP = 25, 20, 10
MIN_EMP_PAIR, MIN_EMP_TRIPLE = (0, 0) if args.naive else (10, 8)

con = duckdb.connect()
duckdb_s3_setup(con)
con.execute(f"""
CREATE TEMP TABLE sal AS
SELECT vacancy_id, coalesce(employer_id, 'v' || vacancy_id) AS employer_id, name, area, key_skills,
       CASE WHEN salary_from IS NOT NULL AND salary_to IS NOT NULL
            THEN (salary_from::DOUBLE + salary_to::DOUBLE) / 2
            ELSE coalesce(salary_from, salary_to)::DOUBLE END
       * CASE WHEN gross = 'true' THEN 0.87 ELSE 1 END AS salary
FROM read_csv('s3://{BUCKET}/{RAW_KEY}', header = true, all_varchar = true)
WHERE {VARIANT_SQL} AND currency = 'RUR' AND (salary_from IS NOT NULL OR salary_to IS NOT NULL)
""")
con.execute("DELETE FROM sal WHERE salary < 15000 OR salary > 1000000")
n_before = con.execute("SELECT count(*) FROM sal").fetchone()[0]
if not args.naive:
    con.execute("""CREATE OR REPLACE TEMP TABLE sal AS SELECT * FROM sal
        QUALIFY row_number() OVER (PARTITION BY employer_id, name, salary, coalesce(key_skills, '')
                                   ORDER BY vacancy_id) = 1""")
con.execute(f"""
CREATE TEMP TABLE sk AS
SELECT DISTINCT s.vacancy_id, s.employer_id, s.salary, {skill_sql('x')} AS skill
FROM sal s, unnest(string_split(coalesce(s.key_skills, ''), ';')) AS t(x)
WHERE lower(trim(x)) <> ''
""")
n_sal, med_all = con.execute("SELECT count(*), median(salary) FROM sal").fetchone()
n_sk = con.execute("SELECT count(DISTINCT vacancy_id) FROM sk").fetchone()[0]
fmt = lambda x: f"{x:,.0f}".replace(",", " ")
print(f"режим: {'naive (без защиты от массовых публикаций)' if args.naive else 'с дедупликацией и порогом работодателей'}")
print(f"вакансий варианта с зарплатой в RUR после очистки выбросов: {n_before}; после дедупликации: {n_sal}; "
      f"с навыками: {n_sk}; общая медиана: {fmt(med_all)} ₽")
print(f"пороги: пара n >= {MIN_PAIR} и работодателей >= {MIN_EMP_PAIR}; тройка n >= {MIN_TRIPLE} "
      f"и работодателей >= {MIN_EMP_TRIPLE}")

# частота, число работодателей и медиана для навыков, пар и троек (a < b < c)
con.execute("""CREATE TEMP TABLE s1 AS
    SELECT skill, count(*) n, count(DISTINCT employer_id) ne, median(salary) med FROM sk GROUP BY skill""")
con.execute("""CREATE TEMP TABLE s2 AS
    SELECT a.skill a, b.skill b, count(*) n, count(DISTINCT a.employer_id) ne, median(a.salary) med
    FROM sk a JOIN sk b ON a.vacancy_id = b.vacancy_id AND a.skill < b.skill GROUP BY ALL""")
con.execute("""CREATE TEMP TABLE s3 AS
    SELECT a.skill a, b.skill b, c.skill c, count(*) n, count(DISTINCT a.employer_id) ne, median(a.salary) med
    FROM sk a JOIN sk b ON a.vacancy_id = b.vacancy_id AND a.skill < b.skill
              JOIN sk c ON b.vacancy_id = c.vacancy_id AND b.skill < c.skill GROUP BY ALL""")

# пары: база = более частый навык (при равенстве - по алфавиту), добавленный - второй навык
con.execute(f"""CREATE TEMP TABLE pair_up AS
WITH j AS (
  SELECT p.*, sa.skill sa_skill, sa.n sa_n, sa.med sa_med, sb.skill sb_skill, sb.n sb_n, sb.med sb_med,
         (sa.n > sb.n OR (sa.n = sb.n AND sa.skill < sb.skill)) AS a_is_base
  FROM s2 p JOIN s1 sa ON sa.skill = p.a JOIN s1 sb ON sb.skill = p.b
  WHERE p.n >= {MIN_PAIR} AND p.ne >= {MIN_EMP_PAIR})
SELECT a, b, n, ne, med,
       CASE WHEN a_is_base THEN sa_skill ELSE sb_skill END AS base,
       CASE WHEN a_is_base THEN sa_n ELSE sb_n END AS base_n,
       CASE WHEN a_is_base THEN sa_med ELSE sb_med END AS base_med,
       CASE WHEN a_is_base THEN sb_skill ELSE sa_skill END AS added,
       med - CASE WHEN a_is_base THEN sa_med ELSE sb_med END AS uplift
FROM j""")

# тройки: база = самая частая из трех входящих пар
con.execute(f"""CREATE TEMP TABLE triple_up AS
WITH sub AS (
  SELECT t.a, t.b, t.c, t.n, t.ne, t.med, q.a qa, q.b qb, q.n qn, q.med qmed,
         row_number() OVER (PARTITION BY t.a, t.b, t.c ORDER BY q.n DESC, q.a, q.b) rk
  FROM s3 t JOIN s2 q ON (q.a, q.b) IN ((t.a, t.b), (t.a, t.c), (t.b, t.c))
  WHERE t.n >= {MIN_TRIPLE} AND t.ne >= {MIN_EMP_TRIPLE})
SELECT a, b, c, n, ne, med, qa || ' + ' || qb AS base, qn AS base_n, qmed AS base_med,
       CASE WHEN a NOT IN (qa, qb) THEN a WHEN b NOT IN (qa, qb) THEN b ELSE c END AS added,
       med - qmed AS uplift
FROM sub WHERE rk = 1""")

res = {"mode": "naive" if args.naive else "dedup", "n_salary": n_sal, "n_with_skills": n_sk, "median_all": med_all}
out = ROOT / "results" / ("salary_naive" if args.naive else "salary")
out.mkdir(parents=True, exist_ok=True)
for kind, tbl, cols in [("пары", "pair_up", "a || ' + ' || b"), ("тройки", "triple_up", "a || ' + ' || b || ' + ' || c")]:
    total = con.execute(f"SELECT count(*) FROM {tbl}").fetchone()[0]
    for direction, order in [("ПОВЫШАЮТ", "DESC"), ("ПОНИЖАЮТ", "ASC")]:
        rows = con.execute(f"""SELECT {cols}, n, ne, med, base, base_n, base_med, added, uplift
                               FROM {tbl} ORDER BY uplift {order}, n DESC LIMIT {TOP}""").fetchall()
        print(f"\n{kind.upper()}, которые сильнее всего {direction} медиану (всего сочетаний, прошедших пороги: {total}):")
        print(f"  {'сочетание':<44}{'n':>4}{'раб.':>5}{'медиана':>10}  {'база (более частая)':<32}{'n':>5}"
              f"{'медиана':>10}  {'+ навык':<20}{'прибавка':>10}{'%':>7}")
        for combo, n, ne, med, base, bn, bmed, added, up in rows:
            print(f"  {combo[:43]:<44}{n:>4}{ne:>5}{fmt(med):>10}  {base[:31]:<32}{bn:>5}{fmt(bmed):>10}  "
                  f"{added[:19]:<20}{fmt(up):>10}{up / bmed * 100:>6.1f}%")
        res[f"{tbl}_{direction}"] = rows
    con.execute(f"COPY (SELECT * FROM {tbl} ORDER BY uplift DESC) TO '{(out / (tbl + '.csv')).as_posix()}' (HEADER)")
    if not args.naive:
        con.execute(f"COPY (SELECT * FROM {tbl} ORDER BY uplift DESC) TO 's3://{BUCKET}/results/salary/{tbl}.csv' (HEADER)")

print("\nМедианы самых частых навыков (база для сравнения):")
for skill, n, ne, med in con.execute("SELECT skill, n, ne, med FROM s1 ORDER BY n DESC LIMIT 12").fetchall():
    print(f"  {skill:<28}{n:>5} вакансий {ne:>4} работодателей  медиана {fmt(med):>8}")
(out / "summary.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
