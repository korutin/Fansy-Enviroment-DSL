/* ============================================================================
   ЗАГЛУШКИ новых процедур API_* для DSL описания тестовых окружений Fansy.

   Статус: НЕ РЕАЛИЗОВАНО. Каждая процедура ничего не пишет в БД и
   возвращает NULL (для FIND/INS) либо не делает ничего (для UPD).
   Вызов из DSL-сценария на этом этапе даст пустой/нерабочий результат,
   а не ошибку — это осознанно временное решение, чтобы вызовы уже сейчас
   компилировались и обвес можно было тестировать по остальной части
   пайплайна (алиасы, парсинг блоков, порядок вызовов).

   Оформление соответствует стилю существующих API_* в
   Fansy-Foundation/dBase/proc.sql (CREATE OR ALTER PROCEDURE, разбор
   FIELDS через f_Token/f_Chr(10), PR_LIST_VAL и т.п.) — при реализации
   ориентироваться на аналоги:
     API_FIND_CLIENT                   <- В ЭТОМ ФАЙЛЕ НЕТ: рабочая процедура
                                          лежит отдельно в
                                          Fansy-Foundation/dBase/proc.sql
     API_INS_CLIENT                    <- НЕ СУЩЕСТВУЕТ и здесь не создаётся:
                                          вставку делает обвес напрямую через
                                          платформенную OD_PR_INSERT_CLIENT
                                          (Fansy-Foundation/dBase/proc.sql);
                                          черновик процедуры — в
                                          sql/draft_api_ins_client.sql.
     API_UPD_CLIENT                    <- остаётся заглушкой, аналогичной
                                          "update"-процедуры не давали
     API_INS_BANK  / API_UPD_BANK     <- по образцу inline-кода создания банка
                                          в Fansy-Foundation/examples-code/
                                          metaM__F_REESTR_V04_59.mes
                                          (OD_FACES -> OD_U_FACES -> OD_BANKS)

   Решения по контракту, зафиксированные в обсуждении (актуальны на момент
   написания заглушек, при реализации сверяться с последним состоянием
   design-документа):
     - CLIENT и BANK — сущности ПЛОСКИЕ (без исторических версий, без
       as_of/NEW_B_DATE), в отличие от FACE/SHARE. UPD правит запись на месте
       по ID, как API_UPD_ACC.
     - CLIENT: бизнес-ключ поиска — (NUMBER, PLAN_ID, ISSUER), см. constraint
       U_CLIENTS и rslv_client_t. PLAN_ID резолвится по PLAN_SYS_NAME через
       OD_ACC_PLANS.SYS_NAME (в текущем прикладном коде — 'REESTR', жёстко).
       SUBTYPE передаётся готовым числом. Справочник значений — OD_SYS_TABS
       где CODE='REESTR_SUBTYPE', колонка NUM (1=владелец, 2=номинальный
       держатель, 3=довер.управляющий, 4=доп.инвестиционные паи,
       5=залогодержатель, 6=выдаваемые инвестиционные паи, 7=счёт фонда,
       8=неустановленные лица, 9=депозитный лиц.счёт, 10=казначейский счёт
       эмитента, 102=номинальный держатель ЦД). Маппинг мнемоника->NUM
       фиксируется в конфиге обвеса, привязка по NUM (стабилен),
       не по NAME (текст описания, может измениться).
       OPER резолвить ВНУТРИ процедуры через CURRENT_USER (по образцу
       rslv_operator_current_t), а не снаружи.
     - BANK: бизнес-ключ поиска — BIC (см. IX_BANKS_BIC), также предусмотреть
       SWIFT как альтернативный ключ (по аналогии с API_FIND_ACC/API_INS_ACC).
       Известно, что API_INS_ACC НЕ создаёт банк-субъект сам — ищет только
       среди уже существующих OD_BANKS/OD_FACES, значит API_INS_BANK
       обязателен как отдельный шаг ДО создания банковского счёта.
   ============================================================================ */


