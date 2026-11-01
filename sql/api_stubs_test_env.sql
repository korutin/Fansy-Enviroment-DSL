/* ============================================================================
   Новые процедуры API_* для DSL описания тестовых окружений Fansy:
   ЗАГЛУШКИ и уже РЕАЛИЗОВАННЫЕ. Статус каждой процедуры указан в комментарии
   над ней.

   РЕАЛИЗОВАНЫ (коллекции лица и лицевого счёта): API_SET_P_FACE,
   API_FIND_A_FACE, API_INS_A_FACE, API_FIND_AFFIL, API_INS_AFFIL.
   РЕАЛИЗОВАНЫ (банк): API_FIND_BANK, API_SET_BANK.

   ЗАГЛУШКИ: API_UPD_CLIENT, API_UPD_A_FACE, API_UPD_AFFIL. Заглушка ничего
   не пишет в БД и не делает ничего (UPD) либо возвращает NULL (FIND/INS).
   Вызов из DSL-сценария на этом этапе даст пустой/нерабочий результат,
   а не ошибку — это осознанно временное решение, чтобы вызовы уже сейчас
   компилировались и обвес можно было тестировать по остальной части
   пайплайна (алиасы, парсинг блоков, порядок вызовов).

   Порядок процедур в файле значим: INS вызывает FIND, поэтому FIND описан
   раньше. Не запускайте этот скрипт поверх стенда, где API_* с такими же
   именами уже написаны вручную, — CREATE OR ALTER их заменит.

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
     API_FIND_BANK / API_SET_BANK     <- банк = лицо (платформенные API_FIND_FACE,
                                          API_INS_FACE, API_UPD_FACE) плюс запись
                                          OD_BANKS; образец ручного создания:
                                          Fansy-Foundation/examples-code/
                                          metaM__F_REESTR_V04_59.mes

   Решения по контракту, зафиксированные в обсуждении (актуальны на момент
   написания заглушек, при реализации сверяться с последним состоянием
   design-документа):
     - CLIENT — сущность ПЛОСКАЯ (без исторических версий, без
       as_of/NEW_B_DATE), в отличие от FACE/SHARE. UPD правит запись на месте
       по ID, как API_UPD_ACC.
     - BANK - лицо (оно историческое, as_of версионирует только его) плюс
       плоская запись OD_BANKS, которая при повторе просто перезаписывается.
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
     - BANK: бизнес-ключ поиска — BIC (см. IX_BANKS_BIC) либо SWIFT (по
       аналогии с API_FIND_ACC/API_INS_ACC); BIC необязателен, банк бывает
       и без него. Известно, что API_INS_ACC НЕ создаёт банк-субъект сам —
       ищет только среди уже существующих OD_BANKS/OD_FACES, значит банк
       должен быть создан отдельным шагом ДО банковского счёта.
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

/* Банк - обычное юрлицо (OD_FACES + OD_U_FACES) плюс запись OD_BANKS. Лицо
   обвес ведёт платформенными API_FIND_FACE / API_INS_FACE / API_UPD_FACE
   (с историей), а запись OD_BANKS - процедурами ниже (без истории).
   Образец прикладного кода, создающего банк вручную:
   Fansy-Foundation/examples-code/metaM__F_REESTR_V04_59.mes. */

/* РЕАЛИЗОВАНО. Поиск банка в OD_BANKS: сначала по BIC, затем по SWIFT.
   Возвращает SELF_ID лица-банка либо NULL.

   BIC   - БИК; пустой не используется.
   SWIFT - SWIFT-код; пустой не используется, регистр не учитывается.

   BIC необязателен (иностранный банк бывает только со SWIFT), поэтому ищется
   по любому из двух заданных ключей. Банк без обоих кодов процедурой не
   находится - такой банк обвес ищет как обычное лицо (API_FIND_FACE).
   OD_BANKS.U_FACE - ID лица (FK на OD_FACES.ID); наружу отдаётся SELF_ID, как
   у остальных процедур (у первой версии лица они совпадают). */
