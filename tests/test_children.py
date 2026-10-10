import unittest

from cte.db import FakeDatabase
from cte.engine import Engine
from cte.model import DslError, parse_text


def run(text, scripted=None):
    blocks = parse_text(text)
    db = FakeDatabase(scripted_returns=scripted or {})
    engine = Engine(db)
    engine.run(blocks)
    return engine, db


FACE_OK = {"API_FIND_FACE": [(None, None)], "API_INS_FACE": [(1,), (2,)]}


class NestingParseTests(unittest.TestCase):
    def test_children_parsed_into_tree(self):
        blocks = parse_text(
            """
face &ivanov: individual
  NAME=Иванов
  code: nsd
    CODE=NDC001
  activity: clearing
  INN=770123456789
  attorney: &petrov
    DUTY=Директор
"""
        )
        self.assertEqual(len(blocks), 1)
        face = blocks[0]
        # поле после подблока вернулось к родителю
        self.assertEqual([f.name for f in face.fields], ["NAME", "INN"])
        self.assertEqual([c.kind for c in face.children], ["code", "activity", "attorney"])
        self.assertEqual(face.children[0].get("CODE").raw, "NDC001")
        self.assertEqual(face.children[1].subtype, "clearing")
        self.assertEqual(face.children[1].fields, [])
        self.assertTrue(face.children[2].subtype_is_alias)
        self.assertEqual(face.children[2].subtype_alias, "petrov")

    def test_child_kind_at_top_level_is_error(self):
        with self.assertRaisesRegex(DslError, "только вложенным"):
            parse_text("code: nsd\n  CODE=1\n")

    def test_wrong_parent_is_error(self):
        with self.assertRaisesRegex(DslError, "недопустим внутри"):
            parse_text(
                """
client &c: owner
  NUMBER=T1
  code: nsd
    CODE=1
"""
            )

    def test_kind_without_children_is_error(self):
        with self.assertRaisesRegex(DslError, "не имеет вложенных"):
            parse_text(
                """
bank &sber
  BIC=044525225
  code: nsd
    CODE=1
"""
            )


