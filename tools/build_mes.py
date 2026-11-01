# -*- coding: utf-8 -*-
"""Сборка модуля Fansy-SCRIPT из .fsc-файлов в один .mes для загрузки в Admin.

Каждый файл <имя>.fsc каталога модуля - одна функция: сигнатура берётся из
шапки-блока (первая строка шапки после линии из дефисов), тело - весь текст
файла. Модуль называется как каталог (_F_ENVLIGHT). Формат записей выведен по
выгрузкам модулей платформы (metaM__<модуль>_V04_xx.mes):

  - строки "ключ\\Таблица.поле=значение", отсортированы как строки (cp1251);
    начало !MESS_TYPE!=DICFORMS и !TIMESTAMP!, конец "Версия БД", "Выгружал",
    "Формы"; кодировка cp1251, концы строк CR LF; пустые (NULL) поля не пишутся;
  - текст функции построчно в FUNC_BODY.N (пустая строка - пропущенный номер),
    FUNC_BODY.COUNT - число строк, ширина номера - число цифр в COUNT-1;
  - MD5_HASH функции - MD5 строк тела, склеенных через CR LF, в cp1251.

Запуск:  python tools/build_mes.py fsc/_F_ENVLIGHT fsc/metaM__F_ENVLIGHT_V04_60.mes
Номера записей в файле локальные (ключи группировки); загрузка их переназначает.
"""
import argparse
import datetime
import hashlib
import os
import re
import sys

CRLF = "\r\n"
EMPTY_MD5 = "d41d8cd98f00b204e9800998ecf8427e"
DASHES = re.compile(r"^   -{10,}$")


def md5_cp1251(text):
    return hashlib.md5(text.encode("cp1251")).hexdigest()


def read_fsc(path, module):
    """Разобрать .fsc: (имя функции, строки FUNC_HEADER, строки тела)."""
    raw = open(path, "rb").read()
    text = raw.decode("utf-8")
    if text.startswith("﻿"):
        text = text[1:]
    lines = text.replace("\r\n", "\n").split("\n")
    while lines and lines[-1] == "":
        lines.pop()
    name = os.path.splitext(os.path.basename(path))[0]
    if not lines or not lines[0].startswith("/* ---"):
        raise SystemExit(f"{path}: нет шапки-блока в первой строке")
    sig = []
    for ln in lines[1:]:
        if DASHES.match(ln):
            break
        sig.append(ln[3:] if ln.startswith("   ") else ln)
    else:
        raise SystemExit(f"{path}: не найдена линия под сигнатурой")
    prefix = module + "->"
    if not sig or not sig[0].startswith(prefix + name + "("):
        raise SystemExit(f"{path}: сигнатура не начинается с {prefix}{name}(")
    sig[0] = sig[0][len(prefix):]
    return name, sig, lines


def function_records(fid, form_id, name, header, body, comm, stamp, md5_hash=None, extra=None):
    """Строки записи DICMETAF одной функции."""
    out = []
    p = f"{fid}\\DICMETAF."
    # Номера строк дополняются нулями до ширины числа COUNT (по выгрузкам:
    # 9 строк - ширина 1, 10 строк - ширина 2, 16 - 2, 102 - 3); пустые
    # строки в файл не пишутся, но входят в COUNT.
    cw = len(str(len(comm)))
    for i, c in enumerate(comm):
        if c != "":
            out.append(f"{p}COMM.{str(i).zfill(cw)}={c}")
    if comm:
        out.append(f"{p}COMM.COUNT={len(comm)}")
    out.append(f"{p}FORM_NUM={form_id}")
    width = len(str(len(body)))
    for i, b in enumerate(body):
        if b != "":
            out.append(f"{p}FUNC_BODY.{str(i).zfill(width)}={b}")
    out.append(f"{p}FUNC_BODY.COUNT={len(body)}")
    hw = len(str(len(header)))
    for i, h in enumerate(header):
        if h != "":
            out.append(f"{p}FUNC_HEADER.{str(i).zfill(hw)}={h}")
    out.append(f"{p}FUNC_HEADER.COUNT={len(header)}")
    out.append(f"{p}FUNC_ID={name}")
    out.append(f"{p}IS_CANON=0")
    out.append(f"{p}IS_USER=1")
    for k, v in (extra or {}).items():
        out.append(f"{p}{k}={v}")
    out.append(f"{p}MD5_HASH={md5_hash or md5_cp1251(CRLF.join(body))}")
    out.append(f"{p}MD5_STAMP={stamp}")
    return out


