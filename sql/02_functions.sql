-- =============================================================
-- SERVICE DESK — STORED FUNCTIONS (схема sm)
-- Запустить после 01_schema.sql:
--   psql -U service_desk_user -d service_desk_db -f sql/02_functions.sql
--
-- ВАЖНО: функция sm.hashpassword_postgen имеет исправленный
-- порядок аргументов по сравнению с оригиналом.
-- Приложение всегда перезаписывает хэш через Werkzeug,
-- поэтому PG-хэш используется только как дополнительный слой.
-- =============================================================

-- -------------------------------------------------------------
-- sm.translit — транслитерация кириллицы в латиницу
-- -------------------------------------------------------------
CREATE OR REPLACE FUNCTION sm.translit(p_to_translit text)
RETURNS text
LANGUAGE plpgsql
STABLE
AS $function$
DECLARE
    v_rus_chars text[] := ARRAY[
        'А','Б','В','Г','Д','Е','Ё','Ж','З','И','Й','К','Л','М','Н',
        'О','П','Р','С','Т','У','Ф','Х','Ц','Ч','Ш','Щ','Ы','Э','Ю','Я','Ь','Ъ'
    ];
    v_eng_chars text[] := ARRAY[
        'A','B','V','G','D','E','YO','ZH','Z','I','Y','K','L','M','N',
        'O','P','R','S','T','U','F','KH','C','CH','SH','SHH','Y','E','YU','YA','',''
    ];
    v_current_char text;
    v_res          text := '';
    v_char_index   int;
BEGIN
    IF p_to_translit IS NOT NULL THEN
        FOR i IN 1..length(p_to_translit) LOOP
            v_current_char := substr(p_to_translit, i, 1);
            v_char_index   := ARRAY_POSITION(v_rus_chars, upper(v_current_char));
            IF v_char_index IS NOT NULL THEN
                v_res := v_res || v_eng_chars[v_char_index];
            END IF;
        END LOOP;
    END IF;
    RETURN v_res;
EXCEPTION WHEN OTHERS THEN
    RAISE EXCEPTION 'sm.translit failed: %', SQLERRM;
END;
$function$;


-- -------------------------------------------------------------
-- sm.generate_login — генерация уникального логина
-- Формат: Familiya.IO  (транслит, до 8 символов фамилии)
-- -------------------------------------------------------------
CREATE OR REPLACE FUNCTION sm.generate_login(
    p_lastname   text,
    p_firstname  text,
    p_middlename text
)
RETURNS text
LANGUAGE plpgsql
AS $function$
DECLARE
    v_base_login text;
    v_res_login  text;
    v_cnt        int := 0;
BEGIN
    p_lastname   := SUBSTR(sm.translit(p_lastname),   1, 8);
    p_firstname  := SUBSTR(sm.translit(p_firstname),  1, 1);
    p_middlename := CASE WHEN p_middlename IS NOT NULL
                         THEN SUBSTR(sm.translit(p_middlename), 1, 1)
                         ELSE '' END;

    IF p_lastname IS NOT NULL AND p_firstname IS NOT NULL
       AND p_lastname != '' AND p_firstname != '' THEN

        v_base_login := CONCAT(p_lastname, '.', p_firstname, p_middlename);
        v_res_login  := v_base_login;

        WHILE EXISTS (SELECT 1 FROM sm.users WHERE user_name = v_res_login) LOOP
            v_cnt       := v_cnt + 1;
            v_res_login := CONCAT(v_base_login, v_cnt);
        END LOOP;

        RETURN v_res_login;
    ELSE
        RAISE EXCEPTION 'sm.generate_login: last_name and first_name are required';
    END IF;
EXCEPTION WHEN OTHERS THEN
    RAISE EXCEPTION 'sm.generate_login failed: %', SQLERRM;
END;
$function$;


