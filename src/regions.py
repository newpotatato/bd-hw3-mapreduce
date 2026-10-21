# -*- coding: utf-8 -*-
"""Этап 6: сравнение трех регионов - Москва, Санкт-Петербург, Самара.

Таблица 1 - рынок и зарплаты: число вакансий, опыт, удаленка, медиана и квартили зарплаты.
Таблица 2 - востребованность навыков: топ навыков, пар и троек (доля вакансий региона с навыками).
Таблица 3 - медиана зарплаты по ключевым навыкам в каждом регионе.
Зарплаты считаются так же, как в salary_analysis.py (RUR, на руки, без выбросов, без дублей).
"""
import pathlib

import duckdb

from common import BUCKET, RAW_KEY, VARIANT_SQL, duckdb_s3_setup, skill_sql

ROOT = pathlib.Path(__file__).resolve().parent.parent
REGIONS = ["Москва", "Санкт-Петербург", "Самара"]
fmt = lambda x: "-" if x is None else f"{x:,.0f}".replace(",", " ")
pct = lambda x: f"{100 * x:.1f}%"

con = duckdb.connect()
duckdb_s3_setup(con)
reg_list = ", ".join(f"'{r}'" for r in REGIONS)
con.execute(f"""CREATE TEMP TABLE v AS
SELECT vacancy_id, coalesce(employer_id, 'v' || vacancy_id) AS employer_id, name, area, experience, schedule,
       key_skills, currency,
       CASE WHEN currency = 'RUR' AND (salary_from IS NOT NULL OR salary_to IS NOT NULL) THEN
            CASE WHEN salary_from IS NOT NULL AND salary_to IS NOT NULL
                 THEN (salary_from::DOUBLE + salary_to::DOUBLE) / 2
                 ELSE coalesce(salary_from, salary_to)::DOUBLE END
            * CASE WHEN gross = 'true' THEN 0.87 ELSE 1 END END AS salary
FROM read_csv('s3://{BUCKET}/{RAW_KEY}', header = true, all_varchar = true)
WHERE {VARIANT_SQL}""")
con.execute("UPDATE v SET salary = NULL WHERE salary < 15000 OR salary > 1000000")
# зарплатная выборка без дублей массовых публикаций
con.execute("""CREATE TEMP TABLE sal AS SELECT * FROM v WHERE salary IS NOT NULL
    QUALIFY row_number() OVER (PARTITION BY employer_id, name, salary, coalesce(key_skills, '')
                               ORDER BY vacancy_id) = 1""")
con.execute(f"""CREATE TEMP TABLE sk AS
SELECT DISTINCT vacancy_id, employer_id, area, {skill_sql('x')} AS skill
FROM v, unnest(string_split(coalesce(key_skills, ''), ';')) AS t(x) WHERE lower(trim(x)) <> ''""")
total_all = con.execute("SELECT count(*) FROM v").fetchone()[0]

# ------------------------------------------------------------------ таблица 1
print("ТАБЛИЦА 1. Рынок и зарплаты (вакансии варианта C#/.NET)")
hdr = f"  {'показатель':<42}" + "".join(f"{r:>18}" for r in REGIONS) + f"{'вся Россия':>14}"
print(hdr)
metrics = [
    ("вакансий", "count(*)", "int"),
    ("доля от всех вакансий варианта", f"count(*) / {total_all}", "pct"),
    ("работодателей", "count(DISTINCT employer_id)", "int"),
    ("вакансий на работодателя", "count(*) / count(DISTINCT employer_id)", "f2"),
    ("доля с навыками", "avg((coalesce(key_skills,'') <> '')::INT)", "pct"),
    ("опыт: нет опыта", "avg((experience = 'Нет опыта')::INT)", "pct"),
    ("опыт: 1-3 года", "avg((experience = 'От 1 года до 3 лет')::INT)", "pct"),
    ("опыт: 3-6 лет", "avg((experience = 'От 3 до 6 лет')::INT)", "pct"),
    ("опыт: более 6 лет", "avg((experience = 'Более 6 лет')::INT)", "pct"),
    ("удаленная работа", "avg((schedule = 'Удаленная работа')::INT)", "pct"),
]
for label, expr, kind in metrics:
    vals = [con.execute(f"SELECT {expr} FROM v WHERE area = ?", [r]).fetchone()[0] for r in REGIONS]
    vals.append(con.execute(f"SELECT {expr} FROM v").fetchone()[0])
    f = {"int": fmt, "pct": pct, "f2": lambda x: f"{x:.2f}"}[kind]
    print(f"  {label:<42}" + "".join(f"{f(x):>18}" for x in vals[:-1]) + f"{f(vals[-1]):>14}")
