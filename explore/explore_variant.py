# -*- coding: utf-8 -*-
"""Разведка датасета: как выделить сегмент «Программист, разработчик на C# и .NET»."""
import duckdb

CSV = r"C:\obsidian_workspace\university\3_grade\bd\hw_evolution\it_vacancies_2024.csv"
con = duckdb.connect()
con.execute(f"CREATE VIEW v AS SELECT * FROM read_csv_auto('{CSV}', all_varchar=true)")

print("Всего строк, уникальных vacancy_id, источники:")
print(con.execute("SELECT count(*), count(DISTINCT vacancy_id), string_agg(DISTINCT source, ',') FROM v").fetchall())

print("\nТоп ролей:")
for r in con.execute("SELECT role, count(*) c FROM v GROUP BY 1 ORDER BY c DESC LIMIT 12").fetchall():
    print(r)

name_cs = r"regexp_matches(lower(name), '(c#|\.net|asp\.net|dotnet|\bc sharp\b|blazor|xamarin|unity)')"
skill_cs = r"regexp_matches(lower(key_skills), '(^|;\s*)(c#|\.net|asp\.net|\.net core|\.net framework)(\s*;|$)')"
print("\nC#/.NET в названии:", con.execute(f"SELECT count(*) FROM v WHERE {name_cs}").fetchone())
print("C#/.NET в навыках:", con.execute(f"SELECT count(*) FROM v WHERE {skill_cs}").fetchone())
print("в названии ИЛИ навыках:", con.execute(f"SELECT count(*) FROM v WHERE {name_cs} OR {skill_cs}").fetchone())

print("\nРоли вакансий с C#/.NET в названии:")
for r in con.execute(f"SELECT role, count(*) c FROM v WHERE {name_cs} GROUP BY 1 ORDER BY c DESC LIMIT 8").fetchall():
    print(r)

print("\nПримеры названий с C#/.NET (роль 'Программист, разработчик'):")
for r in con.execute(f"SELECT name FROM v WHERE {name_cs} AND role='Программист, разработчик' USING SAMPLE 15").fetchall():
    print(" ", r[0])

print("\nПримеры названий: навыки C#/.NET есть, а в названии нет:")
for r in con.execute(f"SELECT name, role FROM v WHERE {skill_cs} AND NOT {name_cs} USING SAMPLE 15").fetchall():
    print(" ", r)

print("\nДубликаты vacancy_id (сколько id встречаются >1 раза):",
      con.execute("SELECT count(*) FROM (SELECT vacancy_id FROM v GROUP BY 1 HAVING count(*)>1)").fetchone())
print("Пустые key_skills среди C#/.NET в названии:",
      con.execute(f"SELECT count(*) FILTER (WHERE key_skills IS NULL OR key_skills=''), count(*) FROM v WHERE {name_cs}").fetchone())
print("Валюты / с зарплатой:", con.execute(f"SELECT currency, count(*) FROM v WHERE {name_cs} GROUP BY 1 ORDER BY 2 DESC").fetchall())