CREATE OR ALTER PROCEDURE API_FIND_BANK (
    BIC VARCHAR(21),
    SWIFT VARCHAR(12)
)
RETURNS (
    ID INTEGER
)
AS
begin
    ID = null;
    if (f_IsBlank(BIC) = 0) then
        select max(F.SELF_ID) from OD_BANKS B
               join OD_FACES F on F.ID = B.U_FACE
         where f_LRTrim(B.BIC) = f_LRTrim(:BIC)
          into :ID;
    if (ID is null and f_IsBlank(SWIFT) = 0) then
        select max(F.SELF_ID) from OD_BANKS B
               join OD_FACES F on F.ID = B.U_FACE
         where f_LRTrim(f_Upper(B.SWIFT)) = f_LRTrim(f_Upper(:SWIFT))
          into :ID;
    suspend;
end^


/* РЕАЛИЗОВАНО. Upsert записи банка в OD_BANKS (PK U_FACE). Конвенция
   платформы для таких процедур - префикс SET (ср. API_SET_FC_CODE).

   FACE   - SELF_ID лица (в OD_BANKS пишется как U_FACE; формально FK смотрит
            на OD_FACES.ID, у первой версии лица они совпадают). Само лицо
            (OD_FACES + OD_U_FACES) должно уже существовать - его создаёт
            API_INS_FACE.
   FIELDS - BIC, KORR, CITY, SWIFT, REG_NUM, IS_INSURANCE; пустое значение =
            <<не задано>>; прочие имена игнорируются (как во всех API_*).

   Записи ещё нет - вставляется (IS_INSURANCE по умолчанию 1, как в таблице),
   есть - обновляются только переданные поля. Истории у OD_BANKS нет: повторный
   вызов просто перезаписывает поля.

   Не проверено: по сводке триггеров OD_BANKS_BI_10 и OD_BANKS_BU_10 меняют
   OD_P_FACES - возможно, сами заводят вид деятельности <<банк>>. */