/* Справочник CLASS для API_INS_SHARE/API_FIND_SHARE (не заглушка, процедуры
   уже существуют в платформе, это только для обвеса) — OD_SYS_TABS
   где CODE='SHARE_CLASS', колонка NUM: 1=акция, 2=облигация, 3=вексель,
   4=опцион, 5=фьючерс, 6=банк.сертификат, 7=депозитарная расписка,
   8=коносамент, 9=варрант, 10=пай, 11=уставной капитал ООО, 12=закладная,
   13=ипотечный сертификат участия, 14=клиринговый сертификат участия,
   15=цифровой актив, 16=цифровое свидетельство, 17=криптовалюта.
   Маппинг мнемоника->NUM
   также в конфиге обвеса, привязка по NUM. */


/* ---------- CLIENT (лицевой счёт, OD_CLIENTS) ---------- */

SET TERM ^ ;

/* API_FIND_CLIENT здесь СОЗНАТЕЛЬНО отсутствует: реальная процедура уже
   написана и лежит в Fansy-Foundation/dBase/proc.sql — её накатывать отдельно.
   Её интерфейс:
     API_FIND_CLIENT(NUMBER VARCHAR(128), FIELDS VARCHAR(16368))
       RETURNS (ID INTEGER, MULTI_ID VARCHAR(4000))
   Из FIELDS понимает PLAN_ID, ISSUER, STATE (все опционально); если PLAN_ID
   не задан, берёт его из OD_OPERATORS по текущему пользователю подключения.
   При нескольких подходящих записях ID не заполняется, список уходит в
   MULTI_ID (обвес трактует это как ошибку неоднозначности, а не «не найдено»).
   Раньше в этом файле была заглушка с другой сигнатурой — удалена, чтобы
   CREATE OR ALTER не затёр рабочую процедуру. */


/* API_INS_CLIENT в платформе НЕ СУЩЕСТВУЕТ и этим скриптом не создаётся:
   лицевой счёт вставляется напрямую через OD_PR_INSERT_CLIENT (см.
   cte/engine.py, ClientHandler). Заготовка процедуры сохранена в
   sql/draft_api_ins_client.sql — НЕ накатывать, пока не решено, что
   API_INS_CLIENT нужна. */


CREATE OR ALTER PROCEDURE API_UPD_CLIENT (
    ID INTEGER,
    FIELDS VARCHAR(16383)
)
AS
begin
    /* STUB: не реализовано.
       TODO: разбор FIELDS построчно (f_Token(FIELDS, f_Chr(10), k))
       по образцу API_UPD_ACC, применение к колонкам OD_CLIENTS.
       Плоское обновление, без версионирования (as_of не поддерживается). */
end^


/* ---------- BANK (банк как субъект, OD_FACES + OD_U_FACES + OD_BANKS) ---------- */

CREATE OR ALTER PROCEDURE API_FIND_BANK (
    BIC VARCHAR(21)
)
RETURNS (
    ID INTEGER
)
AS
begin
    /* STUB: не реализовано.
       TODO: select max(U_FACE) from OD_BANKS where f_LRTrim(BIC)=f_LRTrim(:BIC)
       into :ID; если не найдено — попробовать по SWIFT (см. API_INS_ACC). */
    ID = null;
    SUSPEND;
end^


CREATE OR ALTER PROCEDURE API_INS_BANK (
    BIC VARCHAR(21),
    FIELDS VARCHAR(16383)
)
RETURNS (
    ID INTEGER
)
AS
begin
    /* STUB: не реализовано.
       TODO: find-or-create по образцу inline-кода из
       Fansy-Foundation/examples-code/metaM__F_REESTR_V04_59.mes:
         1) select ID from API_FIND_BANK(:BIC) into :ID;
         2) если не найдено:
              ID = gen_id(OD_FACES_ID_GEN, 1);
              insert into OD_FACES (ID, NAME, INN, HOME_ADR, S_TYPE, STATE,
                  LAST_FLAG, B_DATE) values (:ID, ..., 1, 643, 1, <начало времён>);
              insert into OD_U_FACES (FACE, FULL_NAME, FS, UPTYPE)
                  values (:ID, ..., 16, 0);
              insert into OD_BANKS (U_FACE, BIC, KORR, CITY)
                  values (:ID, :BIC, ..., ...);
         3) execute procedure API_UPD_BANK(:ID, :FIELDS); */
    ID = null;
    SUSPEND;