class ChildEngineTests(unittest.TestCase):
    def test_code_calls_set_fc_code(self):
        engine, db = run(
            """
face &ivanov: individual
  NAME=Иванов
  code: nsd
    CODE=NDC001
""",
            FACE_OK,
        )
        calls = [c for c in db.calls if c[0] == "API_SET_FC_CODE"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1][0], 1)  # SELF_ID родителя
        self.assertEqual(calls[0][1][1], "nsd")
        self.assertIn("CODE=NDC001", calls[0][1][2])

    def test_code_coder_by_alias(self):
        scripted = {"API_FIND_FACE": [(None, None), (None, None)], "API_INS_FACE": [(10,), (20,)]}
        engine, db = run(
            """
face &nsd: juridical
  NAME=НКО АО НРД

face &ivanov: individual
  NAME=Иванов
  code: &nsd
    CODE=NDC001
""",
            scripted,
        )
        call = [c for c in db.calls if c[0] == "API_SET_FC_CODE"][0]
        self.assertEqual(call[1][0], 20)  # родитель — Иванов
        self.assertEqual(call[1][1], "10")  # кодировщик — НРД по алиасу

    def test_code_requires_code_field(self):
        with self.assertRaisesRegex(DslError, "CODE отсутствует"):
            run(
                """
face &ivanov: individual
  NAME=Иванов
  code: nsd
    NOTE=пусто
""",
                FACE_OK,
            )

    def test_activity_mnemonic_and_number(self):
        engine, db = run(
            """
face &nrd: juridical
  NAME=НРД
  activity: clearing
  activity: 27
    NUM_LIC=12345
""",
            FACE_OK,
        )
        calls = [c for c in db.calls if c[0] == "API_SET_P_FACE"]
        self.assertEqual([c[1][1] for c in calls], [6, 27])
        self.assertIn("NUM_LIC=12345", calls[1][1][2])

    def test_activity_unknown_mnemonic(self):
        with self.assertRaisesRegex(DslError, "неизвестный вид деятельности"):
            run(
                """
face &nrd: juridical
  NAME=НРД
  activity: telepathy
""",
                FACE_OK,
            )

    def test_keyless_child_cannot_have_alias(self):
        with self.assertRaisesRegex(DslError, "алиас невозможен"):
            run(
                """
face &ivanov: individual
  NAME=Иванов
  code &c1: nsd
    CODE=NDC001
""",
                FACE_OK,
            )

    def test_attorney_find_then_insert(self):
        scripted = dict(FACE_OK)
        scripted.update({"API_FIND_A_FACE": [(None,)], "API_INS_A_FACE": [(77,)]})
        engine, db = run(
            """
face &ivanov: individual
  NAME=Иванов
  attorney
    NAME=Сидоров С.С.
    DOC_NUM=12/2020
""",
            scripted,
        )
        find = [c for c in db.calls if c[0] == "API_FIND_A_FACE"][0]
        self.assertEqual(find[1][0], 1)
        self.assertIsNone(find[1][1])  # WORKER не задан
        self.assertEqual(find[1][2], "Сидоров С.С.")
        self.assertTrue(any(c[0] == "API_INS_A_FACE" for c in db.calls))

    def test_attorney_needs_name_or_alias(self):
        with self.assertRaisesRegex(DslError, "либо ключ &алиас"):
            run(
                """
face &ivanov: individual
  NAME=Иванов
  attorney
    DUTY=Директор
""",
                FACE_OK,
            )

    def test_attorney_stub_returning_null_errors(self):
        # API_FIND_A_FACE / API_INS_A_FACE — заглушки, оба отдают None
        with self.assertRaisesRegex(DslError, "создание 'attorney' не удалось"):
            run(
                """
face &ivanov: individual
  NAME=Иванов
  attorney
    NAME=Сидоров С.С.
""",
                FACE_OK,
            )

    def test_affiliate_under_client(self):
        scripted = {
            "API_FIND_FACE": [(None, None), (None, None)],
            "API_INS_FACE": [(1,), (2,)],
            "API_FIND_CLIENT": [(None, None)],
            "API_FIND_AFFIL": [(None,)],
            "API_INS_AFFIL": [(99,)],
        }
        engine, db = run(
            """
face &ivanov: individual
  NAME=Иванов

face &petrov: individual
  NAME=Петров

client &ivanov_owner: owner
  NUMBER=Т0001
  FACE=&ivanov
  affiliate: &petrov
    RELATION=1
    NUMERATOR=1
    DENOMINATOR=4
""",
            scripted,
        )
        find = [c for c in db.calls if c[0] == "API_FIND_AFFIL"][0]
        self.assertEqual(find[1][0], 5000)  # CLIENT — лицевой счёт
        self.assertEqual(find[1][1], 2)   # FACE — Петров
        self.assertEqual(find[1][2], 1)   # RELATION
        ins = [c for c in db.calls if c[0] == "API_INS_AFFIL"][0]
        self.assertNotIn("RELATION=", ins[1][3])
        self.assertIn("NUMERATOR=1", ins[1][3])
        self.assertEqual(engine.aliases["ivanov_owner"].id, 5000)

    def test_affiliate_requires_relation(self):
        scripted = {
            "API_FIND_FACE": [(None, None), (None, None)],
            "API_INS_FACE": [(1,), (2,)],
            "API_FIND_CLIENT": [(None, None)],
        }
        with self.assertRaisesRegex(DslError, "RELATION отсутствует"):
            run(
                """
face &petrov: individual
  NAME=Петров

client &c: owner
  NUMBER=Т1
  FACE=&petrov
  affiliate: &petrov
""",
                scripted,
            )

    def test_as_of_forbidden_in_child(self):
        with self.assertRaisesRegex(DslError, "as_of недопустим у вложенного"):
            run(
                """
face &ivanov: individual
  NAME=Иванов
  activity: clearing
    as_of=2020-01-01
""",
                FACE_OK,
            )

    def test_children_run_on_revision_block_too(self):
        engine, db = run(
            """
face &ivanov: individual
  NAME=Иванов

face &ivanov: individual
  as_of=2020-06-01
  NAME=Иванов
  activity: broker
""",
            FACE_OK,
        )
        calls = [c for c in db.calls if c[0] == "API_SET_P_FACE"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1][0], 1)  # тот же SELF_ID

    def test_stub_warnings_collected(self):
        engine, db = run(
            """
face &nrd: juridical
  NAME=НРД
  activity: clearing
""",
            FACE_OK,
        )
        self.assertTrue(any("API_SET_P_FACE" in w for w in engine.warnings))


if __name__ == "__main__":
    unittest.main()
