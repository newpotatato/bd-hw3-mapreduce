# -*- coding: utf-8 -*-
"""Скриншоты веб-консоли RustFS: бакет hh-lake, папка results/ и результаты MapReduce."""
import pathlib

from playwright.sync_api import sync_playwright

OUT = pathlib.Path(__file__).resolve().parent.parent / "screenshots"
OUT.mkdir(exist_ok=True)
BASE = "http://localhost:9001"

with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge", headless=True)
    page = b.new_page(viewport={"width": 1440, "height": 760})
    page.goto(BASE, wait_until="networkidle")
    page.fill("#accessKey", "chernikov")
    page.fill("#secretKey", "chernikov-j3310")
    page.click("button[type=submit]")
    page.wait_for_url("**/browser/**", timeout=30000)
    page.wait_for_timeout(4500)
    page.screenshot(path=str(OUT / "01_console_buckets.png"))
    page.goto(BASE + "/rustfs/console/browser/?bucket=hh-lake", wait_until="networkidle")
    page.wait_for_timeout(2500)
    page.screenshot(path=str(OUT / "02_console_hh_lake.png"))
    for folder, name in [("raw/", "03_console_raw.png"), ("results/", "04_console_results.png"),
                         ("mapreduce/", "05_console_results_mapreduce.png")]:
        page.get_by_text(folder, exact=True).first.click()
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2500)
        page.screenshot(path=str(OUT / name))
        print("saved", name, page.url)
        if folder == "raw/":
            page.go_back()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2000)
    b.close()
