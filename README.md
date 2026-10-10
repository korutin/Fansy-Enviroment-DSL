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
  sql/        заглушки недостающих процедур API_* для стенда
              (+ draft_api_ins_client.sql — черновик, не накатывается)
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
- `face` и `share` — исторические сущности. Повтор блока с тем же алиасом
  требует `as_of=YYYY-MM-DD` (строго возрастающие даты) и вызывает
  `API_UPD_FACE`/`API_UPD_SHARE` с этой датой. Первое объявление `as_of`
  не принимает.
- `bank_account`, `client`, `bank` — плоские. Повтор блока правит запись на
  месте (`API_UPD_*`, без даты); `as_of` для них — ошибка.
- `balance` зарезервирован, не реализован — использование даёт явную ошибку.
- `include "файл.tenv"` — текстовая подстановка перед разбором.
- `# ...` в начале строки — комментарий.

Вложенные блоки (коллекции) бывают двух классов. Безключевые — `code`
(`OD_FACE_CODERS`) и `activity` (`OD_P_FACES`) — своего `ID` не имеют, запись
сама себе ключ, обслуживаются одной upsert-процедурой `API_SET_*` и не могут
иметь алиас. Идентифицируемые — `attorney` (`OD_A_FACES`) и `affiliate`
(`OD_AFFILS`) — имеют суррогатный `ID`, работают через `API_FIND_*`/`API_INS_*`
и алиас им разрешён.

Допустимая вложенность: `face` → `code`, `activity`, `attorney`;
`client` → `affiliate` (аффилированность в `OD_AFFILS` висит на лицевом
счёте, а не на лице). Нарушение — ошибка компиляции сценария.

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
`API_INS_CLIENT`)/`API_UPD_CLIENT`; `bank` →
`API_FIND_BANK`/`API_INS_BANK`/`API_UPD_BANK`; `code` → `API_SET_FC_CODE`;
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
| `bank` | заглушка целиком | `API_FIND_BANK`/`API_INS_BANK`/`API_UPD_BANK` — заглушки (см. `sql/api_stubs_test_env.sql`), возвращают NULL/no-op |
| `code` | рабочий | `API_SET_FC_CODE` существует в платформе; обязательное поле `CODE` |
| `activity` | заглушка | `API_SET_P_FACE` не реализована; вызов проходит, но данных не создаёт — движок печатает предупреждение (безключевой блок, по возвращаемому значению сбой не поймать) |
| `attorney` | заглушка | `API_*_A_FACE` не реализованы, возвращают NULL → сценарий падает с явной ошибкой |
| `affiliate` | заглушка | `API_*_AFFIL` не реализованы, возвращают NULL → сценарий падает с явной ошибкой |
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

Часть процедур `API_*`, которые нужны обвесу, в платформе отсутствует —
их (заглушки) надо накатить из `sql/api_stubs_test_env.sql`. Скрипт исходит
из того, что на стенде уже есть `API_FIND_CLIENT`: она описана в
`Fansy-Foundation/dBase/proc.sql` и в скрипт не входит. `API_INS_CLIENT` не
существует и не нужна — вставка `client` идёт через `OD_PR_INSERT_CLIENT`
(заготовка процедуры лежит в `sql/draft_api_ins_client.sql`, её не накатывать):

```
isql -u SYSDBA -p *** "fb:d:\data\stand\DATA.fdb" -i sql\api_stubs_test_env.sql
```

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
это не баг, а показатель того, что конкретный блок пока не готов к
реальной работе (см. пример `examples/scenario_example.tenv`, где сценарий
останавливается на блоке `bank`).

## Тесты

```
cd D:\Projecto\Fansy-Enviroment-DSL
python -m unittest discover -s tests
```

Тесты не требуют установленного Firebird-клиента — используют `FakeDatabase`
(скриптуемые ответы для точечных проверок) и работают полностью в памяти.

## Не реализовано / открытые вопросы для следующих итераций

- `balance` (входящие остатки) — сознательно отложено, нет платформенного
  документа/категории для этого, требует отдельного проектирования.
- `bank` как субъект — нужна реализация `API_INS_BANK`/`API_FIND_BANK`/
  `API_UPD_BANK` (сейчас заглушки), по образцу inline-кода в
  `Fansy-Foundation/examples-code/metaM__F_REESTR_V04_59.mes`.
- `API_UPD_CLIENT` — нет платформенного аналога, нужна реализация.
- Коллекции: `API_SET_P_FACE` (виды деятельности), `API_*_A_FACE`
  (уполномоченные), `API_*_AFFIL` (аффилированные) — заглушки с проработанными
  TODO в `sql/api_stubs_test_env.sql`. Отдельно отмечены две ловушки:
  NULL-значения `BEG_LIC` в UNIQUE `OD_P_FACES` (нужно `is null`, иначе дубли
  при каждом прогоне) и симметричный поиск в `OD_A_FACES`, чтобы зеркальное
  описание связи не создавало перевёрнутый дубль.
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