-- -------------------------------------------------------------
-- sm.generate_password — генерация временного пароля
-- Гарантирует наличие букв, цифры и спецсимвола.
-- Использует shuffle через ORDER BY random() (без array_shuffle).
-- -------------------------------------------------------------
CREATE OR REPLACE FUNCTION sm.generate_password()
RETURNS text
LANGUAGE plpgsql
AS $function$
DECLARE
    v_chars      text[] := ARRAY[
        'a','b','c','d','e','f','g','h','i','j','k','l','m',
        'n','o','p','q','r','s','t','u','v','w','x','y','z',
        'A','B','C','D','E','F','G','H','I','J','K','L','M',
        'N','O','P','Q','R','S','T','U','V','W','X','Y','Z'
    ];
    v_numbers    text[] := ARRAY['1','2','3','4','5','6','7','8','9','0'];
    v_spec_chars text[] := ARRAY['!','@','#','$','%','&','*'];
    v_all_chars  text[];
    v_parts      text[];
    v_result     text;
BEGIN
    v_all_chars := v_chars || v_numbers || v_spec_chars;

    -- Гарантированные символы каждого класса
    v_parts := ARRAY[
        v_chars     [1 + floor(random() * array_length(v_chars,     1))::int],
        v_chars     [1 + floor(random() * array_length(v_chars,     1))::int + 26], -- upper
        v_numbers   [1 + floor(random() * array_length(v_numbers,   1))::int],
        v_spec_chars[1 + floor(random() * array_length(v_spec_chars,1))::int]
    ];

    -- Добавляем 8 случайных символов
    FOR i IN 1..8 LOOP
        v_parts := array_append(v_parts,
            v_all_chars[1 + floor(random() * array_length(v_all_chars, 1))::int]);
    END LOOP;

    -- Перемешиваем (без array_shuffle — через subquery)
    SELECT string_agg(ch, '' ORDER BY random())
    INTO   v_result
    FROM   unnest(v_parts) AS ch;

    RETURN v_result;
EXCEPTION WHEN OTHERS THEN
    RAISE EXCEPTION 'sm.generate_password failed: %', SQLERRM;
END;
$function$;


-- -------------------------------------------------------------
-- sm.hashpassword_postgen — хэширование пароля (pgcrypto)
-- ИСПРАВЛЕНО: правильный порядок аргументов (p_username, p_password)
-- -------------------------------------------------------------
CREATE OR REPLACE FUNCTION sm.hashpassword_postgen(
    p_username text,
    p_password text
)
RETURNS text
LANGUAGE plpgsql
AS $function$
DECLARE
    v_user_uid uuid;
BEGIN
    SELECT user_uid INTO v_user_uid
    FROM sm.users
    WHERE user_name = p_username;

    IF v_user_uid IS NULL THEN
        RETURN CONCAT('ERROR: User: ', p_username, ' is not found');
    END IF;

    IF p_password IS NOT NULL THEN
        -- Werkzeug-хэш будет записан приложением поверх этого.
        -- Здесь сохраняем дополнительный pgcrypto-хэш.
        IF EXISTS (SELECT 1 FROM sm.passwords WHERE user_uid = v_user_uid) THEN
            UPDATE sm.passwords
            SET    passwordhash = crypt(p_password, gen_salt('bf', 8))
            WHERE  user_uid = v_user_uid;
            RETURN 'SUCCESS: Hashpassword has been updated';
        ELSE
            INSERT INTO sm.passwords (user_uid, passwordhash)
            VALUES (v_user_uid, crypt(p_password, gen_salt('bf', 8)));
            RETURN 'SUCCESS: Hashpassword has been inserted';
        END IF;
    ELSE
        RETURN 'ERROR: input password is null';
    END IF;
EXCEPTION WHEN OTHERS THEN
    RAISE EXCEPTION 'sm.hashpassword_postgen failed: %', SQLERRM;
END;
$function$;


-- -------------------------------------------------------------
-- sm.reset_password — сброс пароля пользователя
-- -------------------------------------------------------------
CREATE OR REPLACE FUNCTION sm.reset_password(p_username text)
RETURNS text
LANGUAGE plpgsql
AS $function$
DECLARE
    v_password text;
    v_res      text;
