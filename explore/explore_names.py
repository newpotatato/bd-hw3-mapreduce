# -*- coding: utf-8 -*-
"""Разведка: примеры названий, вклад отдельных ключевых слов, ложные срабатывания."""
import duckdb

CSV = r"C:\obsidian_workspace\university\3_grade\bd\hw_evolution\it_vacancies_2024.csv"
con = duckdb.connect()
con.execute(f"CREATE VIEW v AS SELECT * FROM read_csv_auto('{CSV}', all_varchar=true) "
            "WHERE role = 'Программист, разработчик'")

print("Сколько дает каждое ключевое слово в названии (роль = Программист, разработчик):")
for kw in ["c#", ".net", "asp.net", "dotnet", "blazor", "xamarin", "unity", "1c", "c++"]:
    n = con.execute("SELECT count(*) FROM v WHERE strpos(lower(name), ?) > 0", [kw]).fetchone()[0]
    print(f"  {kw!r}: {n}")

print("\nСлучайные названия с c# или .net:")
for (n,) in con.execute("SELECT name FROM v WHERE regexp_matches(lower(name), '(c#|\\.net)') "
                        "ORDER BY hash(vacancy_id) LIMIT 20").fetchall():
    print("  ", n)

print("\nНазвания с unity, но без c#/.net:")
for (n,) in con.execute("SELECT name FROM v WHERE strpos(lower(name),'unity')>0 "
                        "AND NOT regexp_matches(lower(name), '(c#|\\.net)') ORDER BY hash(vacancy_id) LIMIT 8").fetchall():
    print("  ", n)

print("\n'.net' внутри других слов (ложные срабатывания?):")
for (n,) in con.execute("SELECT name FROM v WHERE regexp_matches(lower(name), '[a-zа-я0-9]\\.net') "
                        "ORDER BY hash(vacancy_id) LIMIT 10").fetchall():
    print("  ", n)

print("\nНавыки C#/.NET есть, в названии нет - примеры названий:")
for (n,) in con.execute("SELECT name FROM v WHERE regexp_matches(lower(key_skills), '(^|;\\s*)(c#|\\.net|asp\\.net)') "
                        "AND NOT regexp_matches(lower(name), '(c#|\\.net)') ORDER BY hash(vacancy_id) LIMIT 15").fetchall():
    print("  ", n)
