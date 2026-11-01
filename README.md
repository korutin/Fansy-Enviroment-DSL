# CTE — Creator of Test Environment (Fansy)

Обвес для описания тестовых окружений Fansy декларативным DSL (`.tenv`)
и заведения описанных сущностей в БД через штатные `API_*`-процедуры
платформы. Только `API_*` — никакого прямого `INSERT`/fsc; единственное
осознанное исключение — вставка `client` через `OD_PR_INSERT_CLIENT` (см. ниже).

Структура проекта (`D:\Projecto\Fansy-Enviroment-DSL`):

```
Fansy-Enviroment-DSL/
  cte/        пакет: парсер, движок, слой БД, CLI
  examples/   примеры сценариев .tenv
  tests/      юнит-тесты (без обращения к Firebird)
  sql/        процедуры API_* для стенда: реализации и заглушки
              (api_stubs_test_env.sql), копия платформенной API_FIND_CLIENT
              (api_find_client.sql), черновик draft_api_ins_client.sql
              (не накатывается)
  README.md
  *.zip       архив Cowork-задачи: история работы над проектом
```

Ссылки вида `Fansy-Foundation/...` ведут в соседнюю папку
`D:\Projecto\Fansy-Foundation` — общую базу платформы: `dBase/` (`proc.sql`,
выгрузки `OD_SYS_TABS`), `examples-code/` (накопленный прикладной код `.mes`,
откуда берутся приёмы программирования) и `fansy_conventions.md`.

## Формат `.tenv`

```
face &gazprom: juridical
  NAME=ПАО Газпром
  INN=7736050003

face &ivanov: individual
  NAME=Иванов Иван Иванович

face &ivanov: individual
  as_of=2020-06-01
  NAME=Иванов Иван Иванович
  DOC_SER=45 05

share &gazp: stock
  SYSNAME=GAZP
  ISSUER=&gazprom
  ISIN=RU0007661625

client &ivanov_owner: owner
  NUMBER=Т0001
  FACE=&ivanov
  ISSUER=&gazprom
  # PLAN_ID необязателен: если не задан, платформа берёт план счетов из
  # записи оператора в OD_OPERATORS по текущему пользователю подключения

bank &sber
  NAME=ПАО Сбербанк
  BIC=044525225

bank_account &ivanov_acc
  ACNT=40817810900000012345
  BIC=044525225
  FACE=&ivanov
```

Множественные атрибуты задаются вложенными блоками:

```
face &ivanov: individual
  NAME=Иванов Иван Иванович
  code: &nsd
    CODE=NDC000123
  activity: depositary
    NUM_LIC=045-12042-000100
    BEG_LIC=2012-12-04
  attorney: &petrov
    DUTY=Заместитель директора

client &ivanov_owner: owner
  NUMBER=Т0001
  FACE=&ivanov
  affiliate: &petrov
    RELATION=1
```

Правила:

- Строка со знаком `=` — поле, принадлежит ближайшему блоку с меньшим
  отступом. Строка без `=` — заголовок блока: `kind [&alias] [: key]`.
  Отступ определяет вложенность.
- `key` (после двоеточия) — подтип для верхнеуровневых блоков
  (`face: individual`) либо ключ элемента коллекции для вложенных
  (`code: nsd`, `activity: clearing`, `attorney: &petrov`).
- Значение поля, равное **целиком** `&alias`, — ссылка на другой блок,
  резолвится в его ID перед вызовом API. `&` внутри более длинного текста —
  обычный символ.
- Порядок строго сверху вниз: ссылка на ещё не объявленный алиас — ошибка.
- `face`, `share` и `bank` — исторические сущности. Повтор блока с тем же
  алиасом требует `as_of=YYYY-MM-DD` (строго возрастающие даты) и вызывает
  `API_UPD_FACE`/`API_UPD_SHARE` с этой датой. Первое объявление `as_of`
  не принимает. У `bank` версионируется только часть <<лицо>>, см. раздел
  <<Блок bank>>.
- `bank_account`, `client` — плоские. Повтор блока правит запись на
  месте (`API_UPD_*`, без даты); `as_of` для них — ошибка.
- `balance` зарезервирован, не реализован — использование даёт явную ошибку.
- `include "файл.tenv"` — текстовая подстановка перед разбором.
- `# ...` в начале строки — комментарий.

## Блок bank

Банк — обычное юридическое лицо плюс запись в `OD_BANKS`. Поля блока делятся
на два слоя:

