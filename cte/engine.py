"""Оркестратор: превращает дерево Block в последовательность вызовов API_*.

Верхнеуровневые блоки:
  - Первое появление алиаса -> FIND, если не нашли -> INS.
  - Повтор алиаса у ИСТОРИЧЕСКОЙ сущности (face, share) требует as_of и
    вызывает UPD(SELF_ID, as_of, FIELDS); даты as_of строго возрастают.
  - Повтор алиаса у ПЛОСКОЙ сущности (bank_account, client, bank) запрещает
    as_of и вызывает UPD(ID, FIELDS) на месте.
  - Если процедура создания вернула NULL — ошибка выполнения сразу.

Дочерние блоки (коллекции атрибутов) делятся на два класса:
  - БЕЗКЛЮЧЕВЫЕ (code -> OD_FACE_CODERS, activity -> OD_P_FACES): своего ID
    нет, запись сама себе ключ. Одна upsert-процедура API_SET_*, алиас
    запрещён (ссылаться не на что), возвращаемого ID нет.
  - ИДЕНТИФИЦИРУЕМЫЕ (attorney -> OD_A_FACES, affiliate -> OD_AFFILS): есть
    суррогатный ID, поэтому FIND -> INS, алиас разрешён.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import mnemonics as M
from .db import Database
from .model import Block, DslError, FieldValue

BEGINNING_OF_TIME = "1900-01-01"

# Процедуры, которые на стенде пока заглушки (sql/api_stubs_test_env.sql).
# Для безключевых детей возвращаемого значения нет, поэтому молчаливый no-op
# иначе никак не обнаружить — предупреждаем явно.
STUB_PROCS = {
    "API_SET_P_FACE",
    "API_FIND_BANK", "API_INS_BANK", "API_UPD_BANK",
    "API_UPD_CLIENT",
    "API_FIND_A_FACE", "API_INS_A_FACE", "API_UPD_A_FACE",
    "API_FIND_AFFIL", "API_INS_AFFIL", "API_UPD_AFFIL",
}


# Какие процедуры нужны для каждого типа блока: обязательные (без них блок
# не отработает вообще) и опциональные (нужны только при повторном объявлении
# блока, то есть при обновлении).
REQUIRED_PROCS = {
    "face": (("API_FIND_FACE", "API_INS_FACE"), ("API_UPD_FACE",)),
    "share": (("API_FIND_SHARE", "API_INS_SHARE"), ("API_UPD_SHARE",)),
    "bank_account": (("API_FIND_ACC", "API_INS_ACC"), ("API_UPD_ACC",)),
    "client": (("API_FIND_CLIENT", "OD_PR_INSERT_CLIENT"), ("API_UPD_CLIENT",)),
    "bank": (("API_FIND_BANK", "API_INS_BANK"), ("API_UPD_BANK",)),
    "code": (("API_SET_FC_CODE",), ()),
    "activity": (("API_SET_P_FACE",), ()),
    "attorney": (("API_FIND_A_FACE", "API_INS_A_FACE"), ("API_UPD_A_FACE",)),
    "affiliate": (("API_FIND_AFFIL", "API_INS_AFFIL"), ("API_UPD_AFFIL",)),
}


REQUIRED_GENERATORS = {"client": ("OD_CLIENTS_ID_GEN",)}


def required_generators(blocks: List[Block]) -> List[str]:
    """Генераторы, из которых обвес будет брать идентификаторы."""
    found = set()

    def walk(bs: List[Block]):
        for b in bs:
            found.update(REQUIRED_GENERATORS.get(b.kind, ()))
            walk(b.children)

    walk(blocks)
    return sorted(found)


def required_procedures(blocks: List[Block]):
    """(обязательные, опциональные) процедуры для сценария.

    Опциональные — только те, что реально понадобятся: UPD нужен, если блок
    с тем же алиасом объявлен повторно.
    """
    required, optional = set(), set()
    seen_aliases = set()

    def walk(bs: List[Block]):
        for b in bs:
            req, opt = REQUIRED_PROCS.get(b.kind, ((), ()))
            required.update(req)
            key = (b.kind, b.alias)
            if b.alias and key in seen_aliases:
                optional.update(opt)
            seen_aliases.add(key)
            walk(b.children)

    walk(blocks)
    return sorted(required), sorted(optional - required)


@dataclass
class AliasState:
    kind: str
    id: Optional[int]
    last_as_of: Optional[str] = None


class Engine:
    def __init__(self, db: Database):
        self.db = db
        self.aliases: Dict[str, AliasState] = {}
        self.log: List[str] = []
        self.warnings: List[str] = []
        self._operator = None

    def operator(self):
        """(OPER, PLAN_ID) текущего пользователя подключения, с кэшированием."""
        if self._operator is None:
            self._operator = self.db.current_operator()
        return self._operator

    # ---------- вызов процедур ----------

    def call(self, proc: str, args: list, block: Optional[Block] = None):
        if proc in STUB_PROCS:
            where = f" ({block.file}:{block.line})" if block else ""
            msg = f"{proc} — заглушка, реального действия не произошло{where}"
            if msg not in self.warnings:
                self.warnings.append(msg)
        return self.db.call(proc, args)

    def find_one(self, proc: str, args: list, block: Block, what: str) -> Optional[int]:
        """Вызов API_FIND_* с обработкой неоднозначности.

        Процедуры поиска платформы возвращают (ID, MULTI_ID): если под условие
        подходит несколько записей, ID НЕ заполняется, а MULTI_ID содержит их
        список через запятую. Трактовать это как «не найдено» нельзя — обвес
        создал бы дубль поверх уже существующих записей.
        """
        result = self.call(proc, args, block)
        found = result[0]
        multi = result[1] if len(result) > 1 else None
        if found is None and multi:
            raise DslError(
                f"{what}: под условие поиска подходит несколько записей "
                f"(ID: {multi}) — уточните ключевые поля в сценарии",
                block.file, block.line,
            )
        return found

    # ---------- разрешение значений полей (алиасы -> ID) ----------

    def resolve_value(self, fv: FieldValue, block: Block) -> str:
        if not fv.is_alias:
            return fv.raw
        return str(self.resolve_alias(fv.alias, block))

    def resolve_alias(self, alias: str, block: Block) -> int:
        state = self.aliases.get(alias)
        if state is None:
            raise DslError(f"неизвестный алиас &{alias}", block.file, block.line)
        if state.id is None:
            raise DslError(
                f"алиас &{alias} ({state.kind}) не имеет ID — вероятно, процедура "
                f"создания для '{state.kind}' ещё не реализована (заглушка)",
                block.file, block.line,
            )
        return state.id

    def fields_to_text(self, fields: List[FieldValue], block: Block) -> str:
        return "\n".join(f"{fv.name}={self.resolve_value(fv, block)}" for fv in fields)

    def field_value(self, block: Block, name: str, required: bool = False) -> Optional[str]:
        fv = block.get(name)
        if fv is None:
            if required:
                raise DslError(f"обязательное поле {name} отсутствует", block.file, block.line)
            return None
        return self.resolve_value(fv, block)

    # ---------- обработка блоков ----------

    def process(self, block: Block) -> None:
        if block.kind == "balance":
            raise DslError(
                "тип блока 'balance' пока не поддерживается (в разработке)", block.file, block.line
            )

        handler = _HANDLERS.get(block.kind)
        if handler is None:
            raise DslError(f"нет обработчика для типа блока {block.kind!r}", block.file, block.line)

        as_of_fv = block.get("as_of")
        as_of = as_of_fv.raw.strip() if as_of_fv else None

        if block.alias and block.alias in self.aliases:
            state = self.aliases[block.alias]
            if state.kind != block.kind:
                raise DslError(
                    f"алиас &{block.alias} уже занят типом '{state.kind}', "
                    f"повторно используется как '{block.kind}'",
                    block.file, block.line,
                )
            handler.revise(self, block, state, as_of)
            parent_id = state.id
        else:
            if as_of is not None:
                raise DslError("as_of недопустим при первом объявлении блока", block.file, block.line)
            new_id = handler.create(self, block)
            if new_id is None:
                raise DslError(
                    f"создание '{block.kind}' не удалось — процедура API вернула NULL "
                    f"(заглушка не реализована или не разрешена зависимость, "
                    f"например банк по BIC ещё не существует)",
                    block.file, block.line,
                )
            state = AliasState(kind=block.kind, id=new_id, last_as_of=None)
            if block.alias:
                self.aliases[block.alias] = state
            self.log.append(f"{block.kind} &{block.alias or '-'} -> ID={new_id}")
            parent_id = new_id

        for child in block.children:
            self._process_child(parent_id, child)

    def _process_child(self, parent_id: int, block: Block) -> None:
        handler = _CHILD_HANDLERS.get(block.kind)
        if handler is None:
            raise DslError(f"нет обработчика для блока {block.kind!r}", block.file, block.line)

        if block.get("as_of") is not None:
            raise DslError(
                f"as_of недопустим у вложенного блока '{block.kind}' — "
                f"даты задаются обычными полями (B_DATE/E_DATE/BEG_LIC)",
                block.file, block.line,
            )

        if block.alias:
            if handler.keyless:
                raise DslError(
                    f"блок '{block.kind}' не имеет собственного ID, алиас невозможен",
                    block.file, block.line,
                )
            if block.alias in self.aliases:
                raise DslError(
                    f"повторное объявление вложенного блока &{block.alias} не поддерживается",
                    block.file, block.line,
                )

        child_id = handler.ensure(self, parent_id, block)

        if handler.keyless:
            self.log.append(f"  {block.kind}:{block.subtype} -> upsert (parent={parent_id})")
        else:
            if child_id is None:
                raise DslError(
                    f"создание '{block.kind}' не удалось — процедура API вернула NULL "
                    f"(вероятно, ещё не реализована)",
                    block.file, block.line,
                )
            if block.alias:
                self.aliases[block.alias] = AliasState(kind=block.kind, id=child_id)
            self.log.append(
                f"  {block.kind} &{block.alias or '-'} -> ID={child_id} (parent={parent_id})"
            )

    def run(self, blocks: List[Block]) -> None:
        for block in blocks:
            self.process(block)


# ---------------------- обработчики верхнеуровневых блоков ----------------------


class Handler:
    historical: bool = False

    def create(self, engine: Engine, block: Block) -> Optional[int]:
        raise NotImplementedError

    def revise(self, engine: Engine, block: Block, state: AliasState, as_of: Optional[str]) -> None:
        if self.historical:
            if as_of is None:
                raise DslError(
                    "для повторного блока исторической сущности нужен as_of", block.file, block.line
                )
            if state.last_as_of is not None and as_of <= state.last_as_of:
                raise DslError(
                    f"as_of={as_of} должен быть позже предыдущей версии ({state.last_as_of})",
                    block.file, block.line,
                )
            self._update_historical(engine, block, state, as_of)
            state.last_as_of = as_of
            engine.log.append(f"{block.kind} &{block.alias} as_of={as_of} -> UPD (SELF_ID={state.id})")
        else:
            if as_of is not None:
                raise DslError(
                    f"as_of недопустим для плоской сущности '{block.kind}'", block.file, block.line
                )
            self._update_flat(engine, block, state)
            engine.log.append(f"{block.kind} &{block.alias} -> UPD (ID={state.id})")

    def _update_historical(self, engine: Engine, block: Block, state: AliasState, as_of: str) -> None:
        raise NotImplementedError

    def _update_flat(self, engine: Engine, block: Block, state: AliasState) -> None:
        raise NotImplementedError


class FaceHandler(Handler):
    historical = True

    def create(self, engine: Engine, block: Block) -> Optional[int]:
        if block.subtype not in M.FACE_IS_JURIC:
            raise DslError(
                f"face: неизвестный subtype {block.subtype!r} (individual|juridical)",
                block.file, block.line,
            )
        is_juric = M.FACE_IS_JURIC[block.subtype]
        fields_text = engine.fields_to_text(block.without("as_of"), block)
        self_id = engine.find_one("API_FIND_FACE", [fields_text], block, "face")
        if self_id is None:
            result = engine.call("API_INS_FACE", [is_juric, BEGINNING_OF_TIME, fields_text], block)
            return result[0]
        return self_id

    def _update_historical(self, engine: Engine, block: Block, state: AliasState, as_of: str) -> None:
        fields_text = engine.fields_to_text(block.without("as_of"), block)
        engine.call("API_UPD_FACE", [state.id, as_of, fields_text], block)


class ShareHandler(Handler):
    historical = True

    def create(self, engine: Engine, block: Block) -> Optional[int]:
        sysname = engine.field_value(block, "SYSNAME", required=True)
        issuer = engine.field_value(block, "ISSUER", required=True)
        if block.subtype not in M.SHARE_CLASS:
            raise DslError(f"share: неизвестный subtype {block.subtype!r}", block.file, block.line)
        klass = M.SHARE_CLASS[block.subtype]
        fields_text = engine.fields_to_text(block.without("as_of", "SYSNAME", "ISSUER"), block)
        share_id = engine.find_one("API_FIND_SHARE", [fields_text], block, "share")
        if share_id is None:
            result = engine.call("API_INS_SHARE", [sysname, int(issuer), klass, fields_text], block)
            return result[0]
        return share_id

    def _update_historical(self, engine: Engine, block: Block, state: AliasState, as_of: str) -> None:
        fields_text = engine.fields_to_text(block.without("as_of", "SYSNAME", "ISSUER"), block)
        engine.call("API_UPD_SHARE", [state.id, as_of, fields_text], block)


class BankAccountHandler(Handler):
    historical = False

    def create(self, engine: Engine, block: Block) -> Optional[int]:
        acnt = engine.field_value(block, "ACNT", required=True)
        bic = engine.field_value(block, "BIC", required=True)
        fields_text = engine.fields_to_text(block.without("as_of", "ACNT", "BIC"), block)
        result = engine.call("API_FIND_ACC", [acnt, bic, fields_text], block)
        acc_id = result[0]
        if acc_id is None:
            result = engine.call("API_INS_ACC", [acnt, bic, fields_text], block)
            return result[0]
        return acc_id

    def _update_flat(self, engine: Engine, block: Block, state: AliasState) -> None:
        # ACNT не выделяем — API_UPD_ACC сам разбирает ACNT из FIELDS
        fields_text = engine.fields_to_text(block.without("as_of"), block)
        engine.call("API_UPD_ACC", [state.id, fields_text], block)


class ClientHandler(Handler):
    """Лицевой счёт — OD_CLIENTS.

    Поиск: API_FIND_CLIENT(NUMBER, FIELDS) -> (ID, MULTI_ID). Из FIELDS
    понимает PLAN_ID, ISSUER, STATE (все опционально); если PLAN_ID не задан,
    берёт его из записи оператора в OD_OPERATORS по текущему пользователю
    подключения — то есть план счетов в сценарии обычно указывать не нужно.

    Вставка: API_INS_CLIENT пока НЕ СУЩЕСТВУЕТ, поэтому зовём платформенную
    OD_PR_INSERT_CLIENT напрямую. Два следствия:
      - ID берётся из генератора OD_CLIENTS_ID_GEN ДО вызова и передаётся
        параметром (аналог Gen_ID('Данные','OD_CLIENTS_ID_GEN',1) в
        Fansy-SCRIPT): у процедуры нет RETURNS, сама она ID не отдаёт, а он
        нужен и для алиаса, и для дочерних affiliate;
      - OPER и PLAN_ID у неё обязательные входные параметры, поэтому их
        приходится читать из OD_OPERATORS (см. Database.current_operator).
    Умолчания ниже повторяют DEFAULT-ы самой таблицы OD_CLIENTS — именно на
    них опирался прикладной ups_client_t, который вставлял запись без этих
    колонок.
    """

    historical = False

    # генератор идентификаторов лицевого счёта
    GENERATOR = "OD_CLIENTS_ID_GEN"

    # поля, которые API_FIND_CLIENT понимает в своём FIELDS
    FIND_FIELDS = ("PLAN_ID", "ISSUER", "STATE")

    # Позиционные параметры OD_PR_INSERT_CLIENT со значениями по умолчанию.
    # Порядок ЗНАЧИМ и должен совпадать с сигнатурой OD_PR_INSERT_CLIENT в
    # Fansy-Foundation/dBase/proc.sql.
    INSERT_PARAMS = (
        ("ID", None),            # подставляется из генератора
        ("NUMBER", None),        # подставляется явно
        ("TYPE_", 2),            # конвенция (см. ups_client_t); влияет на OD_CLIENTS_REC
        ("SUBTYPE", None),       # из subtype блока
        ("FACE", None),          # из поля FACE
        ("RELATION", 0),
        ("PARENT", None),
        ("PLAN_ID", None),       # из поля либо от оператора
        ("IS_TERM", "T"),
        ("IS_MANAGER", 1),
        ("IS_VOICE", 1),
        ("IS_PRIV", 0),
        ("IS_SOV", 0),
        ("IS_NZ", 0),
        ("IS_BCLIENT", 0),
        ("STATE", 0),
        ("D_OPEN", None),        # null -> процедура поставит GETDATE()
        ("D_CLOSE", None),
        ("Z_DATE", None),
        ("OPER", None),          # от оператора
        ("NAME", None),
        ("LINK_NUMBER", None),
        ("INCOME_MOD", None),
        ("INCOME_ACC", None),
        ("INCOME_ADR", None),
        ("INCOME_REC", None),
        ("INCOME_FACE", None),
        ("INCOME_VERBAL", None),
        ("O_MAIL_MOD", None),
        ("O_MAIL_ADR", None),
        ("I_MAIL_MOD", None),
        ("I_MAIL_ALT", None),
        ("I_MAIL_ADR", None),
        ("DD_DATE", None),
        ("DD_NUM", None),
        ("PLACE", None),
        ("ISSUER", None),
        ("TARIF", None),
        ("EXTRA_INT", None),
        ("EXTRA_TYPE", None),
    )

    INT_PARAMS = {
        "TYPE_", "SUBTYPE", "FACE", "RELATION", "PARENT", "PLAN_ID", "IS_MANAGER",
        "IS_VOICE", "IS_PRIV", "IS_SOV", "IS_NZ", "IS_BCLIENT", "STATE", "OPER",
        "INCOME_MOD", "INCOME_ACC", "INCOME_FACE", "O_MAIL_MOD", "I_MAIL_MOD",
        "I_MAIL_ALT", "PLACE", "ISSUER", "EXTRA_INT", "EXTRA_TYPE",
    }

    def create(self, engine: Engine, block: Block) -> Optional[int]:
        number = engine.field_value(block, "NUMBER", required=True)
        face = engine.field_value(block, "FACE", required=True)
        if block.subtype not in M.REESTR_SUBTYPE:
            raise DslError(f"client: неизвестный subtype {block.subtype!r}", block.file, block.line)
        subtype = M.REESTR_SUBTYPE[block.subtype]

        find_text = engine.fields_to_text(
            [fv for fv in block.fields if fv.name in self.FIND_FIELDS], block
        )
        client_id = engine.find_one("API_FIND_CLIENT", [number, find_text], block, "client")
        if client_id is not None:
            return client_id

        oper_id, oper_plan_id = engine.operator()
        given = {fv.name: engine.resolve_value(fv, block) for fv in block.without("as_of")}
        # ID берём из генератора заранее: OD_PR_INSERT_CLIENT не возвращает его
        # наружу, а он нужен и для алиаса, и для дочерних affiliate
        new_id = engine.db.next_id(self.GENERATOR)
        forced = {
            "ID": new_id,
            "NUMBER": number,
            "SUBTYPE": subtype,
            "FACE": face,
            "OPER": oper_id,
            "PLAN_ID": given.get("PLAN_ID", oper_plan_id),
        }

        args = []
        for name, default in self.INSERT_PARAMS:
            value = forced.get(name, given.get(name, default))
            if name in self.INT_PARAMS and isinstance(value, str):
                value = int(value) if value.strip() != "" else None
            args.append(value)

        if args[self._index("PLAN_ID")] is None:
            raise DslError(
                "client: не удалось определить PLAN_ID — задайте его полем "
                "PLAN_ID или убедитесь, что пользователь подключения есть "
                "в OD_OPERATORS с заполненным PLAN_ID",
                block.file, block.line,
            )
        if args[self._index("OPER")] is None:
            raise DslError(
                "client: не удалось определить оператора (OPER) — пользователя "
                "подключения нет в OD_OPERATORS",
                block.file, block.line,
            )

        engine.call("OD_PR_INSERT_CLIENT", args, block)
        return new_id

    @classmethod
    def _index(cls, name: str) -> int:
        return [n for n, _ in cls.INSERT_PARAMS].index(name)

    def _update_flat(self, engine: Engine, block: Block, state: AliasState) -> None:
        fields_text = engine.fields_to_text(block.without("as_of", "NUMBER", "FACE"), block)
        engine.call("API_UPD_CLIENT", [state.id, fields_text], block)


class BankHandler(Handler):
    historical = False

    def create(self, engine: Engine, block: Block) -> Optional[int]:
        bic = engine.field_value(block, "BIC", required=True)
        fields_text = engine.fields_to_text(block.without("as_of", "BIC"), block)
        result = engine.call("API_FIND_BANK", [bic], block)
        bank_id = result[0]
        if bank_id is None:
            result = engine.call("API_INS_BANK", [bic, fields_text], block)
            return result[0]
        return bank_id

    def _update_flat(self, engine: Engine, block: Block, state: AliasState) -> None:
        fields_text = engine.fields_to_text(block.without("as_of", "BIC"), block)
        engine.call("API_UPD_BANK", [state.id, fields_text], block)


# ---------------------------- обработчики детей ----------------------------


class ChildHandler:
    keyless: bool = False

    def ensure(self, engine: Engine, parent_id: int, block: Block) -> Optional[int]:
        raise NotImplementedError


class CodeHandler(ChildHandler):
    """Код лица у кодировщика — OD_FACE_CODERS, PK(CODER,FACE).

    API_SET_FC_CODE(SELF_ID, CODER, FIELDS): CODER задаётся мнемоникой
    кодировщика либо его SELF_ID (тогда в сценарии — `code: &alias`).
    """

    keyless = True

    def ensure(self, engine: Engine, parent_id: int, block: Block) -> Optional[int]:
        if not block.subtype:
            raise DslError("code: не указан кодировщик (code: <мнемоника|&алиас>)", block.file, block.line)
        coder = (
            str(engine.resolve_alias(block.subtype_alias, block))
            if block.subtype_is_alias
            else block.subtype
        )
        if block.get("CODE") is None:
            raise DslError("code: обязательное поле CODE отсутствует", block.file, block.line)
        fields_text = engine.fields_to_text(block.fields, block)
        engine.call("API_SET_FC_CODE", [parent_id, coder, fields_text], block)
        return None


class ActivityHandler(ChildHandler):
    """Вид деятельности (лицензия) — OD_P_FACES, UNIQUE(FACE,DIAL_MODE,BEG_LIC)."""

    keyless = True

    def ensure(self, engine: Engine, parent_id: int, block: Block) -> Optional[int]:
        if not block.subtype:
            raise DslError(
                "activity: не указан вид деятельности (activity: <мнемоника|номер>)",
                block.file, block.line,
            )
        key = block.subtype
        if key.isdigit():
            dial_mode = int(key)
        elif key in M.DIAL_MODE:
            dial_mode = M.DIAL_MODE[key]
        else:
            raise DslError(
                f"activity: неизвестный вид деятельности {key!r} "
                f"(мнемоника из DIAL_MODE или число)",
                block.file, block.line,
            )
        fields_text = engine.fields_to_text(block.fields, block)
        engine.call("API_SET_P_FACE", [parent_id, dial_mode, fields_text], block)
        return None


class AttorneyHandler(ChildHandler):
    """Уполномоченное лицо — OD_A_FACES, ключ (FACE, WORKER, IS_A=1).

    `attorney: &alias` — уполномоченный есть в справочнике лиц (WORKER);
    `attorney` без ключа — только NAME, лица в системе нет.
    """

    keyless = False

    def ensure(self, engine: Engine, parent_id: int, block: Block) -> Optional[int]:
        worker = None
        if block.subtype:
            if not block.subtype_is_alias:
                raise DslError(
                    f"attorney: ключ должен быть ссылкой на лицо (&алиас), "
                    f"получено {block.subtype!r}",
                    block.file, block.line,
                )
            worker = engine.resolve_alias(block.subtype_alias, block)
        name = engine.field_value(block, "NAME")
        if worker is None and not name:
            raise DslError(
                "attorney: нужен либо ключ &алиас (WORKER), либо поле NAME",
                block.file, block.line,
            )
        result = engine.call("API_FIND_A_FACE", [parent_id, worker, name], block)
        a_id = result[0]
        if a_id is None:
            fields_text = engine.fields_to_text(block.fields, block)
            result = engine.call("API_INS_A_FACE", [parent_id, worker, fields_text], block)
            return result[0]
        return a_id


class AffiliateHandler(ChildHandler):
    """Аффилированное лицо — OD_AFFILS, висит на ЛИЦЕВОМ СЧЁТЕ (CLIENT).

    Ключ (CLIENT, FACE, RELATION).
    """

    keyless = False

    def ensure(self, engine: Engine, parent_id: int, block: Block) -> Optional[int]:
        if not block.subtype or not block.subtype_is_alias:
            raise DslError(
                "affiliate: ключ должен быть ссылкой на лицо (affiliate: &алиас)",
                block.file, block.line,
            )
        face = engine.resolve_alias(block.subtype_alias, block)
        relation = engine.field_value(block, "RELATION", required=True)
        result = engine.call("API_FIND_AFFIL", [parent_id, face, int(relation)], block)
        aff_id = result[0]
        if aff_id is None:
            fields_text = engine.fields_to_text(block.without("RELATION"), block)
            result = engine.call(
                "API_INS_AFFIL", [parent_id, face, int(relation), fields_text], block
            )
            return result[0]
        return aff_id


_HANDLERS: Dict[str, Handler] = {
    "face": FaceHandler(),
    "share": ShareHandler(),
    "bank_account": BankAccountHandler(),
    "client": ClientHandler(),
    "bank": BankHandler(),
}

_CHILD_HANDLERS: Dict[str, ChildHandler] = {
    "code": CodeHandler(),
    "activity": ActivityHandler(),
    "attorney": AttorneyHandler(),
    "affiliate": AffiliateHandler(),
}
