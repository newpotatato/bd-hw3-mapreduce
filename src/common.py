# -*- coding: utf-8 -*-
"""Общие настройки: подключение к RustFS (S3), условие варианта, нормализация навыков."""
import os
import re

import boto3
from botocore.config import Config

# --- хранилище ---------------------------------------------------------------
S3_ENDPOINT = os.getenv("S3_ENDPOINT", "http://localhost:9000")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "chernikov")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "chernikov-j3310")
BUCKET = "hh-lake"
RAW_KEY = "raw/it_vacancies_2024.csv"

# --- вариант 17: «Программист, разработчик на C# и .NET» ----------------------
VARIANT_ROLE = "Программист, разработчик"
# в названии C# или .NET; «с#» - с кириллической «с» (так написаны ~11% вакансий)
VARIANT_TITLE_RE = re.compile(r"(c#|с#|\.net|dotnet)")
# то же условие для DuckDB (RE2), должно совпадать с Python-версией
VARIANT_SQL = (f"role = '{VARIANT_ROLE}' "
               r"AND regexp_matches(lower(name), '(c#|с#|\.net|dotnet)')")


def is_variant(role: str, name: str) -> bool:
    return role == VARIANT_ROLE and VARIANT_TITLE_RE.search(name.lower()) is not None


# Кириллические буквы-двойники латинских: «с#», «.net сore», «odatа» и т.п. - это те же навыки.
# Если в навыке из кириллицы есть ТОЛЬКО такие буквы, заменяем их на латинские
# («ооп», «работа в команде» содержат другие русские буквы и не меняются).
HOMO_CYR, HOMO_LAT = "асеорхку", "aceopxky"
_HOMO_TR = str.maketrans(HOMO_CYR, HOMO_LAT)
_ANY_CYR = re.compile(r"[а-яё]")
_NON_HOMO_CYR = re.compile(r"[б-дж-йл-нптфц-яё]")


def normalize_skill(s: str) -> str:
    s = s.strip(" ").lower()
    if _ANY_CYR.search(s) and not _NON_HOMO_CYR.search(s):
        s = s.translate(_HOMO_TR)
    return s


def normalize_skills(key_skills: str) -> list[str]:
    """'Git; С#;  .NET ;c#' -> ['.net', 'c#', 'git']: нижний регистр, обрезка пробелов, двойники, без повторов."""
    if not key_skills:
        return []
    return sorted({normalize_skill(s) for s in key_skills.split(";")} - {""})


def skill_sql(x: str) -> str:
    """То же правило нормализации одного навыка на SQL (DuckDB)."""
    s = f"lower(trim({x}))"
    return (f"CASE WHEN regexp_matches({s}, '[а-яё]') AND NOT regexp_matches({s}, '[б-дж-йл-нптфц-яё]') "
            f"THEN translate({s}, '{HOMO_CYR}', '{HOMO_LAT}') ELSE {s} END")


def s3_client():
    return boto3.client(
        "s3", endpoint_url=S3_ENDPOINT, aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY, region_name="us-east-1",
        config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 3},
                      read_timeout=300, connect_timeout=10))


def duckdb_s3_setup(con) -> None:
    """Подключает DuckDB к RustFS через расширение httpfs."""
    con.execute("INSTALL httpfs; LOAD httpfs;")
    host = S3_ENDPOINT.split("://", 1)[1]
    con.execute(f"""
        CREATE OR REPLACE SECRET rustfs (
            TYPE s3, KEY_ID '{S3_ACCESS_KEY}', SECRET '{S3_SECRET_KEY}',
            ENDPOINT '{host}', URL_STYLE 'path', USE_SSL false, REGION 'us-east-1')""")
