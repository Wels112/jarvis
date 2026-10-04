# -*- coding: utf-8 -*-
"""Достаёт авторское содержимое артефакта из опубликованной страницы.

Опубликованный HTML обёрнут служебным runtime-кодом. Для переиздания нужен
только кусок между <body> и </body> — он и есть исходник, который мы пишем.
"""
import re
import sys
from pathlib import Path

src = Path(sys.argv[1])
dst = Path(sys.argv[2])

html = src.read_text(encoding="utf-8", errors="replace")

m = re.search(r"<body>(.*)</body>", html, re.S)
if not m:
    print("не нашёл body — структура страницы изменилась")
    sys.exit(1)

body = m.group(1).strip()
dst.parent.mkdir(parents=True, exist_ok=True)
dst.write_text(body + "\n", encoding="utf-8")
print(f"восстановлено {len(body)} символов → {dst}")
print("начало:", body[:60].replace("\n", " "))