| Слой | Поля | Кто пишет | История |
|---|---|---|---|
| лицо | любые поля юрлица: `NAME`, `INN`, `KPP`, `HOME_ADR`, `MNEM`, `STATE`, `FS`, `FULL_NAME`, `OGRN`, ... (всё, что принимает `API_UPD_FACE`) | `API_FIND_FACE`/`API_INS_FACE`/`API_UPD_FACE` | да, через `as_of` |
| банк | `BIC`, `KORR`, `CITY`, `SWIFT`, `REG_NUM`, `IS_INSURANCE` | `API_FIND_BANK`/`API_SET_BANK` | нет, поля перезаписываются |

```
bank &sber
  NAME=ПАО Сбербанк
  INN=7707083893
  BIC=044525225
  KORR=30101810400000000225
  CITY=Москва

# банк без БИК (иностранный): достаточно SWIFT
bank &jpm
  NAME=JPMorgan Chase Bank
  SWIFT=CHASUS33
  STATE=840

# повтор: поля лица пойдут в новую версию с 2021-01-01,
# KORR будет просто перезаписан
bank &sber
  as_of=2021-01-01
  NAME=ПАО Сбербанк России
  KORR=30101810400000000999
```

Правила:

- `BIC` необязателен. Готовый банк ищется по `BIC`, затем по `SWIFT`
  (`API_FIND_BANK`); найденный банк не меняется. Если не нашёлся — ищется
  обычное лицо (`API_FIND_FACE`: `INN`, `NAME`, `TIN`, `MNEM`): найденное лицо
  становится банком, ему дописывается запись `OD_BANKS`. Нет и лица — оно
  создаётся (для этого нужен `NAME`) и дописывается запись `OD_BANKS`.
- Умолчания при создании лица, если поле в блоке не задано: `S_TYPE=1`
  (юрлицо), `STATE=643`, `FS=16` (частная собственность). Больше ничего не
  подставляется; заданное в блоке пишется как есть, так что иная форма
  собственности задаётся полем `FS` в блоке. `S_TYPE` отличный от 1 — ошибка: `API_UPD_FACE` не
  умеет менять `S_TYPE`, записать иное значение нельзя. При повторном
  объявлении блока умолчания не применяются.
- Повтор блока требует `as_of`: поля лица создают историческую версию
  (`API_UPD_FACE`), поля банка перезаписываются (`API_SET_BANK`) без истории.
- Вложенный блок у `bank` один — `activity` (например, `activity: bank` с
  номером и датой лицензии); работает так же, как у `face`. `code` и
  `attorney` у `bank` не разрешены.
- `bank_account` ссылается на банк текстом в поле `BIC`; для банка без БИК туда
  пишут SWIFT (платформа ищет банк по БИК, SWIFT и мнемонике лица).

Вложенные блоки (коллекции) бывают двух классов. Безключевые — `code`
(`OD_FACE_CODERS`) и `activity` (`OD_P_FACES`) — своего `ID` не имеют, запись
сама себе ключ, обслуживаются одной upsert-процедурой `API_SET_*` и не могут
иметь алиас. Идентифицируемые — `attorney` (`OD_A_FACES`) и `affiliate`
(`OD_AFFILS`) — имеют суррогатный `ID`, работают через `API_FIND_*`/`API_INS_*`
и алиас им разрешён.

Допустимая вложенность: `face` → `code`, `activity`, `attorney`;
`client` → `affiliate` (аффилированность в `OD_AFFILS` висит на лицевом
счёте, а не на лице); `bank` → `activity`. Нарушение — ошибка компиляции
сценария.

У вложенных блоков `as_of` запрещён: даты у них обычные поля
(`B_DATE`/`E_DATE`/`BEG_LIC`), версионирования нет.

Отклонение от правила «только `API_*`», временное и осознанное: пока нет
`API_INS_CLIENT`, лицевой счёт вставляется прямым вызовом платформенной
`OD_PR_INSERT_CLIENT`. У неё нет `RETURNS`, поэтому ID берётся из генератора
`OD_CLIENTS_ID_GEN` до вызова и передаётся параметром (аналог
`Gen_ID('Данные','OD_CLIENTS_ID_GEN',1)` в Fansy-SCRIPT), а
обязательные ей `OPER` и `PLAN_ID` читаются запросом к `OD_OPERATORS` по
текущему пользователю подключения — тем же правилом, что внутри
`API_FIND_CLIENT`. Оба костыля исчезнут, когда появится `API_INS_CLIENT`.
Умолчания остальных 40 параметров повторяют `DEFAULT`-ы самой `OD_CLIENTS`
(`IS_TERM='T'`, `IS_MANAGER=1`, `IS_VOICE=1`, `RELATION=0`, `TYPE_=2`).