CREATE OR ALTER PROCEDURE API_SET_BANK (
    FACE INTEGER,
    FIELDS VARCHAR(16383)
)
AS
declare variable K integer;
declare variable I integer;
declare variable FIELD varchar(500);
declare variable FLD varchar(64);
declare variable VL varchar(255);
declare variable V_BIC varchar(10);
declare variable V_KORR varchar(255);
declare variable V_CITY varchar(64);
declare variable V_SWIFT varchar(12);
declare variable V_REG_NUM varchar(24);
declare variable V_IS_INSURANCE integer;
declare variable H_BIC integer;
declare variable H_KORR integer;
declare variable H_CITY integer;
declare variable H_SWIFT integer;
declare variable H_REG_NUM integer;
declare variable H_IS_INSURANCE integer;
declare variable C integer;
begin
    V_BIC = null;  V_KORR = null;  V_CITY = null;  V_SWIFT = null;  V_REG_NUM = null;
    V_IS_INSURANCE = null;
    H_BIC = 0;  H_KORR = 0;  H_CITY = 0;  H_SWIFT = 0;  H_REG_NUM = 0;  H_IS_INSURANCE = 0;

    /* Разбор FIELDS: пары ИМЯ=ЗНАЧЕНИЕ, разделённые переводом строки */
    K = 1;
    FIELD = f_LRTrim(f_Token(FIELDS, f_Chr(10), K));
    while (f_IsBlank(FIELD) = 0) do begin
        I = f_Pos('=', FIELD);
        if (I > 1) then begin
            FLD = f_RTrim(f_Left(FIELD, I - 1));
            if (f_StrLen(FIELD) > I) then VL = f_LTrim(f_Copy(FIELD, I + 1, 255));
                                     else VL = null;
            if (f_IsBlank(VL) = 0) then begin
                if      (FLD = 'BIC')          then begin V_BIC = VL;  H_BIC = 1;  end
                else if (FLD = 'KORR')         then begin V_KORR = VL; H_KORR = 1; end
                else if (FLD = 'CITY')         then begin V_CITY = VL; H_CITY = 1; end
                else if (FLD = 'SWIFT')        then begin V_SWIFT = VL; H_SWIFT = 1; end
                else if (FLD = 'REG_NUM')      then begin V_REG_NUM = VL; H_REG_NUM = 1; end
                else if (FLD = 'IS_INSURANCE') then begin V_IS_INSURANCE = f_AsInteger(VL); H_IS_INSURANCE = 1; end
            end
        end
        K = K + 1;
        FIELD = f_LRTrim(f_Token(FIELDS, f_Chr(10), K));
    end

    select count(*) from OD_BANKS where U_FACE = :FACE into :C;

    if (C = 0) then
        insert into OD_BANKS (U_FACE, BIC, KORR, CITY, SWIFT, REG_NUM, IS_INSURANCE)
            values (:FACE, :V_BIC, :V_KORR, :V_CITY, :V_SWIFT, :V_REG_NUM, coalesce(:V_IS_INSURANCE, 1));
    else if (H_BIC + H_KORR + H_CITY + H_SWIFT + H_REG_NUM + H_IS_INSURANCE > 0) then
        update OD_BANKS
           set BIC          = case when :H_BIC = 1          then :V_BIC          else BIC          end,
               KORR         = case when :H_KORR = 1         then :V_KORR         else KORR         end,
               CITY         = case when :H_CITY = 1         then :V_CITY         else CITY         end,
               SWIFT        = case when :H_SWIFT = 1        then :V_SWIFT        else SWIFT        end,
               REG_NUM      = case when :H_REG_NUM = 1      then :V_REG_NUM      else REG_NUM      end,
               IS_INSURANCE = case when :H_IS_INSURANCE = 1 then :V_IS_INSURANCE else IS_INSURANCE end
         where U_FACE = :FACE;
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
          -> API_SET_P_FACE, реализована ниже

   2) ИДЕНТИФИЦИРУЕМЫЕ — есть суррогатный ID, нужна тройка FIND/INS/UPD:
        - уполномоченные лица: OD_A_FACES, ключ (FACE, WORKER, IS_A=1)
        - аффилированные лица: OD_AFFILS, ключ (CLIENT, FACE, RELATION);
          ВАЖНО: висят на ЛИЦЕВОМ СЧЁТЕ (OD_AFFILS.CLIENT), не на лице
   ============================================================================ */


/* ---------- ACTIVITY (виды деятельности / лицензии, OD_P_FACES) ---------- */

/* РЕАЛИЗОВАНО. Upsert вида деятельности (лицензии) лица в OD_P_FACES.
   Таблица без суррогатного ID, запись сама себе ключ: UNIQUE(FACE, DIAL_MODE,
   BEG_LIC). Конвенция платформы для таких процедур — префикс SET
   (ср. API_SET_FC_CODE).

   FACE      - SELF_ID лица. Формально FK смотрит на OD_FACES.ID, но
               семантический ключ везде SELF_ID; у первой версии лица они
               совпадают, а триггеры OD_P_FACES вызывают OD_PR_GET_FACE_SELF_ID.
   DIAL_MODE - NUM из OD_SYS_TABS где CODE='DIAL_MODE' (0..38).
   FIELDS    - NUM_LIC, PLACE_LIC, BEG_LIC, END_LIC. Даты в виде ГГГГ-ММ-ДД
               (как пишет DSL) или ДД.ММ.ГГГГ; пустое значение = «не задано»;
               прочие имена игнорируются (как во всех API_* платформы).

   Нашлась запись с тем же (FACE, DIAL_MODE, BEG_LIC) - обновляются только
   переданные поля, иначе вставляется новая.

   Ловушка NULL в UNIQUE: BEG_LIC может быть NULL (вид деятельности без
   лицензии), а Firebird считает NULL-ы в UNIQUE различными. Поэтому поиск
   идёт условием (BEG_LIC = :V_BEG_LIC or (BEG_LIC is null and :V_BEG_LIC is
   null)) - иначе при каждом прогоне сценария появлялся бы новый дубль.

   Некорректный период (END_LIC раньше BEG_LIC) и пересечение периодов одного
   вида деятельности отсекают триггеры OD_P_FACES (судя по именам исключений -
   OD_EX_PERIOD_INTERVAL и OD_EX_PERIOD_INTERSEC). */
