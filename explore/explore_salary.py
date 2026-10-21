# -*- coding: utf-8 -*-
"""Разведка зарплат и полей для регионального анализа (вакансии варианта)."""
import sys

import duckdb

sys.path.insert(0, "src")
from common import BUCKET, RAW_KEY, VARIANT_SQL, duckdb_s3_setup  # noqa: E402

con = duckdb.connect()
duckdb_s3_setup(con)
con.execute(f"CREATE TEMP TABLE v AS SELECT * FROM read_csv('s3://{BUCKET}/{RAW_KEY}', header=true, all_varchar=true) "
            f"WHERE {VARIANT_SQL}")
q = lambda s: con.execute(s).fetchall()
print("currency x gross:", q("SELECT currency, gross, count(*) FROM v GROUP BY ALL ORDER BY 3 DESC"))
print("from/to заполнены (RUR):", q("SELECT salary_from IS NOT NULL, salary_to IS NOT NULL, count(*) FROM v "
                                    "WHERE currency='RUR' GROUP BY ALL ORDER BY 3 DESC"))
print("квантили точечной оценки (RUR):", q("""
    SELECT quantile_cont(p, [0, 0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99, 1]) FROM (
      SELECT CASE WHEN salary_from IS NOT NULL AND salary_to IS NOT NULL
                  THEN (salary_from::DOUBLE + salary_to::DOUBLE)/2
                  ELSE coalesce(salary_from, salary_to)::DOUBLE END AS p
      FROM v WHERE currency='RUR' AND (salary_from IS NOT NULL OR salary_to IS NOT NULL))"""))
print("experience:", q("SELECT experience, count(*) FROM v GROUP BY ALL ORDER BY 2 DESC"))
print("schedule:", q("SELECT schedule, count(*) FROM v GROUP BY ALL ORDER BY 2 DESC"))
print("регионы М/СПб/Самара:", q("SELECT area, count(*), count(*) FILTER (WHERE currency='RUR'), "
                                 "count(*) FILTER (WHERE coalesce(key_skills,'')<>'') FROM v "
                                 "WHERE area IN ('Москва','Санкт-Петербург','Самара') GROUP BY ALL"))
