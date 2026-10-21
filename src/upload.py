# -*- coding: utf-8 -*-
"""Этап 2: создает бакет hh-lake и загружает датасет вакансий (multipart по 64 МиБ)."""
import pathlib
import sys
import time

from boto3.s3.transfer import TransferConfig

from common import BUCKET, RAW_KEY, s3_client

src = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else
                   r"C:\obsidian_workspace\university\3_grade\bd\hw_evolution\it_vacancies_2024.csv")
s3 = s3_client()

if BUCKET not in [b["Name"] for b in s3.list_buckets().get("Buckets", [])]:
    s3.create_bucket(Bucket=BUCKET)
    print(f"bucket {BUCKET}: создан")
else:
    print(f"bucket {BUCKET}: уже есть")

cfg = TransferConfig(multipart_threshold=64 * 2**20, multipart_chunksize=64 * 2**20, max_concurrency=2)
t = time.perf_counter()
s3.upload_file(str(src), BUCKET, RAW_KEY, Config=cfg)
print(f"upload {src.name} -> s3://{BUCKET}/{RAW_KEY}: {time.perf_counter() - t:.1f} s")

h = s3.head_object(Bucket=BUCKET, Key=RAW_KEY)
print(f"head_object: ContentLength={h['ContentLength']}, ETag={h['ETag']}, LastModified={h['LastModified']}")
print(f"локальный размер: {src.stat().st_size}")
for o in s3.list_objects_v2(Bucket=BUCKET).get("Contents", []):
    print(f"  s3://{BUCKET}/{o['Key']}  {o['Size']}")