CREATE OR ALTER PROCEDURE API_SET_P_FACE (
    FACE INTEGER,
    DIAL_MODE INTEGER,
    FIELDS VARCHAR(16383)
)
AS
declare variable K integer;
declare variable I integer;
declare variable FIELD varchar(500);
declare variable FLD varchar(64);
declare variable VL varchar(255);
declare variable V_NUM_LIC varchar(255);
declare variable V_PLACE_LIC varchar(253);
declare variable V_BEG_LIC timestamp;
declare variable V_END_LIC timestamp;
declare variable H_NUM_LIC integer;
declare variable H_PLACE_LIC integer;
declare variable H_END_LIC integer;
declare variable C integer;
begin
    V_NUM_LIC = null;  V_PLACE_LIC = null;  V_BEG_LIC = null;  V_END_LIC = null;
    H_NUM_LIC = 0;     H_PLACE_LIC = 0;     H_END_LIC = 0;

    /* Разбор FIELDS: пары ИМЯ=ЗНАЧЕНИЕ, разделённые переводом строки */
    K = 1;
    FIELD = f_LRTrim(f_Token(FIELDS, f_Chr(10), K));
    while (f_IsBlank(FIELD) = 0) do begin
        I = f_Pos('=', FIELD);
        if (I > 1) then begin
            FLD = f_RTrim(f_Left(FIELD, I - 1));
            if (f_StrLen(FIELD) > I) then VL = f_LTrim(f_Copy(FIELD, I + 1, 255));
                                     else VL = null;
            if (f_IsBlank(VL) = 0) then begin
                if      (FLD = 'NUM_LIC')   then begin V_NUM_LIC   = VL; H_NUM_LIC   = 1; end
                else if (FLD = 'PLACE_LIC') then begin V_PLACE_LIC = VL; H_PLACE_LIC = 1; end
                else if (FLD = 'BEG_LIC')   then V_BEG_LIC = cast(VL as timestamp);
                else if (FLD = 'END_LIC')   then begin V_END_LIC   = cast(VL as timestamp); H_END_LIC = 1; end
            end
        end
        K = K + 1;
        FIELD = f_LRTrim(f_Token(FIELDS, f_Chr(10), K));
    end

    select count(*) from OD_P_FACES
     where FACE = :FACE and DIAL_MODE = :DIAL_MODE
       and (BEG_LIC = :V_BEG_LIC or (BEG_LIC is null and :V_BEG_LIC is null))
      into :C;

    if (C = 0) then
        insert into OD_P_FACES (FACE, DIAL_MODE, NUM_LIC, BEG_LIC, END_LIC, PLACE_LIC)
            values (:FACE, :DIAL_MODE, :V_NUM_LIC, :V_BEG_LIC, :V_END_LIC, :V_PLACE_LIC);
    else if (H_NUM_LIC + H_PLACE_LIC + H_END_LIC > 0) then
        update OD_P_FACES
           set NUM_LIC   = case when :H_NUM_LIC   = 1 then :V_NUM_LIC   else NUM_LIC   end,
               PLACE_LIC = case when :H_PLACE_LIC = 1 then :V_PLACE_LIC else PLACE_LIC end,
               END_LIC   = case when :H_END_LIC   = 1 then :V_END_LIC   else END_LIC   end
         where FACE = :FACE and DIAL_MODE = :DIAL_MODE
           and (BEG_LIC = :V_BEG_LIC or (BEG_LIC is null and :V_BEG_LIC is null));
end^


/* ---------- ATTORNEY (уполномоченные лица, OD_A_FACES) ---------- */

