import unittest

from cte.db import FakeDatabase
from cte.engine import ClientHandler, Engine
from cte.model import DslError, parse_text


def run(text, scripted=None):
    blocks = parse_text(text)
    db = FakeDatabase(scripted_returns=scripted or {})
    engine = Engine(db)
    engine.run(blocks)
    return engine, db


class EngineTests(unittest.TestCase):
    def test_face_create_not_found_then_insert(self):
        scripted = {
            "API_FIND_FACE": [(None, None)],
            "API_INS_FACE": [(101,)],
        }
        engine, db = run(
            """
face &ivanov: individual
  NAME=Иванов Иван Иванович
  INN=770123456789
""",
            scripted,
        )
        self.assertEqual(engine.aliases["ivanov"].id, 101)
        procs = [c[0] for c in db.calls]
        self.assertEqual(procs, ["API_FIND_FACE", "API_INS_FACE"])
        ins_args = db.calls[1][1]
        self.assertEqual(ins_args[0], 0)  # IS_JURIC для individual
        self.assertEqual(ins_args[1], "1900-01-01")
        self.assertIn("NAME=Иванов Иван Иванович", ins_args[2])
        self.assertIn("INN=770123456789", ins_args[2])

    def test_face_found_skips_insert(self):
        scripted = {"API_FIND_FACE": [(55, None)]}
        engine, db = run(
            """
face &ivanov: individual
  NAME=Иванов
""",
            scripted,
        )
        self.assertEqual(engine.aliases["ivanov"].id, 55)
        self.assertEqual([c[0] for c in db.calls], ["API_FIND_FACE"])

    def test_alias_substitution_in_fields(self):
        scripted = {
            "API_FIND_FACE": [(None, None), (777, None)],
            "API_INS_FACE": [(1,)],
            "API_FIND_SHARE": [(None, None)],
            "API_INS_SHARE": [(9,)],
        }
        engine, db = run(
            """
face &gazprom: juridical
  NAME=ПАО Газпром

share &gazp: stock
  SYSNAME=GAZP
  ISSUER=&gazprom
  ISIN=RU0007661625
""",
            scripted,
        )
        ins_share_args = [c for c in db.calls if c[0] == "API_INS_SHARE"][0][1]
        self.assertEqual(ins_share_args[0], "GAZP")
        self.assertEqual(ins_share_args[1], 1)
        self.assertEqual(ins_share_args[2], 1)  # CLASS для 'stock'
        self.assertIn("ISIN=RU0007661625", ins_share_args[3])
        self.assertNotIn("ISSUER=", ins_share_args[3])

    def test_unknown_alias_reference_errors(self):
        with self.assertRaisesRegex(DslError, "неизвестный алиас"):
            run(
                """
share &gazp: stock
  SYSNAME=GAZP
  ISSUER=&nobody
"""
            )

    def test_reference_to_stub_entity_without_id_errors(self):
        scripted = {
            "API_FIND_BANK": [(None,)],
            "API_INS_BANK": [(None,)],
        }
        with self.assertRaisesRegex(DslError, "создание 'bank' не удалось"):
            run(
                """
bank &sber
  BIC=044525225
""",
                scripted,
            )

    def test_face_historical_revision_requires_as_of(self):
        scripted = {
            "API_FIND_FACE": [(None, None)],
            "API_INS_FACE": [(1,)],
        }
        with self.assertRaisesRegex(DslError, "нужен as_of"):
            run(
                """
face &ivanov: individual
  NAME=Иванов

face &ivanov: individual
  NAME=Иванов (новое имя)
""",
                scripted,
            )

    def test_face_historical_revision_ok(self):
        scripted = {
            "API_FIND_FACE": [(None, None)],
            "API_INS_FACE": [(1,)],
        }
        engine, db = run(
            """
face &ivanov: individual
  NAME=Иванов

face &ivanov: individual
  as_of=2020-06-01
  NAME=Иванов (новое имя)
""",
            scripted,
        )
        upd_calls = [c for c in db.calls if c[0] == "API_UPD_FACE"]
        self.assertEqual(len(upd_calls), 1)
        self.assertEqual(upd_calls[0][1][0], 1)
        self.assertEqual(upd_calls[0][1][1], "2020-06-01")
        self.assertEqual(engine.aliases["ivanov"].last_as_of, "2020-06-01")

    def test_as_of_must_increase(self):
        scripted = {"API_FIND_FACE": [(None, None)], "API_INS_FACE": [(1,)]}
        with self.assertRaisesRegex(DslError, "должен быть позже"):
            run(
                """
face &ivanov: individual
  NAME=Иванов

face &ivanov: individual
  as_of=2020-06-01
  NAME=A

face &ivanov: individual
  as_of=2019-01-01
  NAME=B
""",
                scripted,
            )

    def test_as_of_forbidden_on_flat_kind(self):
        scripted = {
            "API_FIND_ACC": [(None,), (5,)],
            "API_INS_ACC": [(5,)],
        }
        with self.assertRaisesRegex(DslError, "as_of недопустим для плоской"):
            run(
                """
bank_account &acc1
  ACNT=40817810900000012345
  BIC=044525225

bank_account &acc1
  as_of=2020-01-01
  ACNT=40817810900000012345
  BIC=044525225
""",
                scripted,
            )

    def test_flat_kind_revision_calls_upd_in_place(self):
        scripted = {
            "API_FIND_ACC": [(None,)],
            "API_INS_ACC": [(5,)],
        }
        engine, db = run(
            """
bank_account &acc1
  ACNT=40817810900000012345
  BIC=044525225

bank_account &acc1
  ACNT=40817810900000012345
  BIC=044525225
  NAME=Новое название счёта
""",
            scripted,
        )
        upd_calls = [c for c in db.calls if c[0] == "API_UPD_ACC"]
        self.assertEqual(len(upd_calls), 1)
        self.assertEqual(upd_calls[0][1][0], 5)

    def test_reused_alias_with_different_kind_errors(self):
        scripted = {
            "API_FIND_FACE": [(None, None)],
            "API_INS_FACE": [(1,)],
        }
        with self.assertRaisesRegex(DslError, "уже занят типом"):
            run(
                """
face &x: individual
  NAME=Иванов

bank &x
  BIC=044525225
""",
                scripted,
            )

    def test_balance_block_not_supported(self):
        with self.assertRaisesRegex(DslError, "не поддерживается"):
            run("balance\n  X=1\n")

    def test_client_full_flow(self):
        scripted = {
            "API_FIND_FACE": [(None, None), (None, None)],
            "API_INS_FACE": [(1,), (2,)],
            "API_FIND_CLIENT": [(None, None)],
        }
        engine, db = run(
            """
face &ivanov: individual
  NAME=Иванов

face &gazprom: juridical
  NAME=ПАО Газпром

client &ivanov_owner: owner
  NUMBER=Т0001
  FACE=&ivanov
  ISSUER=&gazprom
  STATE=0
""",
            scripted,
        )
        # API_FIND_CLIENT(NUMBER, FIELDS): в FIELDS только ISSUER/PLAN_ID/STATE
        find_args = [c for c in db.calls if c[0] == "API_FIND_CLIENT"][0][1]
        self.assertEqual(find_args[0], "Т0001")
        self.assertIn("ISSUER=2", find_args[1])
        self.assertIn("STATE=0", find_args[1])
        self.assertNotIn("FACE=", find_args[1])

        # вставка идёт в OD_PR_INSERT_CLIENT (API_INS_CLIENT пока нет)
        ins_args = [c for c in db.calls if c[0] == "OD_PR_INSERT_CLIENT"][0][1]
        names = [n for n, _ in ClientHandler.INSERT_PARAMS]
        arg = dict(zip(names, ins_args))
        self.assertEqual(len(ins_args), 40)
        self.assertEqual(arg["ID"], 5000)     # из генератора OD_CLIENTS_ID_GEN
        self.assertEqual(arg["NUMBER"], "Т0001")
        self.assertEqual(arg["TYPE_"], 2)
        self.assertEqual(arg["SUBTYPE"], 1)   # owner
        self.assertEqual(arg["FACE"], 1)      # Иванов
        self.assertEqual(arg["ISSUER"], 2)    # Газпром
        self.assertEqual(arg["OPER"], 1)      # из OD_OPERATORS
        self.assertEqual(arg["PLAN_ID"], 100) # план оператора
        self.assertEqual(arg["STATE"], 0)
        self.assertEqual(engine.aliases["ivanov_owner"].id, 5000)

    def test_client_plan_id_passed_through(self):
        scripted = {
            "API_FIND_FACE": [(None, None)],
            "API_INS_FACE": [(1,)],
            "API_FIND_CLIENT": [(None, None)],
        }
        engine, db = run(
            """
face &ivanov: individual
  NAME=Иванов

client &acc: owner
  NUMBER=Т0001
  FACE=&ivanov
  PLAN_ID=7
""",
            scripted,
        )
        find_args = [c for c in db.calls if c[0] == "API_FIND_CLIENT"][0][1]
        self.assertIn("PLAN_ID=7", find_args[1])
        ins_args = [c for c in db.calls if c[0] == "OD_PR_INSERT_CLIENT"][0][1]
        names = [n for n, _ in ClientHandler.INSERT_PARAMS]
        # PLAN_ID из сценария побеждает план оператора
        self.assertEqual(dict(zip(names, ins_args))["PLAN_ID"], 7)

    def test_ambiguous_find_is_error(self):
        # ID не заполнен, но MULTI_ID содержит список — это неоднозначность,
        # а не «не найдено»: создавать дубль нельзя
        scripted = {"API_FIND_FACE": [(None, "101,102")]}
        with self.assertRaisesRegex(DslError, "несколько записей"):
            run(
                """
face &ivanov: individual
  NAME=Иванов
""",
                scripted,
            )

    def test_ambiguous_client_find_is_error(self):
        scripted = {
            "API_FIND_FACE": [(None, None)],
            "API_INS_FACE": [(1,)],
            "API_FIND_CLIENT": [(None, "55,56")],
        }
        with self.assertRaisesRegex(DslError, "client: под условие поиска"):
            run(
                """
face &ivanov: individual
  NAME=Иванов

client &acc: owner
  NUMBER=Т0001
  FACE=&ivanov
""",
                scripted,
            )


if __name__ == "__main__":
    unittest.main()
