-- =============================================================
-- SERVICE DESK — УДАЛЕНИЕ ХРАНИМЫХ ФУНКЦИЙ (схема sm)
-- Все функции перенесены в Python (models.py).
-- Этот файл удаляет устаревшие хранимые процедуры из БД.
--
-- Запустить при необходимости:
--   psql -U service_desk_user -d service_desk_db -f sql/02_functions.sql
-- =============================================================

DROP FUNCTION IF EXISTS sm.get_ticket_stats(uuid);
DROP FUNCTION IF EXISTS sm.create_user(text, text, text, text, text, text, text, text, text, text);
DROP FUNCTION IF EXISTS sm.reset_password(text);
DROP FUNCTION IF EXISTS sm.hashpassword_postgen(text, text);
DROP FUNCTION IF EXISTS sm.generate_password();
DROP FUNCTION IF EXISTS sm.generate_login(text, text, text);
DROP FUNCTION IF EXISTS sm.translit(text);