/* РЕАЛИЗОВАНО. Поиск связи «доверитель - уполномоченный» в OD_A_FACES
   (только записи с IS_A = 1). Возвращает ID записи либо NULL.

   FACE   - доверитель (SELF_ID лица).
   WORKER - уполномоченный (SELF_ID лица) либо NULL, если уполномоченного как
            лица в системе нет; тогда ключ вырождается в (FACE, NAME).
   NAME   - наименование уполномоченного, используется только при WORKER = NULL.

   Связь хранится направленно (FACE - доверитель, WORKER - уполномоченный), но
   читается с обеих сторон, поэтому при заданном WORKER ищется и прямая запись
   (FACE, WORKER), и зеркальная (WORKER, FACE): зеркальное описание той же
   связи (подблок attorney, объявленный под вторым участником) не создаст
   перевёрнутый дубль. Прямая запись предпочтительнее зеркальной.

   ОГРАНИЧЕНИЕ: найденная зеркальная запись возвращается молча, как обычная.
   Сообщать об этом ошибкой было бы правильнее, но платформа заводит
   исключения заранее, а подходящего готового нет; заводить новое исключение
   ради этого не стали. */
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
    ID = null;
    if (WORKER is not null) then begin
        select max(ID) from OD_A_FACES
         where FACE = :FACE and WORKER = :WORKER and IS_A = 1
          into :ID;
        if (ID is null) then
            select max(ID) from OD_A_FACES
             where FACE = :WORKER and WORKER = :FACE and IS_A = 1
              into :ID;
    end
    else if (f_IsBlank(NAME) = 0) then
        select max(ID) from OD_A_FACES
         where FACE = :FACE and WORKER is null and NAME = f_LRTrim(:NAME) and IS_A = 1
          into :ID;
    suspend;
end^


/* РЕАЛИЗОВАНО. Find-or-create уполномоченного лица в OD_A_FACES.

   FACE, WORKER - как в API_FIND_A_FACE. Если нет ни WORKER, ни NAME в FIELDS,
   запись не создаётся и возвращается NULL.
   IS_A = 1 ставится ЖЁСТКО: блок attorney по смыслу и означает уполномоченного;
   если другие значения IS_A кодируют иные роли, это будут отдельные процедуры,
   а не параметр.
   FIELDS - NAME, BASIS, DUTY, B_DATE, E_DATE, A_TYPE, DOC_TYPE, DOC_SER,
   DOC_NUM, DOC_DAT, DOC_PLACE, RELATION, POWER, DOC_END, DOC_CODE (даты в
   виде ГГГГ-ММ-ДД или ДД.ММ.ГГГГ). A_TYPE по умолчанию 0, остальное NULL.
   Если запись уже есть (API_FIND_A_FACE), она не меняется - FIELDS игнорируются.

   Поля передаются сразу в INSERT, а не через API_UPD_A_FACE (она пока
   заглушка). ID назначает триггер OD_A_FACES_BI_10 из OD_A_FACES_ID_GEN,
   возвращаем его через RETURNING. */
