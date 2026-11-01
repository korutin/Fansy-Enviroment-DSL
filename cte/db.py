"""Слой доступа к БД: вызов процедур API_* в Firebird.

FirebirdDatabase — реальное подключение (пакет firebird-driver), импорт
ленивый, чтобы движок и парсер можно было использовать/тестировать без
установленного клиента Firebird.

FakeDatabase — для dry-run и unit-тестов: никуда не подключается, просто
журналирует вызовы и отдаёт заранее заданные (scripted) ответы.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


class Database:
    def call(self, proc: str, args: Sequence[Any]) -> Tuple[Any, ...]:
        raise NotImplementedError

    def missing_procedures(self, names: Sequence[str]) -> List[str]:
        """Какие из перечисленных процедур отсутствуют в БД."""
        return []

    def missing_generators(self, names: Sequence[str]) -> List[str]:
        """Какие из перечисленных генераторов отсутствуют в БД."""
        return []

    def next_id(self, generator: str) -> int:
        """Очередное значение генератора (аналог Gen_ID('Данные', <gen>, 1))."""
        raise NotImplementedError

    def current_operator(self) -> Tuple[Optional[int], Optional[int]]:
        """(ID оператора, его PLAN_ID) для текущего пользователя подключения.

        ВЫНУЖДЕННОЕ ОТКЛОНЕНИЕ от правила «только через API_*»: пока нет
        API_INS_CLIENT, вставка идёт напрямую в OD_PR_INSERT_CLIENT, а та
        требует OPER и PLAN_ID входными параметрами, и процедуры, чтобы их
        получить, в платформе нет. Запрос read-only и повторяет логику самой
        платформы (rslv_operator_current_t, API_FIND_CLIENT): оператор ищется
        по USER_ID = текущий пользователь СУБД, с откатом на SYSDABA.
        Когда появится API_INS_CLIENT — этот метод уйдёт.
        """
        raise NotImplementedError

    def commit(self) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


@dataclass
class FakeDatabase(Database):
    """scripted_returns: имя_процедуры -> список кортежей-ответов, отдаваемых
    по очереди при последовательных вызовах этой процедуры. Если ответов
    не хватило или процедура вообще не описана — отдаётся (None, None, None).
    """

    scripted_returns: Dict[str, List[Tuple[Any, ...]]] = field(default_factory=dict)
    calls: List[Tuple[str, Tuple[Any, ...]]] = field(default_factory=list)
    oper_id: Optional[int] = 1
    plan_id: Optional[int] = 100
    next_generated: int = 5000
    _cursors: Dict[str, int] = field(default_factory=dict)

    def current_operator(self) -> Tuple[Optional[int], Optional[int]]:
        return self.oper_id, self.plan_id

    def next_id(self, generator: str) -> int:
        value = self.next_generated
        self.next_generated += 1
        self.calls.append((f"gen_id({generator})", ()))
        return value

    def call(self, proc: str, args: Sequence[Any]) -> Tuple[Any, ...]:
        self.calls.append((proc, tuple(args)))
        queue = self.scripted_returns.get(proc)
        if not queue:
            return (None, None, None)
        idx = self._cursors.get(proc, 0)
        result = queue[idx] if idx < len(queue) else queue[-1]
        self._cursors[proc] = idx + 1
        return result

    def commit(self) -> None:
        pass

    def close(self) -> None:
        pass


class DryRunDatabase(FakeDatabase):
    """База по умолчанию для `cte --dry-run`.

    Имитирует пустую БД: FIND всегда "не найдено", INS уже реализованных
    процедур (API_INS_FACE/API_INS_SHARE/API_INS_ACC/API_INS_A_FACE/
    API_INS_AFFIL и вставка клиента) выдаёт правдоподобный автоинкрементный
    ID, а процедуры-заглушки (см. sql/api_stubs_test_env.sql — сейчас это
    API_UPD_CLIENT/API_UPD_A_FACE/API_UPD_AFFIL) честно возвращают NULL, как
    они и делают на реальном стенде. SET-процедуры (API_SET_*) ID не отдают и
    тоже отвечают пустым кортежем. Так
    дефолтный dry-run сразу показывает, какая часть сценария уже рабочая,
    а какая упирается в нереализованные процедуры — без ручного скриптинга
    ответов, которое нужно для точечных unit-тестов (см. FakeDatabase).
    """

    _IMPLEMENTED_INS = {
        "API_INS_FACE", "API_INS_SHARE", "API_INS_ACC", "OD_PR_INSERT_CLIENT",
        "API_INS_A_FACE", "API_INS_AFFIL",
    }

    def __init__(self):
        super().__init__()
        self._next_id = 1000
        self._created: Dict[Tuple[str, Tuple[Any, ...]], int] = {}
        self._last_find: Optional[Tuple[str, Tuple[Any, ...]]] = None

    def call(self, proc: str, args: Sequence[Any]) -> Tuple[Any, ...]:
        key = (proc, tuple(args))
        self.calls.append(key)
        if proc.startswith("API_FIND_"):
            # если этим прогоном сущность «создана» — повторный поиск её находит
            # (OD_PR_INSERT_CLIENT не возвращает ID, обвес доспрашивает поиском)
            if key in self._created:
                found = self._created[key]
                return (found, str(found))
            self._last_find = key
            return (None, None)
        if proc in self._IMPLEMENTED_INS:
            new_id = self._next_id
            self._next_id += 1
            if self._last_find is not None:
                self._created[self._last_find] = new_id
                self._last_find = None
            return (new_id,)
        # заглушки (API_UPD_CLIENT, ...) и SET-процедуры (API_SET_BANK, ...) — no-op
        return (None, None)


_LIB_HINT = """\
Не удалось загрузить клиентскую библиотеку Firebird ({driver}): {err}

