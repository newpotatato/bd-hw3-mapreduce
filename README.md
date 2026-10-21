# ДЗ 3: MapReduce и DuckDB по вакансиям C#/.NET

Черников Кирилл Михайлович, группа J3310, вариант 17 — «Программист, разработчик на C# и .NET».

Отчёт: [`Черников_J3310_ДЗ3_MapReduce_DuckDB.pdf`](Черников_J3310_ДЗ3_MapReduce_DuckDB.pdf)

## Что сделано
- RustFS (S3) на 4 дисках, бакет `hh-lake`: датасет в `raw/`, результаты в `results/`.
- Свой MapReduce на Python: читает объект из S3 чанками (Range-запросами), комбайнер, shuffle по `crc32`, параллельные редьюсеры, перезапуск упавшего маппера.
- Тот же подсчёт навыков, пар и троек одним SQL-запросом в DuckDB; построчная сверка результатов (0 расхождений).
- Влияние пар и троек навыков на медианную зарплату (с защитой от массовых публикаций).
- Сравнение регионов: Москва, Санкт-Петербург, Самара.
- Профилирование (3 запуска, время и пик памяти) и оптимизация MapReduce «до/после».

## Структура
| Путь | Назначение |
|---|---|
| `infra/docker-compose.yml` | RustFS: 4 тома-диска, S3 API `:9000`, консоль `:9001` |
| `src/common.py` | настройки S3, условие варианта, нормализация навыков |
| `src/upload.py` | создание бакета `hh-lake` и загрузка датасета |
| `src/mapreduce.py` | собственный MapReduce (режимы `naive`, `optimized`, `stream`) |
| `src/duckdb_skills.py` | подсчёт в DuckDB |
| `src/verify.py` | сверка MapReduce и DuckDB, проверка через число сочетаний |
| `src/salary_analysis.py` | навыки и зарплата |
| `src/regions.py` | региональный анализ |
| `src/profile_runs.py` | профилирование по времени и памяти |
| `explore/` | разведка данных (условие варианта, двойники навыков, работодатели) |
| `outputs/` | выводы всех команд, использованные в отчёте |
| `report/` | исходник отчёта и сборка PDF |

## Запуск
```powershell
docker compose -f infra/docker-compose.yml up -d
python -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt
$py = ".\.venv\Scripts\python.exe"
& $py src/upload.py <путь к it_vacancies_2024.csv>
& $py src/mapreduce.py --mode stream --workers 4
& $py src/mapreduce.py --mode stream --workers 4 --fail-task 3 --out-prefix mapreduce_failtest   # отказ маппера
& $py src/duckdb_skills.py
& $py src/verify.py
& $py src/salary_analysis.py
& $py src/regions.py
& $py src/profile_runs.py --runs 3
```

## Условие варианта
```sql
role = 'Программист, разработчик'
AND regexp_matches(lower(name), '(c#|с#|\.net|dotnet)')   -- вторая «с#» — кириллическая «с»
```
4 356 вакансий, из них 3 345 с навыками.