CREATE OR ALTER PROCEDURE API_INS_A_FACE (
    FACE INTEGER,
    WORKER INTEGER,
    FIELDS VARCHAR(16383)
)
RETURNS (
    ID INTEGER
)
AS
declare variable K integer;
declare variable I integer;
declare variable FIELD varchar(500);
declare variable FLD varchar(64);
declare variable VL varchar(255);
declare variable V_NAME varchar(255);
declare variable V_BASIS varchar(255);
declare variable V_DUTY varchar(255);
declare variable V_B_DATE timestamp;
declare variable V_E_DATE timestamp;
declare variable V_A_TYPE integer;
declare variable V_DOC_TYPE integer;
declare variable V_DOC_SER varchar(25);
declare variable V_DOC_NUM varchar(20);
declare variable V_DOC_DAT timestamp;
declare variable V_DOC_PLACE varchar(255);
declare variable V_RELATION integer;
declare variable V_POWER integer;
declare variable V_DOC_END timestamp;
declare variable V_DOC_CODE varchar(128);
begin
    ID = null;
    V_NAME = null;  V_BASIS = null;  V_DUTY = null;  V_B_DATE = null;  V_E_DATE = null;
    V_A_TYPE = 0;   V_DOC_TYPE = null;  V_DOC_SER = null;  V_DOC_NUM = null;
    V_DOC_DAT = null;  V_DOC_PLACE = null;  V_RELATION = null;  V_POWER = null;
    V_DOC_END = null;  V_DOC_CODE = null;

    /* Разбор FIELDS: пары ИМЯ=ЗНАЧЕНИЕ, разделённые переводом строки */
    K = 1;
    FIELD = f_LRTrim(f_Token(FIELDS, f_Chr(10), K));
    while (f_IsBlank(FIELD) = 0) do begin
        I = f_Pos('=', FIELD);
        if (I > 1) then begin
            FLD = f_RTrim(f_Left(FIELD, I - 1));
            if (f_StrLen(FIELD) > I) then VL = f_LTrim(f_Copy(FIELD, I + 1, 255));
                                     else VL = null;
            if (f_IsBlank(VL) = 0) then begin
                if      (FLD = 'NAME')      then V_NAME      = f_LRTrim(VL);
                else if (FLD = 'BASIS')     then V_BASIS     = VL;
                else if (FLD = 'DUTY')      then V_DUTY      = VL;
                else if (FLD = 'B_DATE')    then V_B_DATE    = cast(VL as timestamp);
                else if (FLD = 'E_DATE')    then V_E_DATE    = cast(VL as timestamp);
                else if (FLD = 'A_TYPE')    then V_A_TYPE    = f_AsInteger(VL);
                else if (FLD = 'DOC_TYPE')  then V_DOC_TYPE  = f_AsInteger(VL);
                else if (FLD = 'DOC_SER')   then V_DOC_SER   = VL;
                else if (FLD = 'DOC_NUM')   then V_DOC_NUM   = VL;
                else if (FLD = 'DOC_DAT')   then V_DOC_DAT   = cast(VL as timestamp);
                else if (FLD = 'DOC_PLACE') then V_DOC_PLACE = VL;
                else if (FLD = 'RELATION')  then V_RELATION  = f_AsInteger(VL);
                else if (FLD = 'POWER')     then V_POWER     = f_AsInteger(VL);
                else if (FLD = 'DOC_END')   then V_DOC_END   = cast(VL as timestamp);
                else if (FLD = 'DOC_CODE')  then V_DOC_CODE  = VL;
            end
        end
        K = K + 1;
        FIELD = f_LRTrim(f_Token(FIELDS, f_Chr(10), K));
    end

    /* уполномоченного нечем идентифицировать - ничего не создаём */
    if (WORKER is null and f_IsBlank(V_NAME) <> 0) then exit;

    select ID from API_FIND_A_FACE(:FACE, :WORKER, :V_NAME) into :ID;

    if (ID is null) then
        insert into OD_A_FACES (FACE, WORKER, IS_A, NAME, BASIS, DUTY, B_DATE, E_DATE,
                                A_TYPE, DOC_TYPE, DOC_SER, DOC_NUM, DOC_DAT, DOC_PLACE,
                                RELATION, POWER, DOC_END, DOC_CODE)
            values (:FACE, :WORKER, 1, :V_NAME, :V_BASIS, :V_DUTY, :V_B_DATE, :V_E_DATE,
                    :V_A_TYPE, :V_DOC_TYPE, :V_DOC_SER, :V_DOC_NUM, :V_DOC_DAT, :V_DOC_PLACE,
                    :V_RELATION, :V_POWER, :V_DOC_END, :V_DOC_CODE)
            returning ID into :ID;
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