Соответствие блок → процедуры: `face` → `API_FIND_FACE`/`API_INS_FACE`/
`API_UPD_FACE`; `share` → `API_FIND_SHARE`/`API_INS_SHARE`/`API_UPD_SHARE`;
`bank_account` → `API_FIND_ACC`/`API_INS_ACC`/`API_UPD_ACC`; `client` →
`API_FIND_CLIENT`/`OD_PR_INSERT_CLIENT` (вместо несуществующей
`API_INS_CLIENT`)/`API_UPD_CLIENT`; `bank` → `API_FIND_BANK`,
`API_FIND_FACE`/`API_INS_FACE`/`API_UPD_FACE` и `API_SET_BANK`; `code` →
`API_SET_FC_CODE`;
`activity` → `API_SET_P_FACE`; `attorney` → `API_FIND_A_FACE`/`API_INS_A_FACE`/
`API_UPD_A_FACE`; `affiliate` → `API_FIND_AFFIL`/`API_INS_AFFIL`/
`API_UPD_AFFIL`.

## Классификаторы (`cte/mnemonics.py`)

`subtype` у `client` — мнемоники `REESTR_SUBTYPE` (`owner`, `nominee`,
`trustee`, `add_units`, `pledge`, `issued_units`, `fund`, `unidentified`,
`deposit`, `issuer_treasury`, `nominee_cdep`). `subtype` у `share` —
мнемоники `SHARE_CLASS` (`stock`, `bond`, `bill`, `option`, `future`,
`bank_cert`, `dr`, `bill_of_lading`, `warrant`, `unit`, `ooo_capital`,
`mortgage_cert`, `mortgage_part`, `clearing_cert`, `digital_asset`,
`digital_cert`, `crypto`). Оба привязаны к `NUM` в `OD_SYS_TABS`, не к тексту `NAME`.

## Что реально работает в v1, а что — заглушка

| Блок | Статус | Комментарий |
|---|---|---|
| `face` | рабочий | реальные `API_FIND_FACE`/`API_INS_FACE`/`API_UPD_FACE` |
| `share` | рабочий | реальные `API_FIND_SHARE`/`API_INS_SHARE`/`API_UPD_SHARE` |
| `bank_account` | рабочий | реальные `API_FIND_ACC`/`API_INS_ACC`/`API_UPD_ACC`; если банк по BIC не существует — платформа тихо не создаёт запись (ID=NULL), обвес превращает это в явную ошибку |
| `client` | рабочий (кроме обновления) | поиск — платформенная `API_FIND_CLIENT` (`Fansy-Foundation/dBase/proc.sql`), вставка — напрямую `OD_PR_INSERT_CLIENT` (`API_INS_CLIENT` ещё не существует); `API_UPD_CLIENT` — заглушка, повторный блок `client` пока ничего не изменит |
| `bank` | рабочий | лицо — платформенные `API_FIND_FACE`/`API_INS_FACE`/`API_UPD_FACE` (с `as_of`); запись `OD_BANKS` — `API_FIND_BANK`/`API_SET_BANK` из `sql/api_stubs_test_env.sql`; на реальной БД не прогонялось |
| `code` | рабочий | `API_SET_FC_CODE` существует в платформе; обязательное поле `CODE` |
| `activity` | рабочий | `API_SET_P_FACE` (`sql/api_stubs_test_env.sql`): upsert по `(FACE, DIAL_MODE, BEG_LIC)` с учётом NULL в `BEG_LIC`; поля `NUM_LIC`, `PLACE_LIC`, `BEG_LIC`, `END_LIC` |
| `attorney` | рабочий (кроме обновления) | `API_FIND_A_FACE`/`API_INS_A_FACE` (запись с `IS_A=1`); поиск симметричный — зеркальная связь возвращается как найденная, молча; `API_UPD_A_FACE` — заглушка |
| `affiliate` | рабочий (кроме обновления) | `API_FIND_AFFIL`/`API_INS_AFFIL`; обязательные `OPER`, `IUD`, `R_DATE`, `B_DATE`, `E_DATE` процедура заполняет сама; `API_UPD_AFFIL` — заглушка |
| `balance` | не реализовано | зарезервированное слово, использование — ошибка |

Мнемоники вложенных блоков: `activity` — из `OD_SYS_TABS` `CODE='DIAL_MODE'`
(в `mnemonics.py` ходовая часть: `broker`, `dealer`, `depositary`, `clearing`,
`registrar`, `trust`, `bank`, `pif`, `npf` и др.), для редких видов можно
писать номер: `activity: 27`.