def form_records(form_id, module, caption, apps, func_ids, stamp, fields=None):
    """Строки записи DICFORMS модуля (без начального и конечного действий)."""
    p = f"{form_id}\\DICFORMS."
    base = {
        "AUTO_OPEN": "0",
        "AUTO_START": "0",
        "FCAPTION": caption,
        "FCLASS": "T_COND_BODY_F",
        "FIN_ACTION.COUNT": "0",
        "FTYPE": module,
        "INI_ACTION.COUNT": "0",
        "LISTED": "0",
        "MD5_HASH": EMPTY_MD5,
        "MD5_STAMP": stamp,
        "MODAL": "0",
        "MULTIPLE": "0",
        "NODEBUG": "0",
        "PROFILE": "-1",
        "VISIBLE": "1",
        "Приложения": apps,
        "Функции": ";".join(str(i) for i in func_ids),
    }
    base.update(fields or {})
    return [f"{p}{k}={v}" for k, v in base.items()]


def render_mes(lines, form_id, db_version, exporter, from_version, timestamp):
    """Собрать файл: отсортировать строки как строки cp1251, добавить хвост."""
    allv = list(lines)
    allv.append("!MESS_TYPE!=DICFORMS")
    allv.append(f"!TIMESTAMP!={timestamp}")
    allv.append(f"Версия БД={db_version}")
    allv.append(f"Выгружал={exporter} из версии {from_version}")
    allv.append(f"Формы={form_id};")
    allv.sort(key=lambda s: s.encode("cp1251"))
    return (CRLF.join(allv) + CRLF).encode("cp1251")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("module_dir", help="каталог модуля с .fsc (имя каталога = имя модуля)")
    ap.add_argument("out", help="выходной .mes")
    ap.add_argument("--caption", default="Модуль выгрузки объектов в формат env-light")
    ap.add_argument("--apps", default="STANDARD;BALANCE;DEPO;BALTUN;DEPONENT;SPECTRE;REESTR;AGENT;TRUST;")
    ap.add_argument("--db-version", default="V04.60")
    ap.add_argument("--exporter", default="ENV_LIGHT")
    ap.add_argument("--form-id", type=int, default=990000)
    args = ap.parse_args()

    module = os.path.basename(os.path.normpath(args.module_dir))
    names = sorted(f for f in os.listdir(args.module_dir) if f.lower().endswith(".fsc"))
    if not names:
        raise SystemExit("в каталоге нет .fsc")
    now = datetime.datetime.now()
    stamp_date = now.strftime("%d.%m.%Y")
    lines, ids = [], []
    for n, fname in enumerate(names, start=1):
        name, header, body = read_fsc(os.path.join(args.module_dir, fname), module)
        fid = args.form_id + n
        ids.append(fid)
        lines.extend(function_records(fid, args.form_id, name, header, body, [], stamp_date))
    lines.extend(form_records(args.form_id, module, args.caption, args.apps, ids, stamp_date))
    data = render_mes(lines, args.form_id, args.db_version, args.exporter,
                      args.db_version, now.strftime("%d.%m.%Y %H:%M:%S"))
    with open(args.out, "wb") as f:
        f.write(data)
    print(f"{module}: функций {len(names)}, {len(data)} байт -> {args.out}")


if __name__ == "__main__":
    sys.exit(main())