/* РЕАЛИЗОВАНО. Поиск аффилированного лица в OD_AFFILS по ключу
   (CLIENT, FACE, RELATION). Возвращает ID записи либо NULL.

   CLIENT   - ID лицевого счёта (OD_CLIENTS.ID); аффилированные висят на
              ЛИЦЕВОМ СЧЁТЕ, не на лице.
   FACE     - SELF_ID лица.
   RELATION - вид связи. Из прикладного кода известно: 0 - владелец,
              11 - оператор счёта депо, 12 - попечитель, 14 - учредитель
              управления, 16 - залогодержатель (уполномоченное лицо).

   Ключ не уникален: прикладной код допускает, что одно лицо включено в список
   несколько раз (разные документы, полномочия, периоды). Датами поиск не
   ограничивается; при нескольких записях возвращается самая поздняя (max ID).
   Для RELATION = 0 запись, скорее всего, уже создана самой вставкой лицевого
   счёта (триггеры OD_CLIENTS меняют OD_AFFILS) - тогда она и будет найдена. */
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
    ID = null;
    select max(ID) from OD_AFFILS
     where CLIENT = :CLIENT and FACE = :FACE and RELATION = :RELATION
      into :ID;
    suspend;
end^


/* РЕАЛИЗОВАНО. Find-or-create аффилированного лица в OD_AFFILS.

   Поля, обязательные в таблице, процедура заполняет САМА, сценарий их задавать
   не обязан:
     OPER      - оператор для CURRENT_USER из OD_OPERATORS, при его отсутствии
                 SYSDBA (то же правило, что в API_FIND_CLIENT и в обвесе)
     IUD       - 0
     R_DATE    - current_timestamp
     B_DATE    - из FIELDS, иначе начало времён (01.01.1900)
     E_DATE    - из FIELDS, иначе конец времён (01.01.9999 - запись действует)
     A_TYPE = 1, PERCENT_ = 0, POWER = 1, NUMERATOR = 1, DENOMINATOR = 1
   FIELDS - B_DATE, E_DATE, A_TYPE, A_NUM, A_DATE, A_END, PERCENT_ (или PERCENT),
   POWER, INCOME_ACC, INCOME_REC, INCOME_ADR, INCOME_VERBAL, NUMERATOR,
   DENOMINATOR (даты в виде ГГГГ-ММ-ДД или ДД.ММ.ГГГГ). Остальные имена,
   включая RELATION, игнорируются.

   A_END по умолчанию остаётся NULL. Прикладной код для связей 11 и 12
   (оператор, попечитель) отбирает только записи с A_END > даты договора, так
   что без явного A_END такие записи там «не действуют» - задавайте A_END.
   Для RELATION = 0 триггеры OD_AFFILS проверяют владельцев (исключения
   OD_EX_CLIENTS_OWNERTYPE, OD_EX_CLIENTS_TWOOWNERS) - они сработают как есть.

   Если запись уже есть (API_FIND_AFFIL), она не меняется - FIELDS игнорируются.
   Поля идут сразу в INSERT, а не через API_UPD_AFFIL (она пока заглушка).
   ID назначает триггер OD_AFFILS_BI из OD_AFFILS_ID_GEN, возвращаем его через
   RETURNING. */
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
declare variable K integer;
declare variable I integer;
declare variable FIELD varchar(500);
declare variable FLD varchar(64);
declare variable VL varchar(255);
declare variable V_OPER integer;
declare variable V_B_DATE timestamp;
declare variable V_E_DATE timestamp;
declare variable V_A_TYPE integer;
declare variable V_A_NUM varchar(64);
declare variable V_A_DATE timestamp;
declare variable V_A_END timestamp;
declare variable V_PERCENT integer;
declare variable V_POWER integer;
declare variable V_INCOME_ACC integer;
declare variable V_INCOME_REC varchar(255);
declare variable V_INCOME_ADR varchar(255);
declare variable V_INCOME_VERBAL varchar(255);
declare variable V_NUMERATOR integer;
declare variable V_DENOMINATOR integer;
begin
    ID = null;
    select ID from API_FIND_AFFIL(:CLIENT, :FACE, :RELATION) into :ID;
    if (ID is null) then begin

        V_B_DATE = cast('01.01.1900' as timestamp);
        V_E_DATE = cast('01.01.9999' as timestamp);
        V_A_TYPE = 1;  V_A_NUM = null;  V_A_DATE = null;  V_A_END = null;
        V_PERCENT = 0;  V_POWER = 1;
        V_INCOME_ACC = null;  V_INCOME_REC = null;  V_INCOME_ADR = null;  V_INCOME_VERBAL = null;
        V_NUMERATOR = 1;  V_DENOMINATOR = 1;

        /* Разбор FIELDS: пары ИМЯ=ЗНАЧЕНИЕ, разделённые переводом строки */
        K = 1;
        FIELD = f_LRTrim(f_Token(FIELDS, f_Chr(10), K));
        while (f_IsBlank(FIELD) = 0) do begin
            I = f_Pos('=', FIELD);
            if (I > 1) then begin
                FLD = f_RTrim(f_Left(FIELD, I - 1));
                if (f_StrLen(FIELD) > I) then VL = f_LTrim(f_Copy(FIELD, I + 1, 255));
                                         else VL = null;
                if (f_IsBlank(VL) = 0) then begin
                    if      (FLD = 'B_DATE')        then V_B_DATE        = cast(VL as timestamp);
                    else if (FLD = 'E_DATE')        then V_E_DATE        = cast(VL as timestamp);
                    else if (FLD = 'A_TYPE')        then V_A_TYPE        = f_AsInteger(VL);
                    else if (FLD = 'A_NUM')         then V_A_NUM         = VL;
                    else if (FLD = 'A_DATE')        then V_A_DATE        = cast(VL as timestamp);
                    else if (FLD = 'A_END')         then V_A_END         = cast(VL as timestamp);
                    else if (FLD = 'PERCENT_' or FLD = 'PERCENT') then V_PERCENT = f_AsInteger(VL);
                    else if (FLD = 'POWER')         then V_POWER         = f_AsInteger(VL);
                    else if (FLD = 'INCOME_ACC')    then V_INCOME_ACC    = f_AsInteger(VL);
                    else if (FLD = 'INCOME_REC')    then V_INCOME_REC    = VL;
                    else if (FLD = 'INCOME_ADR')    then V_INCOME_ADR    = VL;
                    else if (FLD = 'INCOME_VERBAL') then V_INCOME_VERBAL = VL;
                    else if (FLD = 'NUMERATOR')     then V_NUMERATOR     = f_AsInteger(VL);
                    else if (FLD = 'DENOMINATOR')   then V_DENOMINATOR   = f_AsInteger(VL);
                end
            end
            K = K + 1;
            FIELD = f_LRTrim(f_Token(FIELDS, f_Chr(10), K));
        end

        select max(ID) from OD_OPERATORS where upper(USER_ID) = upper(CURRENT_USER) into :V_OPER;
        if (V_OPER is null) then
            select max(ID) from OD_OPERATORS where upper(USER_ID) = 'SYSDBA' into :V_OPER;

        insert into OD_AFFILS (CLIENT, FACE, RELATION, B_DATE, E_DATE, OPER, IUD,
                               A_TYPE, A_NUM, A_DATE, A_END, R_DATE, PERCENT_, POWER,
                               INCOME_ACC, INCOME_REC, INCOME_ADR, INCOME_VERBAL,
                               NUMERATOR, DENOMINATOR)
            values (:CLIENT, :FACE, :RELATION, :V_B_DATE, :V_E_DATE, :V_OPER, 0,
                    :V_A_TYPE, :V_A_NUM, :V_A_DATE, :V_A_END, current_timestamp, :V_PERCENT, :V_POWER,
                    :V_INCOME_ACC, :V_INCOME_REC, :V_INCOME_ADR, :V_INCOME_VERBAL,
                    :V_NUMERATOR, :V_DENOMINATOR)
            returning ID into :ID;
    end
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