Заглушки — в `sql/api_stubs_test_env.sql`, с TODO-комментариями по каждой
недостающей процедуре.

## Запуск

Без похода в реальную БД, только проверка сценария и плана вызовов:

```
cd D:\Projecto\Fansy-Enviroment-DSL
python -m cte examples/scenario_example.tenv --dry-run
python -m cte examples/scenario_children.tenv --dry-run
```

### Подготовка стенда (один раз)

Часть процедур `API_*`, которые нужны обвесу, в платформе отсутствует — их
(реализации и заглушки) надо накатить из `sql/api_stubs_test_env.sql`.
`API_FIND_CLIENT` в этот скрипт не входит: она платформенная (описана в
`Fansy-Foundation/dBase/proc.sql`). Если preflight сообщает, что её на стенде
нет, накатите её копию `sql/api_find_client.sql` — на стенде, где процедура
уже есть, этот файл её ЗАМЕНИТ. `API_INS_CLIENT` не существует и не нужна —
вставка `client` идёт через `OD_PR_INSERT_CLIENT` (заготовка процедуры лежит в
`sql/draft_api_ins_client.sql`, её не накатывать). Накат (так же и для
`api_find_client.sql`):

```
isql -u SYSDBA -p *** "fb:d:\data\stand\DATA.fdb" -i sql\api_stubs_test_env.sql
```

Файлы в `sql/` сохранены в кодировке Windows-1251: в UTF-8 скрипт не встаёт,
сервер отвечает `Malformed string` при записи в `RDB$PROCEDURES`. Править их
нужно редактором, который сохраняет cp1251.

Скрипт использует `SET TERM ^ ;`, так что подходит для `isql` как есть.
Все процедуры создаются через `CREATE OR ALTER` — если процедура с таким
именем на стенде уже есть, она будет ЗАМЕНЕНА. Перед первым накатом стоит
проверить, что этих имён в базе нет:

```sql
select rdb$procedure_name from rdb$procedures
 where rdb$procedure_name starting with 'API_'
 order by 1;
```

Перед каждым прогоном обвес сам проверяет наличие нужных процедур и, если
чего-то не хватает, печатает полный список и останавливается, не начав
создавать данные (отключается флагом `--no-preflight`).

### Реальный запуск на стенде

```
python -m cte scenario.tenv --dsn "server:c:\data\stand\DATA.fdb" --user SYSDBA --password *** --driver fdb
```

Про драйвер и библиотеку клиента:

- Firebird 2.5 (как на стендах Fansy) — драйвер `fdb` (`pip install fdb`).
  `firebird-driver` требует клиент Firebird 3.0+ (новый объектный API) и с
  библиотекой от 2.5 не работает. По умолчанию `--driver auto` пробует `fdb`,
  затем `firebird-driver`.
- Разрядность Python должна совпадать с разрядностью `fbclient.dll`. Иначе
  `OSError: [WinError 193] не является приложением Win32`. Проверка:
  `python -c "import struct;print(struct.calcsize('P')*8)"`. Клиент Firebird
  2.5 чаще 32-битный — тогда нужен 32-битный Python.
- Если библиотека не находится автоматически — `--fb-client C:\путь\fbclient.dll`
  или переменная окружения `FIREBIRD`.
- `--charset` по умолчанию `WIN1251`: базы Fansy и выгрузки платформы в cp1251,
  при UTF8-подключении к базе с charset NONE кириллица поедет.
- Пользователь подключения важен не только для доступа: для вставки `client`
  обвес определяет `OPER` и `PLAN_ID` по записи `OD_OPERATORS` для
  `CURRENT_USER` (с откатом на `SYSDBA`, см. `Database.current_operator`), то
  есть от логина зависит, какой операционист попадёт в данные.

Без `--dsn` обвес всегда уходит в dry-run автоматически.

`--dry-run` по умолчанию имитирует пустую БД: для уже реализованных `INS_*`
выдаёт правдоподобный ID, а для процедур-заглушек честно возвращает NULL —
это не баг, а показатель того, что процедура ещё не готова к реальной работе
(сейчас заглушки остались только у `API_UPD_CLIENT`, `API_UPD_A_FACE` и
`API_UPD_AFFIL`).

## Тесты

```
cd D:\Projecto\Fansy-Enviroment-DSL
python -m unittest discover -s tests
```

Тесты не требуют установленного Firebird-клиента — используют `FakeDatabase`
(скриптуемые ответы для точечных проверок) и работают полностью в памяти.

