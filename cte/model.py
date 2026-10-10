"""Парсер DSL описания тестового окружения Fansy (формат .tenv).

Грамматика:
  - Строка, содержащая '=' — поле; принадлежит ближайшему блоку с меньшим
    отступом. Первый '=' — разделитель, остальное до конца строки — значение.
  - Строка без '=' — заголовок блока: `kind[&alias][: key]`.
    Отступ определяет вложенность: заголовок с отступом больше, чем у
    текущего блока, открывает дочерний блок (коллекцию), меньший или равный —
    закрывает предыдущие.
  - `key` (после двоеточия) — это подтип для верхнеуровневых блоков
    (`face: individual`, `share: stock`) либо ключ элемента коллекции для
    дочерних (`code: nsd`, `activity: clearing`, `attorney: &petrov`).
  - `#...` в начале строки (после отступа) — комментарий на всю строку.
  - `include "путь"` — текстовая подстановка содержимого файла (до разбора).
  - Значение поля, целиком равное `&alias` — ссылка на алиас, резолвится
    движком в ID; частичное вхождение `&` — обычный литеральный символ.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple, Union

# Блоки верхнего уровня — самостоятельные сущности
TOP_LEVEL_KINDS = {"face", "share", "bank_account", "client", "bank", "balance"}

# Дочерние блоки — коллекции атрибутов, принадлежащие родителю
CHILD_KINDS = {"code", "activity", "attorney", "affiliate"}

# Какие дети допустимы у какого родителя
ALLOWED_CHILDREN = {
    "face": {"code", "activity", "attorney"},
    "client": {"affiliate"},
}

ALL_KINDS = TOP_LEVEL_KINDS | CHILD_KINDS

_HEADER_RE = re.compile(
    r"^(?P<kind>[A-Za-z_]\w*)"
    r"(?:\s*&\s*(?P<alias>[A-Za-z_]\w*))?"
    r"(?:\s*:\s*(?P<subtype>&?[\w\-.]+))?"
    r"\s*$"
)
_INCLUDE_RE = re.compile(r'^include\s+"(?P<path>[^"]+)"\s*$')
_ALIAS_VALUE_RE = re.compile(r"^&(?P<alias>[A-Za-z_]\w*)$")


class DslError(Exception):
    def __init__(self, message: str, file: str = "", line: int = 0):
        self.file = file
        self.line = line
        loc = f"{file}:{line}: " if file else (f"строка {line}: " if line else "")
        super().__init__(f"{loc}{message}")


@dataclass
class FieldValue:
    name: str
    raw: str
    is_alias: bool
    alias: Optional[str] = None


@dataclass
class Block:
    kind: str
    alias: Optional[str]
    subtype: Optional[str]
    fields: List[FieldValue] = field(default_factory=list)
    children: List["Block"] = field(default_factory=list)
    file: str = ""
    line: int = 0

    def get(self, name: str) -> Optional[FieldValue]:
        for f in self.fields:
            if f.name == name:
                return f
        return None

    def without(self, *names: str) -> List[FieldValue]:
        skip = set(names)
        return [f for f in self.fields if f.name not in skip]

    @property
    def subtype_is_alias(self) -> bool:
        return bool(self.subtype) and self.subtype.startswith("&")

    @property
    def subtype_alias(self) -> Optional[str]:
        return self.subtype[1:] if self.subtype_is_alias else None


def _read_lines_with_includes(
    path: Path, _seen: Optional[frozenset] = None
) -> List[Tuple[str, str, int]]:
    """Возвращает [(строка, файл, номер_строки)] с уже подставленными include."""
    path = path.resolve()
    seen = _seen or frozenset()
    if path in seen:
        raise DslError(f"циклический include: {path}")
    seen = seen | {path}

    out: List[Tuple[str, str, int]] = []
    text = path.read_text(encoding="utf-8")
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        m = _INCLUDE_RE.match(raw_line.strip())
        if m:
            inc_path = (path.parent / m.group("path")).resolve()
            if not inc_path.exists():
                raise DslError(f"include не найден: {inc_path}", str(path), lineno)
            out.extend(_read_lines_with_includes(inc_path, seen))
        else:
            out.append((raw_line, str(path), lineno))
    return out


def parse_file(path: Union[str, Path]) -> List[Block]:
    return _parse_lines(_read_lines_with_includes(Path(path)))


def parse_text(text: str, file: str = "<string>") -> List[Block]:
    """Разбор из строки, без поддержки include (нет файлового контекста)."""
    lines = [(l, file, i + 1) for i, l in enumerate(text.splitlines())]
    return _parse_lines(lines)


def _make_field(field_line: str, file: str, lineno: int) -> FieldValue:
    name, _, value = field_line.partition("=")
    name = name.strip()
    if not name:
        raise DslError(f"поле без имени: {field_line!r}", file, lineno)
    value = value.lstrip()
    alias_m = _ALIAS_VALUE_RE.match(value.strip())
    if alias_m:
        return FieldValue(name=name, raw=value, is_alias=True, alias=alias_m.group("alias"))
    return FieldValue(name=name, raw=value, is_alias=False)


def _parse_lines(lines: List[Tuple[str, str, int]]) -> List[Block]:
    roots: List[Block] = []
    stack: List[Tuple[int, Block]] = []

    for raw_line, file, lineno in lines:
        if raw_line.strip() == "":
            continue
        stripped = raw_line.strip()
        if stripped.startswith("#"):
            continue
        if _INCLUDE_RE.match(stripped):
            raise DslError(
                "include не подставлен (используйте parse_file, а не parse_text)", file, lineno
            )

        indent = len(raw_line) - len(raw_line.lstrip())

        # закрываем блоки, чей отступ не меньше текущего
        while stack and stack[-1][0] >= indent:
            stack.pop()

        if "=" in stripped:
            if not stack:
                raise DslError("поле встречено до заголовка блока", file, lineno)
            stack[-1][1].fields.append(_make_field(stripped, file, lineno))
            continue

        m = _HEADER_RE.match(stripped)
        if not m:
            raise DslError(f"не удалось разобрать заголовок блока: {stripped!r}", file, lineno)
        kind = m.group("kind")
        if kind not in ALL_KINDS:
            raise DslError(f"неизвестный тип блока: {kind!r}", file, lineno)

        block = Block(
            kind=kind,
            alias=m.group("alias"),
            subtype=m.group("subtype"),
            file=file,
            line=lineno,
        )

        if not stack:
            if kind in CHILD_KINDS:
                parents = sorted(k for k, v in ALLOWED_CHILDREN.items() if kind in v)
                raise DslError(
                    f"блок {kind!r} может быть только вложенным "
                    f"(родитель: {', '.join(parents)})",
                    file, lineno,
                )
            roots.append(block)
        else:
            parent = stack[-1][1]
            allowed = ALLOWED_CHILDREN.get(parent.kind, set())
            if kind not in allowed:
                if allowed:
                    raise DslError(
                        f"блок {kind!r} недопустим внутри {parent.kind!r} "
                        f"(допустимы: {', '.join(sorted(allowed))})",
                        file, lineno,
                    )
                raise DslError(f"блок {parent.kind!r} не имеет вложенных блоков", file, lineno)
            parent.children.append(block)

        stack.append((indent, block))

    return roots