end^


CREATE OR ALTER PROCEDURE API_UPD_BANK (
    ID INTEGER,
    FIELDS VARCHAR(16383)
)
AS
begin
    /* STUB: не реализовано.
       TODO: разбор FIELDS построчно, применение к OD_FACES (NAME/INN/...),
       OD_U_FACES (FULL_NAME/...), OD_BANKS (KORR/CITY/SWIFT/REG_NUM/...).
       Плоское обновление, без версионирования. */
end^


/* ============================================================================
   МНОЖЕСТВЕННЫЕ АТРИБУТЫ (коллекции), дочерние по отношению к лицу/лиц.счёту.

   Делятся на два класса по наличию собственной идентичности:

   1) БЕЗКЛЮЧЕВЫЕ — суррогатного ID нет, запись сама себе ключ, достаточно
      одной upsert-процедуры (конвенция платформы для таких — префикс SET,
      ср. существующие API_SET_FC_CODE / API_SET_SH_CODE):
        - коды лица у кодировщиков: OD_FACE_CODERS, PK(CODER,FACE)
          -> API_SET_FC_CODE УЖЕ СУЩЕСТВУЕТ, ничего писать не нужно
        - виды деятельности/лицензии: OD_P_FACES, UNIQUE(FACE,DIAL_MODE,BEG_LIC)
          -> API_SET_P_FACE, заглушка ниже

   2) ИДЕНТИФИЦИРУЕМЫЕ — есть суррогатный ID, нужна тройка FIND/INS/UPD:
        - уполномоченные лица: OD_A_FACES, ключ (FACE, WORKER, IS_A=1)
        - аффилированные лица: OD_AFFILS, ключ (CLIENT, FACE, RELATION);
          ВАЖНО: висят на ЛИЦЕВОМ СЧЁТЕ (OD_AFFILS.CLIENT), не на лице
   ============================================================================ */


/* ---------- ACTIVITY (виды деятельности / лицензии, OD_P_FACES) ---------- */

CREATE OR ALTER PROCEDURE API_SET_P_FACE (
    FACE INTEGER,
    DIAL_MODE INTEGER,
    FIELDS VARCHAR(16383)
)
AS
begin
    /* STUB: не реализовано.
       TODO: upsert в OD_P_FACES (таблица без суррогатного ID):
         1) разобрать из FIELDS: NUM_LIC, PLACE_LIC, BEG_LIC, END_LIC
         2) поиск существующей строки по UNIQUE(FACE, DIAL_MODE, BEG_LIC).
            ВНИМАНИЕ: BEG_LIC nullable, а Firebird считает NULL-ы в UNIQUE
            различными — поэтому условие обязательно вида
              (BEG_LIC = :BEG_LIC or (BEG_LIC is null and :BEG_LIC is null))
            иначе при каждом прогоне сценария будет появляться новый дубль
            вида деятельности без лицензии.
         3) нашли -> update, не нашли -> insert
       DIAL_MODE — код из OD_SYS_TABS где CODE='DIAL_MODE' (0..37).
       FACE — это SELF_ID лица (формально FK смотрит на OD_FACES.ID, но
       семантический ключ везде SELF_ID; для первой версии они совпадают). */
end^


/* ---------- ATTORNEY (уполномоченные лица, OD_A_FACES) ---------- */

CREATE OR ALTER PROCEDURE API_FIND_A_FACE (
    FACE INTEGER,
    WORKER INTEGER,
    NAME VARCHAR(255)
)
RETURNS (
    ID INTEGER
)
AS
begin
    /* STUB: не реализовано.
       TODO: поиск симметричным условием (связь хранится направленно, но
       читается с обеих сторон):
         where (FACE = :FACE or WORKER = :FACE) and IS_A = 1
           and (WORKER = :WORKER or (:WORKER is null and NAME = :NAME))
       Симметрия нужна, чтобы поймать зеркальное описание той же связи
       (подблок attorney, объявленный под вторым участником) и не создать
       перевёрнутый дубль. По-хорошему в этом случае процедура должна
       сигнализировать об ошибке, а не молча вернуть найденную строку. */
    ID = null;
    SUSPEND;
