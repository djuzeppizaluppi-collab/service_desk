# Service Desk

Веб-приложение для автоматизации обработки заявок внутри компании.

## Технологии

- **Backend:** Python 3.10+, Flask, Flask-Login, Flask-SQLAlchemy, Werkzeug
- **Frontend:** HTML, CSS, Vanilla JavaScript (без фреймворков)
- **База данных:** PostgreSQL 14+ (схема `sm`)
- **ORM:** SQLAlchemy

---

## Структура проекта

```
service_desk/
├── app.py                    # Flask-приложение, все маршруты
├── models.py                 # SQLAlchemy-модели (схема sm.)
├── db_functions.py           # Обёртки для PG-функций + Python fallback
├── requirements.txt          # Зависимости Python
├── README.md
├── .gitignore
├── sql/
│   ├── 01_schema.sql         # CREATE SCHEMA, расширения, таблицы
│   └── 02_functions.sql      # Хранимые функции sm.*
├── static/
│   ├── css/style.css
│   └── js/main.js
└── templates/
    ├── base.html
    ├── login.html
    ├── change_password.html
    ├── home.html
    ├── profile.html
    ├── tickets.html
    ├── admin_users.html
    ├── admin_work_groups.html
    ├── admin_categories.html
    ├── create_user.html
    ├── edit_user.html
    ├── create_category.html
    └── edit_category.html
```

---

## Установка и запуск

### 1. Клонирование репозитория

```bash
git clone <URL репозитория>
cd service_desk
```

### 2. Создание виртуального окружения

```bash
python -m venv venv
```

Активация:
- Windows: `venv\Scripts\activate`
- Linux/macOS: `source venv/bin/activate`

### 3. Установка зависимостей

```bash
pip install -r requirements.txt
```

### 4. Настройка PostgreSQL

#### 4.1. Создать пользователя и базу данных

```sql
CREATE USER service_desk_user WITH PASSWORD 'service123';
CREATE DATABASE service_desk_db OWNER service_desk_user;
GRANT ALL PRIVILEGES ON DATABASE service_desk_db TO service_desk_user;
```

#### 4.2. Применить SQL-скрипты

```bash
psql -U service_desk_user -d service_desk_db -f sql/01_schema.sql
psql -U service_desk_user -d service_desk_db -f sql/02_functions.sql
```

Параметры подключения задаются в `app.py` в блоке `DB_CONFIG`:

```python
DB_CONFIG = {
    "user": "service_desk_user",
    "password": "service123",
    "host": "127.0.0.1",
    "port": "5432",
    "database": "service_desk_db"
}

app.config['SQLALCHEMY_DATABASE_URI'] = (
    f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@"
    f"{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}"
)

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
```

### 5. Инициализация таблиц и начальных данных

```bash
flask --app app init-db
```

Команда создаёт все таблицы и наполняет БД:
- Администратор: логин `admin`, пароль `Admin123!`
- 5 рабочих групп: IT, HR, Security, AHO, Finance
- 5 категорий каталога услуг
- Стандартная SLA-политика

### 6. Запуск приложения

```bash
python app.py
```

