/* ============================================================================
   API_FIND_CLIENT — ДОСЛОВНАЯ КОПИЯ платформенной процедуры из
   Fansy-Foundation/dBase/proc.sql (строка 247 на 2026-10-10); изменён только
   завершающий терминатор процедуры (под SET TERM для isql).

   Накатывать ТОЛЬКО на стенд, где API_FIND_CLIENT нет (обвес проверяет это
   перед прогоном и печатает список недостающих процедур). Если процедура на
   стенде уже есть, CREATE OR ALTER её ЗАМЕНИТ — сверьте версии заранее.

   Это не часть api_stubs_test_env.sql: там процедуры обвеса, а эта —
   платформенная и должна совпадать с оригиналом. При изменении оригинала
   копию нужно обновить.
   ============================================================================ */

SET TERM ^ ;

CREATE OR ALTER PROCEDURE API_FIND_CLIENT ("NUMBER" VARCHAR(128), FIELDS VARCHAR(16368))
RETURNS (
	ID INTEGER,
	MULTI_ID VARCHAR(4000)
)
AS
declare variable PLAN_ID integer;
declare variable ISSUER integer;
declare variable STATE integer;
declare variable FIELD varchar(500);
declare variable FLD varchar(64);
declare variable VL varchar(255);
declare variable I integer;
declare variable K integer;
declare variable M varchar(4000);
begin
   ID        = null;
   MULTI_ID  = null;
   PLAN_ID = null;
   ISSUER  = null;
   STATE   = null;

   /* Разбор параметра FIELDS: пары ИМЯ=ЗНАЧЕНИЕ, разделённые переводом строки.
      Распознаются (все опционально): ISSUER, PLAN_ID, STATE. */
   K = 1;
   FIELD = f_LRTrim(f_Token(FIELDS, f_Chr(10), K));
   while (f_IsBlank(FIELD) = 0) do begin
      I = f_Pos('=', FIELD);
      if (I > 1) then begin
         FLD = f_RTrim(f_Left(FIELD, I - 1));
         if (f_StrLen(FIELD) > I) then VL = f_LTrim(f_Copy(FIELD, I + 1, 255));
                                       else VL = null;
         if      (FLD = 'PLAN_ID') then PLAN_ID = f_AsInteger(VL);
         else if (FLD = 'ISSUER')  then ISSUER  = f_AsInteger(VL);
         else if (FLD = 'STATE')   then STATE   = f_AsInteger(VL);
      end
      K = K + 1;
      FIELD = f_LRTrim(f_Token(FIELDS, f_Chr(10), K));
   end

   /* PLAN_ID: если не задан явно в FIELDS - берём из записи оператора (OD_OPERATORS),
      соответствующей текущему подключённому пользователю (USER_ID = USER). */
   if (PLAN_ID is null) then
      select o.PLAN_ID from OD_OPERATORS o where upper(o.USER_ID) = upper(user) into :PLAN_ID;

   /* Поиск в OD_CLIENTS: PLAN_ID (обязательно) + NUMBER (обязательно) + ISSUER/STATE (если заданы в FIELDS) */
   M = '';
   for
      select c.ID from OD_CLIENTS c
       where c.NUMBER = f_LRTrim(:NUMBER)
         and c.PLAN_ID   = :PLAN_ID
         and (:ISSUER is null or c.ISSUER = :ISSUER)
         and (:STATE  is null or c.STATE  = :STATE)
      into :ID
   do
      M = f_Concat(M, ',' || cast(ID as varchar(12)));

   MULTI_ID = f_Copy(M, 2, 4000);
   if (f_Pos(',', MULTI_ID) > 0) then ID = null; /* найдено более одной записи - неоднозначно, ID не возвращаем */

   suspend;
end^

SET TERM ; ^
