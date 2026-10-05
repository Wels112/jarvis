# -*- coding: utf-8 -*-
"""Скачивание больших файлов с докачкой — модель весит полтора гигабайта.

На этой машине интернет идёт через VPN, и длинное соединение рвётся: первая
загрузка модели 05.10.2026 оборвалась на 240 МБ из 1,4 ГБ. Качать заново с нуля
после каждого обрыва — значит не скачать никогда. Поэтому файл пишется в
`.part`, а после обрыва запрос продолжается с того байта, где остановился
(заголовок Range). Готовый файл переименовывается только целиком — недокачанная
модель под настоящим именем выглядела бы рабочей и падала бы при загрузке.
"""
import os
import time
from pathlib import Path

import requests


def fetch(url: str, dest: Path, attempts: int = 30, progress=print) -> Path:
    dest = Path(dest)
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    total = None
    last_report = 0.0

    for attempt in range(1, attempts + 1):
        have = part.stat().st_size if part.exists() else 0
        headers = {"Range": f"bytes={have}-"} if have else {}
        try:
            with requests.get(url, headers=headers, stream=True, timeout=(15, 60)) as r:
                if r.status_code == 416:              # всё уже скачано
                    break
                r.raise_for_status()
                if have and r.status_code != 206:     # сервер не умеет продолжать
                    have = 0
                    part.unlink(missing_ok=True)
                size = r.headers.get("Content-Length")
                if size is not None and total is None:
                    total = have + int(size)
                with open(part, "ab" if have else "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
                        now = time.monotonic()
                        if progress and total and now - last_report > 5:
                            done = part.stat().st_size
                            progress(f"  {done / 1e9:.2f} из {total / 1e9:.2f} ГБ")
                            last_report = now
            if total is None or part.stat().st_size >= total:
                break
        except (requests.RequestException, OSError) as e:
            if progress:
                got = part.stat().st_size if part.exists() else 0
                progress(f"  связь оборвалась на {got / 1e9:.2f} ГБ ({type(e).__name__}), "
                         f"продолжаю — попытка {attempt + 1}")
            time.sleep(min(2 * attempt, 15))
    else:
        raise RuntimeError(f"не скачалось за {attempts} попыток: {url}")

    if total and part.stat().st_size != total:
        raise RuntimeError(f"файл недокачан: {part.stat().st_size} из {total} байт")
    os.replace(part, dest)
    return dest