end^


CREATE OR ALTER PROCEDURE API_INS_A_FACE (
    FACE INTEGER,
    WORKER INTEGER,
    FIELDS VARCHAR(16383)
)
RETURNS (
    ID INTEGER
)
AS
begin
    /* STUB: не реализовано.
       TODO: find-or-create:
         1) select ID from API_FIND_A_FACE(:FACE, :WORKER, <NAME из FIELDS>)
         2) не нашли -> ID = gen_id(<генератор OD_A_FACES>, 1); insert into
            OD_A_FACES (ID, FACE, WORKER, IS_A, NAME, DUTY, BASIS, RELATION,
            POWER, A_TYPE, DOC_TYPE, DOC_SER, DOC_NUM, DOC_DAT, DOC_PLACE,
            DOC_END, DOC_CODE, B_DATE, E_DATE)
            IS_A = 1 ставится ЖЁСТКО — блок attorney по смыслу и означает
            уполномоченного; если другие значения IS_A кодируют иные роли,
            это будут отдельные процедуры, а не параметр.
         3) execute procedure API_UPD_A_FACE(:ID, :FIELDS);
       Имя генератора уточнить по RDB$GENERATORS. */
    ID = null;
    SUSPEND;
end^


CREATE OR ALTER PROCEDURE API_UPD_A_FACE (
    ID INTEGER,
    FIELDS VARCHAR(16383)
)
AS
begin
    /* STUB: не реализовано.
       TODO: разбор FIELDS построчно по образцу API_UPD_ACC, применение
       к OD_A_FACES. B_DATE/E_DATE — обычные поля, без версионирования. */
end^


/* ---------- AFFILIATE (аффилированные лица, OD_AFFILS) ---------- */

CREATE OR ALTER PROCEDURE API_FIND_AFFIL (
    CLIENT INTEGER,
    FACE INTEGER,
    RELATION INTEGER
)
RETURNS (
    ID INTEGER
)
AS
begin
    /* STUB: не реализовано.
       TODO: select ID from OD_AFFILS
             where CLIENT = :CLIENT and FACE = :FACE and RELATION = :RELATION */
    ID = null;
    SUSPEND;
end^


CREATE OR ALTER PROCEDURE API_INS_AFFIL (
    CLIENT INTEGER,
    FACE INTEGER,
    RELATION INTEGER,
    FIELDS VARCHAR(16383)
)
RETURNS (
    ID INTEGER
)
AS
begin
    /* STUB: не реализовано.
       TODO: find-or-create по образцу черновика API_INS_CLIENT
       (sql/draft_api_ins_client.sql).
       В OD_AFFILS много NOT NULL-полей, которые процедура должна заполнять
       САМА, а не требовать от сценария:
         OPER      - через CURRENT_USER -> OD_OPERATORS (как в черновике API_INS_CLIENT)
         IUD       - 0 (ср. вставку OD_CLIENTS_REC в OD_PR_INSERT_CLIENT)
         R_DATE    - current_timestamp
         B_DATE    - из FIELDS, иначе начало времён
         E_DATE    - конец времён
         POWER, NUMERATOR, DENOMINATOR - умолчания
       Остальное из FIELDS: A_TYPE, A_NUM, A_DATE, A_END, PERCENT_,
       INCOME_ACC/REC/ADR/VERBAL, NUMERATOR/DENOMINATOR. */
    ID = null;
    SUSPEND;
end^


CREATE OR ALTER PROCEDURE API_UPD_AFFIL (
    ID INTEGER,
    FIELDS VARCHAR(16383)
)
AS
begin
    /* STUB: не реализовано.
       TODO: разбор FIELDS построчно, применение к OD_AFFILS. */
end^

SET TERM ; ^