## Выгрузка из БД в env-light (Fansy-SCRIPT)

Обратное направление: функции модуля `_F_ENVLIGHT` (`fsc/_F_ENVLIGHT/`, по
файлу на функцию) сериализуют объект БД в текст сценария env-light:

- `_F_ENVLIGHT->export_face(%face)` - лицо и все лица, на которые оно ссылается;
- `_F_ENVLIGHT->export_client(%client)` - лицевой счёт, его лица, банковские
  счета и лица-банки;
- `_F_ENVLIGHT->export_share(%share)` - финансовый инструмент и его лица.

Функции возвращают текст; порядок блоков - от тех, на кого ссылаются, к
ссылающимся. Устройство, решения, что не выгружается и что нужно проверить при
первом запуске - в `fsc/_F_ENVLIGHT/_NOTES.md`. Функции не запускались на
стенде.

Для загрузки в Admin модуль собирается в один `.mes` (форма `_F_ENVLIGHT` и
44 функции):

```
python tools/build_mes.py fsc/_F_ENVLIGHT fsc/metaM__F_ENVLIGHT_V04_60.mes
```

Формат записей описан в `Fansy-Foundation/skills/fansy-script/references/
mes-module-format.md`. После правки любого `.fsc` файл нужно пересобрать.

## Не реализовано / открытые вопросы для следующих итераций

- `balance` (входящие остатки) — сознательно отложено, нет платформенного
  документа/категории для этого, требует отдельного проектирования.
- `bank` реализован (`API_FIND_BANK`, `API_SET_BANK`), но на реальной БД не
  прогонялся. Не проверено: реакция триггеров `OD_BANKS` (по сводке они
  меняют `OD_P_FACES`, возможно сами заводят вид деятельности <<банк>>). Если
  так, то `activity: bank` с лицензией (`BEG_LIC`) может создать вторую строку
  рядом с заведённой триггером или упереться в проверку пересечения периодов
  (`OD_EX_PERIOD_INTERSEC`) — проверить на стенде.
- `API_UPD_CLIENT` — нет платформенного аналога, нужна реализация.
- Коллекции: `API_SET_P_FACE` (виды деятельности), `API_FIND_A_FACE`/
  `API_INS_A_FACE` (уполномоченные), `API_FIND_AFFIL`/`API_INS_AFFIL`
  (аффилированные) реализованы в `sql/api_stubs_test_env.sql`, но ещё не
  прогонялись на реальной БД: синтаксис и реакция триггеров `OD_AFFILS`/
  `OD_P_FACES` не проверены. Учтены обе ловушки: NULL в `BEG_LIC` в UNIQUE
  `OD_P_FACES` и симметричный поиск в `OD_A_FACES` (зеркальная связь сейчас
  возвращается молча — ошибкой её не сделали, готового исключения нет).
  Заглушками остались `API_UPD_A_FACE` и `API_UPD_AFFIL`: повторное
  объявление такого блока ничего не изменит.
- `affiliate` с `RELATION=0` (владелец): скорее всего, запись владельца уже
  создана самой вставкой лицевого счёта (триггеры `OD_CLIENTS`), а триггер
  `OD_AFFILS_BI` проверяет владельцев (`OD_EX_CLIENTS_TWOOWNERS`). Проверить
  на стенде, как это ведёт себя в сценарии.
- Замена коллекции целиком (`!replace` — «ровно этот набор кодов и никаких
  больше») не реализована: сейчас поведение всегда слияние/upsert.
- Историчность `client` через `OD_CLIENTS_REC` — сейчас `client` трактуется
  как полностью плоская сущность; известно, что часть атрибутов на самом
  деле версионируется через `OD_CLIENTS_REC` — при необходимости `client`
  тоже обзаведётся `as_of`.
- Реквизиты подключения (DSN/пользователь/пароль для рабочего стенда),
  технический пользователь БД для обвеса (влияет на `OPER`, резолвится
  по `CURRENT_USER` в `OD_OPERATORS`) и механика рестора
  Data-базы между прогонами сценариев — вне кода обвеса, эксплуатационная
  настройка.
- Поля блока `client`, совпадающие по имени с параметрами
  `OD_PR_INSERT_CLIENT` (`NAME`, `D_OPEN`, `IS_MANAGER`, `TARIF` и др., полный
  список — `ClientHandler.INSERT_PARAMS`), передаются в процедуру, остальные её
  параметры уходят по умолчанию. Поля с другими именами движок не использует и
  не проверяет — опечатка в имени поля молча пропадёт.