WinError 193 («не является приложением Win32») почти всегда означает
несовпадение разрядности: разрядность Python должна совпадать с разрядностью
fbclient.dll. Проверить Python:  python -c "import struct;print(struct.calcsize('P')*8)"

Для сервера Firebird 2.5 используйте драйвер fdb (pip install fdb) и
32-битный Python, если клиент 32-битный:  --driver fdb
firebird-driver требует клиент Firebird 3.0+ (новый объектный API) и с
библиотекой от 2.5 работать не будет.

Путь к библиотеке можно задать явно переменной окружения FIREBIRD или
аргументом --fb-client."""


def _connect(dsn: str, user: str, password: str, charset: str, driver: str, fb_client: Optional[str]):
    """Подключение через fdb (Firebird 2.5) либо firebird-driver (3.0+).

    driver: 'auto' | 'fdb' | 'firebird-driver'
    """
    order = {
        "auto": ("fdb", "firebird-driver"),
        "fdb": ("fdb",),
        "firebird-driver": ("firebird-driver",),
    }.get(driver)
    if order is None:
        raise ValueError(f"неизвестный драйвер {driver!r} (fdb|firebird-driver|auto)")

    errors = []
    for name in order:
        try:
            if name == "fdb":
                import fdb

                if fb_client:
                    fdb.load_api(fb_client)
                con = fdb.connect(
                    dsn=dsn, user=user, password=password, charset=charset
                )
            else:
                import firebird.driver as fb

                if fb_client:
                    fb.driver_config.fb_client_library.value = fb_client
                con = fb.connect(dsn, user=user, password=password, charset=charset)
            return name, con
        except ImportError as e:
            errors.append(f"{name}: пакет не установлен ({e})")
        except OSError as e:
            raise RuntimeError(_LIB_HINT.format(driver=name, err=e)) from e
    raise RuntimeError(
        "Нет доступного драйвера Firebird. " + "; ".join(errors)
        + ". Для Firebird 2.5: pip install fdb"
    )


class FirebirdDatabase(Database):
    """Реальное подключение к Firebird (fdb или firebird-driver).

    Вызов идёт формой `EXECUTE PROCEDURE NAME ?, ?, ...` — в Firebird это
    работает как для процедур с RETURNS (получаем одну строку результата),
    так и для процедур без RETURNS (результат игнорируется).

    charset по умолчанию WIN1251: базы Fansy и все выгрузки платформы в
    cp1251, при UTF8-подключении к базе с charset NONE кириллица поедет.
    """

    def __init__(
        self,
        dsn: str,
        user: str,
        password: str,
        charset: str = "WIN1251",
        driver: str = "auto",
        fb_client: Optional[str] = None,
    ):
        self.driver, self._con = _connect(dsn, user, password, charset, driver, fb_client)

    def call(self, proc: str, args: Sequence[Any]) -> Tuple[Any, ...]:
        placeholders = ", ".join(["?"] * len(args))
        sql = f"EXECUTE PROCEDURE {proc} {placeholders}".rstrip()
        cur = self._con.cursor()
        try:
            cur.execute(sql, list(args))
            # У процедур без RETURNS набора строк нет: description is None,
            # и fetchone() в fdb на таком операторе бросает DatabaseError.
            if cur.description is None:
                return (None,)
            row = cur.fetchone()
            return tuple(row) if row is not None else (None,)
        except Exception as e:
            shown = ", ".join(
                (repr(a[:80] + "…") if isinstance(a, str) and len(a) > 80 else repr(a))
                for a in args
            )
            raise RuntimeError(f"{proc}({shown}) -> {type(e).__name__}: {e}") from e
        finally:
            cur.close()

    def missing_procedures(self, names: Sequence[str]) -> List[str]:
        cur = self._con.cursor()
        try:
            cur.execute("select trim(rdb$procedure_name) from rdb$procedures")
            existing = {row[0].upper() for row in cur.fetchall() if row[0]}
        finally:
            cur.close()
        return [n for n in names if n.upper() not in existing]

    def next_id(self, generator: str) -> int:
        if not _IDENT_RE.match(generator):
            raise ValueError(f"недопустимое имя генератора: {generator!r}")
        cur = self._con.cursor()
        try:
            cur.execute(f"select gen_id({generator}, 1) from rdb$database")
            return cur.fetchone()[0]
        finally:
            cur.close()

    def missing_generators(self, names: Sequence[str]) -> List[str]:
        cur = self._con.cursor()
        try:
            cur.execute("select trim(rdb$generator_name) from rdb$generators")
            existing = {row[0].upper() for row in cur.fetchall() if row[0]}
        finally:
            cur.close()
        return [n for n in names if n.upper() not in existing]

    def current_operator(self) -> Tuple[Optional[int], Optional[int]]:
        cur = self._con.cursor()
        try:
            cur.execute(
                "select o.ID, o.PLAN_ID from OD_OPERATORS o "
                "where upper(o.USER_ID) = upper(current_user)"
            )
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    "select o.ID, o.PLAN_ID from OD_OPERATORS o "
                    "where upper(o.USER_ID) = 'SYSDBA'"
                )
                row = cur.fetchone()
            return (row[0], row[1]) if row else (None, None)
        finally:
            cur.close()

    def commit(self) -> None:
        self._con.commit()

    def close(self) -> None:
        self._con.close()
