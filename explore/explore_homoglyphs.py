# -*- coding: utf-8 -*-
"""Навыки-«двойники»: одинаковые после замены кириллических букв-близнецов на латинские."""
import csv
import io
import sys
from collections import defaultdict

sys.path.insert(0, "src")
from common import BUCKET, s3_client  # noqa: E402

CYR2LAT = str.maketrans("асеорхкуітмнв", "aceopxkyitmhb")
body = s3_client().get_object(Bucket=BUCKET, Key="results/mapreduce/skills_k1.csv")["Body"].read().decode()
skills = {r[0]: int(r[1]) for r in list(csv.reader(io.StringIO(body)))[1:]}
groups = defaultdict(list)
for s, n in skills.items():
    groups[s.translate(CYR2LAT)].append((s, n))
for key, g in sorted(groups.items(), key=lambda kv: -sum(n for _, n in kv[1])):
    if len(g) > 1:
        print(key, "<-", g)
