/* ============================================================================
   „≈–Ќќ¬»  API_INS_CLIENT Ч Ќ≈ Ќј ј“џ¬ј“№ на стенд, обвесом не используетс€.

   ѕроцедуры API_INS_CLIENT в платформе нет. ќбвес вставл€ет лицевой счЄт
   пр€мым вызовом OD_PR_INSERT_CLIENT (cte/engine.py, ClientHandler), поэтому
   в sql/api_stubs_test_env.sql эта процедура не создаЄтс€. «десь сохранена
   заготовка на случай, когда API_INS_CLIENT всЄ-таки понадобитс€.

   ѕеред использованием сверить значени€ по умолчанию с движком: здесь
   IS_TERM='0', IS_MANAGER=0, IS_VOICE=0, RELATION=NULL, а движок
   (ClientHandler.INSERT_PARAMS) повтор€ет DEFAULT-ы OD_CLIENTS:
   IS_TERM='T', IS_MANAGER=1, IS_VOICE=1, RELATION=0.
   «ависит от API_FIND_CLIENT (Fansy-Foundation/dBase/proc.sql).
   ============================================================================ */

SET TERM ^ ;

/* –≈јЋ»«ќ¬јЌќ (не заглушка) Ч вставка делегирована в существующую
   платформенную OD_PR_INSERT_CLIENT (Fansy-Foundation/dBase/proc.sql),
   по указанию: использовать еЄ дл€ лицевого счЄта, "по крайней мере пока".

   —игнатура согласована с API_FIND_CLIENT: ключевые вещи (NUMBER, FACE,
   SUBTYPE) Ч €вные параметры, остальное в FIELDS. PLAN_ID берЄтс€ из FIELDS,
   а если не задан Ч из OD_OPERATORS по текущему пользователю, тем же
   правилом, что в API_FIND_CLIENT (иначе поиск и вставка могли бы попасть
   в разные планы счетов).

   »з FIELDS сейчас разбираютс€ NAME, PLAN_ID, ISSUER, STATE Ч остальные
   параметры OD_PR_INSERT_CLIENT (LINK_NUMBER, INCOME_*, O_MAIL_*, I_MAIL_*,
   DD_DATE/DD_NUM, TARIF, EXTRA_*, IS_*-флаги) передаютс€ NULL/умолчани€ми.
   TODO: расшир€ть по мере надобности сценариев Ч сама OD_PR_INSERT_CLIENT
   подставл€ет безопасные значени€ по умолчанию дл€ NULL.

   TYPE_ жЄстко = 2 Ч конвенци€, унаследованна€ от прикладного сло€
   ups_client_t (см. Fansy-Foundation/fansy_conventions.md);
   OD_PR_INSERT_CLIENT.TYPE_ вли€ет на то, создаЄтс€ ли OD_CLIENTS_REC (только при TYPE_<=3),
   поэтому трогать это значение не наобум. */
CREATE OR ALTER PROCEDURE API_INS_CLIENT (
    "NUMBER" VARCHAR(128),
    FACE INTEGER,
    SUBTYPE INTEGER,
    FIELDS VARCHAR(16383)
)
RETURNS (
    ID INTEGER
)
AS
declare variable PLAN_ID integer;
declare variable ISSUER integer;
declare variable V_STATE integer;
declare variable OPER integer;
declare variable V_NAME varchar(255);
declare variable V_MULTI varchar(4000);
begin
    ID = null;
    select ID, MULTI_ID from API_FIND_CLIENT(:NUMBER, :FIELDS) into :ID, :V_MULTI;
    if (ID is null and (V_MULTI is null or V_MULTI = '')) then begin

        select VAL from PR_LIST_VAL(:FIELDS, 'PLAN_ID') into :PLAN_ID;
        if (PLAN_ID is null) then
            select o.PLAN_ID from OD_OPERATORS o
             where upper(o.USER_ID) = upper(CURRENT_USER) into :PLAN_ID;
        /* PLAN_ID NOT NULL в OD_CLIENTS Ч если план не определилс€, insert
           ниже упадЄт по constraint, это осознанно (громка€ ошибка вместо
           тихого мусора) */

        select VAL from PR_LIST_VAL(:FIELDS, 'ISSUER') into :ISSUER;
        select VAL from PR_LIST_VAL(:FIELDS, 'STATE') into :V_STATE;
        if (V_STATE is null) then V_STATE = 0;

        select max(ID) from OD_OPERATORS where upper(USER_ID) = upper(CURRENT_USER) into :OPER;
        if (OPER is null) then
            select ID from OD_OPERATORS where upper(USER_ID) = 'SYSDBA' into :OPER;

        select VAL from PR_LIST_VAL(:FIELDS, 'NAME') into :V_NAME;

        execute procedure OD_PR_INSERT_CLIENT (
            null,           /* ID: сгенерировать сама (OD_CLIENTS_ID_GEN) */
            :"NUMBER",
            2,              /* TYPE_ = 2, конвенци€ */
            :SUBTYPE,
            :FACE,
            null,           /* RELATION */
            null,           /* PARENT */
            :PLAN_ID,
            '0',            /* IS_TERM */
            0, 0, 0,        /* IS_MANAGER, IS_VOICE, IS_PRIV */
            0,              /* IS_SOV */
            0,              /* IS_NZ */
            0,              /* IS_BCLIENT */
            :V_STATE,       /* STATE (из FIELDS, по умолчанию 0 Ч открыт) */
            current_timestamp, null,  /* D_OPEN, D_CLOSE */
            null,           /* Z_DATE */
            :OPER,
            :V_NAME,
            null, null, null, null, null, null, null,   /* LINK_NUMBER..INCOME_VERBAL */
            null, null,     /* O_MAIL_MOD, O_MAIL_ADR */
            null, null, null, /* I_MAIL_MOD, I_MAIL_ALT, I_MAIL_ADR */
            null, null,     /* DD_DATE, DD_NUM */
            null,           /* PLACE */
            :ISSUER,
            null, null, null /* TARIF, EXTRA_INT, EXTRA_TYPE */
        ) returning_values :ID;
    end
    SUSPEND;
end^


SET TERM ; ^