BEGIN
    IF EXISTS (SELECT 1 FROM sm.users WHERE user_name = p_username) THEN
        v_password := sm.generate_password();
        v_res      := sm.hashpassword_postgen(p_username, v_password);

        -- Уведомление для внешних слушателей (опционально)
        PERFORM pg_notify(
            'reset_password_channel',
            json_build_object(
                'user_name', p_username,
                'password',  v_password,
                'status',    v_res
            )::text
        );

        RETURN v_res;
    ELSE
        RETURN CONCAT('ERROR: User: ', p_username, ' is not found');
    END IF;
EXCEPTION WHEN OTHERS THEN
    RAISE EXCEPTION 'sm.reset_password failed: %', SQLERRM;
END;
$function$;


-- -------------------------------------------------------------
-- sm.create_user — создание пользователя
-- Возвращает сгенерированный логин.
-- -------------------------------------------------------------
CREATE OR REPLACE FUNCTION sm.create_user(
    p_last_name   text,
    p_first_name  text,
    p_middel_name text,
    p_email       text,
    p_mobile      text,
    p_work_phone  text,
    p_gender      text,
    p_title       text,
    p_department  text,
    p_company     text
)
RETURNS text
LANGUAGE plpgsql
AS $function$
DECLARE
    v_user_name text;
    v_mobile    text;
    v_digits    text;
    v_gender    bpchar(1);
    v_sys_uid   uuid := '00000000-0000-0000-0000-000000000001'::uuid;
BEGIN
    v_user_name   := sm.generate_login(p_last_name, p_first_name, p_middel_name);
    p_middel_name := COALESCE(p_middel_name, '');

    IF v_user_name IS NULL OR p_email IS NULL THEN
        RAISE EXCEPTION 'sm.create_user: cannot generate login or email is NULL';
    END IF;

    -- Нормализация пола
    IF p_gender IS NOT NULL THEN
        CASE upper(trim(p_gender))
            WHEN 'М', 'M', 'МУЖСКОЙ', 'MALE'   THEN v_gender := 'M';
            WHEN 'Ж', 'F', 'ЖЕНСКИЙ', 'FEMALE'  THEN v_gender := 'F';
            ELSE                                      v_gender := 'O';
        END CASE;
    END IF;

    -- Нормализация мобильного
    IF p_mobile IS NOT NULL THEN
        v_digits := regexp_replace(p_mobile, '\D', '', 'g');
        IF length(v_digits) >= 10 THEN
            v_digits := right(v_digits, 10);
            v_mobile := format('+7 (%s) %s-%s-%s',
                substring(v_digits, 1, 3),
                substring(v_digits, 4, 3),
                substring(v_digits, 7, 2),
                substring(v_digits, 9, 2));
        END IF;
    END IF;

    INSERT INTO sm.users (
        user_name, first_name, last_name, middel_name,
        email, work_phone, title, department, company,
        gender, mobile, create_by
    ) VALUES (
        v_user_name, p_first_name, p_last_name, NULLIF(p_middel_name, ''),
        p_email, p_work_phone, p_title, p_department, p_company,
        v_gender, v_mobile, v_sys_uid
    );

    PERFORM sm.reset_password(v_user_name);

    RETURN v_user_name;

EXCEPTION WHEN OTHERS THEN
    RAISE EXCEPTION 'sm.create_user failed: %', SQLERRM;
END;
$function$;


-- -------------------------------------------------------------
-- sm.get_ticket_stats — статистика заявок по группе
-- Используется для быстрой агрегации на доске
-- -------------------------------------------------------------
CREATE OR REPLACE FUNCTION sm.get_ticket_stats(p_work_group_uid uuid DEFAULT NULL)
RETURNS TABLE (
    status        text,
    ticket_count  bigint
)
LANGUAGE sql
STABLE
AS $function$
    SELECT t.status, COUNT(*) AS ticket_count
    FROM   sm.tickets t
    JOIN   sm.service_catalog sc ON sc.catalog_uid = t.catalog_uid
    WHERE  (p_work_group_uid IS NULL OR sc.work_group_uid = p_work_group_uid)
    GROUP  BY t.status;
$function$;
