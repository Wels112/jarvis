# -*- coding: utf-8 -*-
"""Код Джарвиса должен разбираться и старым Python 3.10/3.11 — у заказчика может стоять он.

Установщик принимает Python 3.10–3.13, а у разработчика 3.12, где можно больше:
обратный слэш и те же кавычки внутри {…} f-строки, вложенные f-строки. На 3.10
это SyntaxError ещё до запуска. Проверяем токенами: внутри выражения
f-строки не должно быть обратного слэша и кавычки того же вида, что снаружи.

    python tests\\check_py310.py
"""
import io
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIRS = ("core", "skills", "tests", "train", "docs")


def problems(path: Path):
    out = []
    src = path.read_text(encoding="utf-8")
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, SyntaxError) as e:
        return [f"{path}: не разбирается: {e}"]
    for i, tok in enumerate(tokens):
        if tok.type != getattr(tokenize, "FSTRING_START", -1):
            continue
        quote = tok.string.lstrip("rRbBfF")[:1]
        depth, j = 0, i + 1
        while j < len(tokens) and tokens[j].type != tokenize.FSTRING_END:
            t = tokens[j]
            if t.type == tokenize.OP and t.string == "{":
                depth += 1
            elif t.type == tokenize.OP and t.string == "}":
                depth -= 1
            elif depth > 0 and t.type == tokenize.STRING and (quote in t.string or "\\" in t.string):
                out.append(f"{path.relative_to(ROOT)}:{t.start[0]}: {t.string[:40]} внутри f-строки")
            elif (depth > 0 and t.type == getattr(tokenize, "FSTRING_START", -1)
                  and t.string.lstrip("rRbBfF")[:1] == quote):    # в других кавычках 3.10 понимает
                out.append(f"{path.relative_to(ROOT)}:{t.start[0]}: f-строка в тех же кавычках внутри f-строки")
            j += 1
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    found = []
    files = [ROOT / "jarvis.py", ROOT / "setup.py"] + [p for d in DIRS for p in (ROOT / d).rglob("*.py")]
    for path in files:
        found += problems(path)
    for line in found:
        print("НЕТ", line)
    print(f"\nпроверено файлов: {len(files)}, мест только для 3.12: {len(found)}")
    return not found


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