sal_metrics = [
    ("вакансий с зарплатой (без дублей)", "count(*)", fmt),
    ("медиана зарплаты, ₽", "median(salary)", fmt),
    ("25-й перцентиль, ₽", "quantile_cont(salary, 0.25)", fmt),
    ("75-й перцентиль, ₽", "quantile_cont(salary, 0.75)", fmt),
    ("медиана, опыт 1-3 года, ₽", "median(salary) FILTER (WHERE experience = 'От 1 года до 3 лет')", fmt),
    ("медиана, опыт 3-6 лет, ₽", "median(salary) FILTER (WHERE experience = 'От 3 до 6 лет')", fmt),
    ("медиана, удаленка, ₽", "median(salary) FILTER (WHERE schedule = 'Удаленная работа')", fmt),
    ("  вакансий с зарплатой, удаленка", "count(*) FILTER (WHERE schedule = 'Удаленная работа')", fmt),
    ("медиана, офис/гибкий график, ₽", "median(salary) FILTER (WHERE schedule <> 'Удаленная работа')", fmt),
]
for label, expr, f in sal_metrics:
    vals = [con.execute(f"SELECT {expr} FROM sal WHERE area = ?", [r]).fetchone()[0] for r in REGIONS]
    vals.append(con.execute(f"SELECT {expr} FROM sal").fetchone()[0])
    print(f"  {label:<42}" + "".join(f"{f(x):>18}" for x in vals[:-1]) + f"{f(vals[-1]):>14}")

# ------------------------------------------------------------------ таблица 2
print("\nТАБЛИЦА 2. Востребованность навыков: доля вакансий региона с навыками, где встречается сочетание")
for k, title, top in [(1, "навыки", 10), (2, "пары", 5), (3, "тройки", 5)]:
    print(f"\n  {title.upper()} (топ-{top})")
    for r in REGIONS:
        nv = con.execute("SELECT count(DISTINCT vacancy_id) FROM sk WHERE area = ?", [r]).fetchone()[0]
        if k == 1:
            q = "SELECT skill, count(*) FROM sk WHERE area = ? GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT ?"
        elif k == 2:
            q = """SELECT a.skill || ' + ' || b.skill, count(*) FROM sk a JOIN sk b
                   ON a.vacancy_id = b.vacancy_id AND a.skill < b.skill WHERE a.area = ?
                   GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT ?"""
        else:
            q = """SELECT a.skill || ' + ' || b.skill || ' + ' || c.skill, count(*) FROM sk a
                   JOIN sk b ON a.vacancy_id = b.vacancy_id AND a.skill < b.skill
                   JOIN sk c ON b.vacancy_id = c.vacancy_id AND b.skill < c.skill WHERE a.area = ?
                   GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT ?"""
        rows = con.execute(q, [r, top]).fetchall()
        print(f"    {r} ({nv} вакансий с навыками): " +
              "; ".join(f"{s} {c} ({100 * c / nv:.0f}%)" for s, c in rows))

# что отличает регион: навыки, чья доля в регионе сильнее всего выше, чем по всей России
# (не менее 5 вакансий и 3 разных работодателей в регионе - чтобы не ловить одну компанию)
print("\n  ОТЛИЧИТЕЛЬНЫЕ НАВЫКИ: доля в регионе / доля по России "
      "(в регионе >= 5 вакансий у >= 3 работодателей; в скобках - вакансий / работодателей)")
nv_all = con.execute("SELECT count(DISTINCT vacancy_id) FROM sk").fetchone()[0]
for r in REGIONS:
    rows = con.execute(f"""
        WITH reg AS (SELECT skill, count(*) c, count(DISTINCT employer_id) e FROM sk WHERE area = ? GROUP BY 1),
             nreg AS (SELECT count(DISTINCT vacancy_id) n FROM sk WHERE area = ?),
             alls AS (SELECT skill, count(*) c FROM sk GROUP BY 1)
        SELECT reg.skill, reg.c, reg.e, (reg.c / nreg.n) / (alls.c / {nv_all}) AS lift
        FROM reg, nreg, alls WHERE reg.skill = alls.skill AND reg.c >= 5 AND reg.e >= 3
        ORDER BY lift DESC, reg.c DESC LIMIT 6""", [r, r]).fetchall()
    print(f"    {r}: " + "; ".join(f"{s} x{l:.1f} ({c}/{e})" for s, c, e, l in rows))

# ------------------------------------------------------------------ таблица 3
print("\nТАБЛИЦА 3. Медиана зарплаты по ключевым навыкам, ₽ (в скобках - число вакансий без дублей)")
key_skills = ["c#", ".net core", ".net framework", "asp.net", "postgresql", "ms sql", "docker", "rabbitmq",
              "kubernetes", "javascript"]
con.execute(f"""CREATE TEMP TABLE salsk AS SELECT DISTINCT s.vacancy_id, s.area, s.salary, {skill_sql('x')} AS skill
    FROM sal s, unnest(string_split(coalesce(s.key_skills, ''), ';')) AS t(x) WHERE lower(trim(x)) <> ''""")
print(f"  {'навык':<18}" + "".join(f"{r:>20}" for r in REGIONS) + f"{'вся Россия':>18}")
for s in key_skills:
    cells = []
    for r in REGIONS + [None]:
        cond = "skill = ?" + (" AND area = ?" if r else "")
        params = [s] + ([r] if r else [])
        med, n = con.execute(f"SELECT median(salary), count(*) FROM salsk WHERE {cond}", params).fetchone()
        cells.append(f"{fmt(med)} ({n})")
    print(f"  {s:<18}" + "".join(f"{c:>20}" for c in cells[:-1]) + f"{cells[-1]:>18}")
