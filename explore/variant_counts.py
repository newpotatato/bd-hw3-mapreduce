# -*- coding: utf-8 -*-
"""Итоговое условие варианта и сравнение с альтернативами."""
import duckdb

CSV = r"C:\obsidian_workspace\university\3_grade\bd\hw_evolution\it_vacancies_2024.csv"
con = duckdb.connect()
con.execute(f"CREATE VIEW v AS SELECT * FROM read_csv_auto('{CSV}', all_varchar=true)")

ROLE = "role = 'Программист, разработчик'"
TITLE = r"regexp_matches(lower(name), '(c#|с#|\.net|dotnet)')"   # латинская c и кириллическая с
TITLE_LATIN = r"regexp_matches(lower(name), '(c#|\.net|dotnet)')"
HAS_SKILLS = "coalesce(key_skills, '') <> ''"

for label, cond in [
    ("роль + C#/.NET в названии (латиница и кириллица) [ИТОГ]", f"{ROLE} AND {TITLE}"),
    ("то же, только латинская c", f"{ROLE} AND {TITLE_LATIN}"),
    ("C#/.NET в названии, любая роль", TITLE),
]:
    n, ns, nsal = con.execute(
        f"SELECT count(*), count(*) FILTER (WHERE {HAS_SKILLS}), "
        f"count(*) FILTER (WHERE currency='RUR' AND (salary_from IS NOT NULL OR salary_to IS NOT NULL)) "
        f"FROM v WHERE {cond}").fetchone()
    print(f"{label}: всего {n}, с навыками {ns}, с зарплатой в RUR {nsal}")

print("\nТоп регионов по итоговому условию:")
for r in con.execute(f"SELECT area, count(*) c FROM v WHERE {ROLE} AND {TITLE} GROUP BY 1 ORDER BY c DESC LIMIT 8").fetchall():
    print(" ", r)
print("\nНавыков в вакансии (итоговое условие, с навыками): мин / медиана / среднее / макс")
print(con.execute(f"SELECT min(n), median(n), round(avg(n),2), max(n) FROM (SELECT len(string_split(key_skills, ';')) n "
                  f"FROM v WHERE {ROLE} AND {TITLE} AND {HAS_SKILLS})").fetchall())