Приложение будет доступно по адресу: [http://127.0.0.1:5000](http://127.0.0.1:5000)

---

## Схема базы данных (sm.)

Все таблицы расположены в схеме `sm`:

| Таблица | Назначение |
|---|---|
| `sm.users` | Пользователи системы |
| `sm.passwords` | Хэши паролей (отдельно от users) |
| `sm.user_roles` | Роли пользователей (admin/manager/specialist/user) |
| `sm.work_groups` | Рабочие группы (IT, HR, АХО и т.д.) |
| `sm.user_work_groups` | Привязка пользователей к группам (M2M) |
| `sm.sla_policies` | Политики SLA (время ответа и решения) |
| `sm.service_catalog` | Каталог услуг (категории для создания заявок) |
| `sm.tickets` | Заявки |
| `sm.ticket_history` | История изменений каждого поля заявки |
| `sm.ticket_param_values` | Комментарии, согласования (гибкий key-value) |
| `sm.attachments` | Вложения к заявкам |

---

## Хранимые функции PostgreSQL

Функции расположены в схеме `sm`. Приложение пытается вызвать их через `db.session.execute(text(...))`. Если функция недоступна — автоматически применяется Python-реализация из `db_functions.py`.

| Функция | Назначение |
|---|---|
| `sm.generate_login(last, first, middle)` | Генерация логина: транслитерация + уникальность |
| `sm.generate_password()` | Генерация временного пароля (буквы, цифры, спецсимволы) |
| `sm.create_user(...)` | Создание пользователя + сброс пароля |
| `sm.reset_password(username)` | Генерация нового временного пароля |
| `sm.translit(text)` | Транслитерация кириллицы в латиницу |
| `sm.hashpassword_postgen(user, password)` | Хэширование пароля через pgcrypto |
| `sm.generate_login(...)` | Генерация уникального логина |

> **Примечание:** В `sm.hashpassword_postgen` в исходном SQL порядок аргументов — `(p_password, p_username)`, однако внутри функции они используются наоборот. Приложение обходит это: после вызова PG-функции хэш всегда перезаписывается Werkzeug-хэшем, чтобы `check_password_hash()` корректно работал.

---

## Роли пользователей

| Роль | Описание |
|---|---|
| `admin` | Полный доступ: все пользователи, все заявки, все группы |
| `manager` | Руководитель: заявки своей группы, согласование, переназначение |
| `specialist` | Специалист: берёт заявки своей группы в работу, комментирует |
| `user` | Обычный пользователь: создаёт заявки, видит только свои |

---

## Рабочие группы

Специалисты привязываются к рабочим группам через `sm.user_work_groups`.  
Каждая категория каталога услуг (`sm.service_catalog`) привязана к одной рабочей группе (`work_group_uid`).  
Специалист видит только заявки категорий, привязанных к его группе.

---

## Основные функции системы

### Авторизация
- Вход по `user_name` (генерируется автоматически: `Иванов.ИО`)
- Обязательная смена пароля при первом входе
- Блокировка после 3 неверных попыток → принудительная смена пароля
- Показать/скрыть пароль, ссылка «Забыли пароль?»

### Главная страница — каталог услуг
- Карточки категорий с иконками
- Создание заявки через модальное окно
- Тип: Запрос (`service_request`) / Инцидент (`incident`)
- Приоритет: Низкий / Средний / Высокий / Критический

### Профиль пользователя
- Просмотр и редактирование личных данных
- Отображение рабочей группы, должности, телефонов
- Список своих заявок с фильтрацией по статусу и дате
- Редактирование заявки в статусе «Новая»

### Доска заявок (специалисты и выше)
- Канбан: Назначено / В работе / Выполнено
- Статистика сверху
- Фильтры: статус, исполнитель, период
- История изменений каждой заявки
- Внутренние комментарии (видны только специалистам)
- Согласование заявок (руководитель / администратор)

### Администрирование
- Создание пользователей (логин генерируется автоматически через `sm.generate_login`)
- Сброс пароля с отображением нового временного пароля
- Управление рабочими группами
- Управление категориями каталога услуг

---

## Процесс согласования

При создании заявки типа `service_request` в `sm.ticket_param_values` записывается `param_name='requires_approval'`. Руководитель или администратор видит блок согласования в модальном окне и может одобрить или отклонить заявку. Решение сохраняется в `ticket_param_values` с `param_type='approval'`, а изменение статуса фиксируется в `sm.ticket_history`.

---

## История изменений

Любое изменение поля заявки (статус, исполнитель, описание, приоритет) фиксируется в `sm.ticket_history` с указанием старого значения, нового значения, автора изменения и времени. История отображается в модальном окне заявки на доске (раскрывающийся блок).




CREATE OR REPLACE FUNCTION anon.prepare_anonymize_job_by_pk(
    p_table           regclass,
    p_pk_column       name,
    p_planned_workers integer,
    p_batch_size      bigint DEFAULT 200000,
    p_min_id          bigint DEFAULT NULL,
    p_max_id          bigint DEFAULT NULL,
    p_extra_where     text DEFAULT NULL
)
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE
    v_qtable text;
    v_pk_type regtype;
    v_min_id bigint;
    v_max_id bigint;
    v_job_id bigint;
BEGIN
    IF p_planned_workers < 1 THEN
        RAISE EXCEPTION 'p_planned_workers должен быть >= 1';
    END IF;

    IF p_batch_size < 1 THEN
        RAISE EXCEPTION 'p_batch_size должен быть >= 1';
    END IF;

    SELECT format('%I.%I', n.nspname, c.relname)
    INTO v_qtable
    FROM pg_class c
    JOIN pg_namespace n
        ON n.oid = c.relnamespace
    WHERE c.oid = p_table::oid;

    IF v_qtable IS NULL THEN
        RAISE EXCEPTION 'Таблица % не найдена', p_table;
    END IF;

    SELECT a.atttypid::regtype
    INTO v_pk_type
    FROM pg_attribute a
    WHERE a.attrelid = p_table::oid
      AND a.attname = p_pk_column
      AND a.attnum > 0
      AND NOT a.attisdropped;

    IF v_pk_type IS NULL THEN
        RAISE EXCEPTION 'Колонка % не найдена в таблице %', p_pk_column, p_table;
    END IF;

    IF v_pk_type NOT IN (
        'smallint'::regtype,
        'integer'::regtype,
        'bigint'::regtype
    ) THEN
        RAISE EXCEPTION 'PK-колонка % имеет тип %. Поддерживаются smallint/integer/bigint',
            p_pk_column,
            v_pk_type;
    END IF;

    IF p_min_id IS NULL OR p_max_id IS NULL THEN
        EXECUTE format(
            'SELECT min(%1$I)::bigint, max(%1$I)::bigint FROM %2$s',
            p_pk_column,
            v_qtable
        )
        INTO v_min_id, v_max_id;
    ELSE
        v_min_id := p_min_id;
        v_max_id := p_max_id;
    END IF;

    IF v_min_id IS NULL OR v_max_id IS NULL THEN
        RAISE EXCEPTION 'Таблица % пустая или PK полностью NULL', p_table;
    END IF;

    IF v_min_id > v_max_id THEN
        RAISE EXCEPTION 'Некорректные границы: min_id=% > max_id=%', v_min_id, v_max_id;
    END IF;

    INSERT INTO anon.anonymize_job (
        table_oid,
        table_name,
        pk_column,
        min_id,
        max_id,
        batch_size,
        planned_workers,
        extra_where,
        status
    )
    VALUES (
        p_table::oid,
        v_qtable,
        p_pk_column,
        v_min_id,
        v_max_id,
        p_batch_size,
        p_planned_workers,
        p_extra_where,
        'created'
    )
    RETURNING job_id INTO v_job_id;

    INSERT INTO anon.anonymize_job_chunk (
        job_id,
        chunk_no,
        from_id,
        to_id
    )
    SELECT
        v_job_id,
        row_number() OVER (ORDER BY gs)::integer AS chunk_no,
        gs AS from_id,
        least(gs + p_batch_size, v_max_id + 1) AS to_id
    FROM generate_series(v_min_id, v_max_id, p_batch_size) AS gs;

    RAISE NOTICE 'Created anonymize job %, table=%, range=[%, %], batch_size=%, planned_workers=%',
        v_job_id,
        v_qtable,
        v_min_id,
        v_max_id,
        p_batch_size,
        p_planned_workers;

    RETURN v_job_id;
END;
$$;
3. Процедура выполнения job

Эту процедуру запускаешь в нескольких окнах DBeaver одинаково.

CREATE OR REPLACE PROCEDURE anon.run_anonymize_job_by_pk(
    p_job_id        bigint,
    p_dry_run       boolean DEFAULT false,
    p_limit_chunks  integer DEFAULT NULL,
    p_stop_on_error boolean DEFAULT false
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_table_oid    oid;
    v_qtable       text;
    v_pk_column    name;
    v_extra_where  text;
    v_where_sql    text := '';

    v_set_clause   text;

    v_chunk_id     bigint;
    v_chunk_no     integer;
    v_from_id      bigint;
    v_to_id        bigint;

    v_sql          text;
    v_rows         bigint;
    v_done_chunks  integer := 0;
    v_total_rows   bigint := 0;

    v_error_text   text;
    v_error_state  text;
BEGIN
    SELECT
        table_oid,
        table_name,
        pk_column,
        extra_where
    INTO
        v_table_oid,
        v_qtable,
        v_pk_column,
        v_extra_where
    FROM anon.anonymize_job
    WHERE job_id = p_job_id;

    IF v_table_oid IS NULL THEN
        RAISE EXCEPTION 'Job % не найден', p_job_id;
    END IF;

    /*
      Собираем SET-часть:
      - MASKED WITH FUNCTION берем из masking_filter, если trusted_schema = true.
      - MASKED WITH VALUE берем либо из masking_filter, либо вытаскиваем из col_description.
    */
    SELECT string_agg(
               format('%I = %s', x.attname, x.mask_expr),
               ', ' ORDER BY x.attnum
           )
    INTO v_set_clause
    FROM (
        SELECT
            r.attnum,
            r.attname,
            COALESCE(
                r.masking_filter,
                regexp_replace(
                    r.col_description,
                    '^MASKED[[:space:]]+WITH[[:space:]]+VALUE[[:space:]]+',
                    '',
                    'i'
                )
            ) AS mask_expr
        FROM anon.pg_masking_rules r
        WHERE r.attrelid = v_table_oid
          AND (
                r.masking_filter IS NOT NULL
                OR r.col_description ~* '^MASKED[[:space:]]+WITH[[:space:]]+VALUE[[:space:]]+'
              )
          AND (
                r.col_description ~* '^MASKED[[:space:]]+WITH[[:space:]]+VALUE[[:space:]]+'
                OR COALESCE(r.trusted_schema, false) = true
              )
    ) x;

    IF v_set_clause IS NULL OR btrim(v_set_clause) = '' THEN
        RAISE EXCEPTION 'Для job % / таблицы % не найдено правил маскировки',
            p_job_id,
            v_qtable;
    END IF;

    IF v_extra_where IS NOT NULL AND btrim(v_extra_where) <> '' THEN
        v_where_sql := format(' AND (%s)', v_extra_where);
    ELSE
        v_where_sql := '';
    END IF;

    UPDATE anon.anonymize_job
    SET
        status = 'running',
        started_at = COALESCE(started_at, clock_timestamp())
    WHERE job_id = p_job_id
      AND status IN ('created', 'running', 'failed');

    COMMIT;

    LOOP
        EXIT WHEN p_limit_chunks IS NOT NULL AND v_done_chunks >= p_limit_chunks;

        v_chunk_id := NULL;
        v_chunk_no := NULL;
        v_from_id := NULL;
        v_to_id := NULL;

        WITH picked AS (
            SELECT c.chunk_id
            FROM anon.anonymize_job_chunk c
            WHERE c.job_id = p_job_id
              AND c.status = 'pending'
            ORDER BY c.chunk_no
            FOR UPDATE SKIP LOCKED
            LIMIT 1
        )
        UPDATE anon.anonymize_job_chunk c
        SET
            status = 'in_progress',
            worker_pid = pg_backend_pid(),
            attempt_no = attempt_no + 1,
            started_at = clock_timestamp(),
            last_heartbeat = clock_timestamp(),
            finished_at = NULL,
            error_text = NULL
        FROM picked p
        WHERE c.chunk_id = p.chunk_id
        RETURNING
            c.chunk_id,
            c.chunk_no,
            c.from_id,
            c.to_id
        INTO
            v_chunk_id,
            v_chunk_no,
            v_from_id,
            v_to_id;

        IF v_chunk_id IS NULL THEN
            EXIT;
        END IF;

        COMMIT;

        v_sql := format(
            'UPDATE %1$s
                SET %2$s
              WHERE %3$I >= %4$L
                AND %3$I <  %5$L
                %6$s',
            v_qtable,
            v_set_clause,
            v_pk_column,
            v_from_id,
            v_to_id,
            v_where_sql
        );

        IF p_dry_run THEN
            RAISE NOTICE 'DRY RUN job %, chunk %, range=[%, %): %',
                p_job_id,
                v_chunk_no,
                v_from_id,
                v_to_id,
                v_sql;

            UPDATE anon.anonymize_job_chunk
            SET
                status = 'pending',
                worker_pid = NULL,
                started_at = NULL,
                last_heartbeat = NULL,
                finished_at = NULL,
                rows_updated = NULL,
                error_text = NULL
            WHERE chunk_id = v_chunk_id;

            COMMIT;

            v_done_chunks := v_done_chunks + 1;
        ELSE
            v_error_text := NULL;
            v_error_state := NULL;
            v_rows := 0;

            RAISE NOTICE 'job %, chunk % started, range=[%, %), pid=%',
                p_job_id,
                v_chunk_no,
                v_from_id,
                v_to_id,
                pg_backend_pid();

            BEGIN
                EXECUTE v_sql;
                GET DIAGNOSTICS v_rows = ROW_COUNT;
            EXCEPTION
                WHEN OTHERS THEN
                    v_error_text := SQLERRM;
                    v_error_state := SQLSTATE;
            END;

            IF v_error_text IS NULL THEN
                UPDATE anon.anonymize_job_chunk
                SET
                    status = 'done',
                    rows_updated = v_rows,
                    last_heartbeat = clock_timestamp(),
                    finished_at = clock_timestamp(),
                    error_text = NULL
                WHERE chunk_id = v_chunk_id;

                COMMIT;

                v_done_chunks := v_done_chunks + 1;
                v_total_rows := v_total_rows + v_rows;

                RAISE NOTICE 'job %, chunk % done, rows=%, total_rows_this_session=%',
                    p_job_id,
                    v_chunk_no,
                    v_rows,
                    v_total_rows;
            ELSE
                UPDATE anon.anonymize_job_chunk
                SET
                    status = 'failed',
                    rows_updated = NULL,
                    last_heartbeat = clock_timestamp(),
                    finished_at = clock_timestamp(),
                    error_text = format('[%s] %s', v_error_state, v_error_text)
                WHERE chunk_id = v_chunk_id;

                COMMIT;

                RAISE NOTICE 'job %, chunk % failed: [%] %',
                    p_job_id,
                    v_chunk_no,
                    v_error_state,
                    v_error_text;

                IF p_stop_on_error THEN
                    RAISE EXCEPTION 'Job %, chunk % failed: [%] %',
                        p_job_id,
                        v_chunk_no,
                        v_error_state,
                        v_error_text;
                END IF;
            END IF;
        END IF;
    END LOOP;

    IF NOT EXISTS (
        SELECT 1
        FROM anon.anonymize_job_chunk
        WHERE job_id = p_job_id
          AND status IN ('pending', 'in_progress')
    ) THEN
        UPDATE anon.anonymize_job
        SET
            status = CASE
                WHEN EXISTS (
                    SELECT 1
                    FROM anon.anonymize_job_chunk
                    WHERE job_id = p_job_id
                      AND status = 'failed'
                )
                THEN 'failed'
                ELSE 'done'
            END,
            finished_at = clock_timestamp()
        WHERE job_id = p_job_id;

        COMMIT;
    END IF;

    RAISE NOTICE 'session finished. job=%, chunks_processed_this_session=%, rows_updated_this_session=%',
        p_job_id,
        v_done_chunks,
        v_total_rows;
END;
$$;


4. Функция сброса failed / зависших in_progress

   
CREATE OR REPLACE FUNCTION anon.reset_anonymize_job_chunks(
    p_job_id bigint,
    p_reset_failed boolean DEFAULT true,
    p_reset_stale_in_progress boolean DEFAULT true,
    p_stale_interval interval DEFAULT interval '30 minutes'
)
RETURNS TABLE (
    reset_status text,
    reset_count bigint
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_count bigint;
BEGIN
    IF p_reset_failed THEN
        UPDATE anon.anonymize_job_chunk
        SET
            status = 'pending',
            worker_pid = NULL,
            started_at = NULL,
            last_heartbeat = NULL,
            finished_at = NULL,
            rows_updated = NULL,
            error_text = NULL
        WHERE job_id = p_job_id
          AND status = 'failed';

        GET DIAGNOSTICS v_count = ROW_COUNT;

        reset_status := 'failed_to_pending';
        reset_count := v_count;
        RETURN NEXT;
    END IF;

    IF p_reset_stale_in_progress THEN
        UPDATE anon.anonymize_job_chunk
        SET
            status = 'pending',
            worker_pid = NULL,
            started_at = NULL,
            last_heartbeat = NULL,
            finished_at = NULL,
            rows_updated = NULL,
            error_text = 'reset from stale in_progress'
        WHERE job_id = p_job_id
          AND status = 'in_progress'
          AND started_at < clock_timestamp() - p_stale_interval;

        GET DIAGNOSTICS v_count = ROW_COUNT;

        reset_status := 'stale_in_progress_to_pending';
        reset_count := v_count;
        RETURN NEXT;
    END IF;

    UPDATE anon.anonymize_job
    SET
        status = 'created',
        finished_at = NULL
    WHERE job_id = p_job_id
      AND EXISTS (
          SELECT 1
          FROM anon.anonymize_job_chunk
          WHERE job_id = p_job_id
            AND status = 'pending'
      );

END;
$$;
5. Создать job для полной обработки таблицы
SELECT anon.prepare_anonymize_job_by_pk(
    p_table           => 'ourpension.individual'::regclass,
    p_pk_column       => 'id'::name,
    p_planned_workers => 8,
    p_batch_size      => 200000,
    p_min_id          => 2,
    p_max_id          => 14112685,
    p_extra_where     => NULL
) AS job_id;

Допустим, вернулся:

job_id = 7
6. Создать job только по строкам, где осталась кириллица
SELECT anon.prepare_anonymize_job_by_pk(
    p_table           => 'ourpension.individual'::regclass,
    p_pk_column       => 'id'::name,
    p_planned_workers => 8,
    p_batch_size      => 200000,
    p_min_id          => 2,
    p_max_id          => 14112685,
    p_extra_where     => $where$
        birth_first_name ~ '[А-Яа-яЁё]'
        OR birth_last_name ~ '[А-Яа-яЁё]'
        OR birth_middle_name ~ '[А-Яа-яЁё]'
    $where$
) AS job_id;
7. Проверочный dry run

Например job 7, проверить первые 2 куска:

CALL anon.run_anonymize_job_by_pk(
    p_job_id       => 7,
    p_dry_run      => true,
    p_limit_chunks => 2
);
8. Реальный запуск

В 8 окнах DBeaver запускаешь один и тот же вызов:

CALL anon.run_anonymize_job_by_pk(7, false);

Ничего менять по окнам не нужно. Каждая сессия сама заберет свободные pending-куски.

9. Мониторинг
SELECT
    status,
    count(*) AS chunks,
    sum(rows_updated) AS rows_updated
FROM anon.anonymize_job_chunk
WHERE job_id = 7
GROUP BY status
ORDER BY status;

Подробно:

SELECT
    chunk_no,
    from_id,
    to_id,
    status,
    worker_pid,
    attempt_no,
    rows_updated,
    started_at,
    finished_at,
    error_text
FROM anon.anonymize_job_chunk
WHERE job_id = 7
ORDER BY chunk_no;
10. Если что-то упало — перезапуск непройденных

Сначала сбросить failed и старые зависшие in_progress обратно в pending:

SELECT *
FROM anon.reset_anonymize_job_chunks(
    p_job_id => 7,
    p_reset_failed => true,
    p_reset_stale_in_progress => true,
    p_stale_interval => interval '30 minutes'
);

Потом снова запускаешь:

CALL anon.run_anonymize_job_by_pk(7, false);
