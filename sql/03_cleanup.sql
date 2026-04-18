-- Remove unused tables (safe to drop, no FK dependencies from kept tables)
DROP TABLE IF EXISTS sm.ticket_templates CASCADE;
DROP TABLE IF EXISTS sm.audit_log CASCADE;

-- Remove audit() helper call sites in app.py after dropping audit_log
-- ticket_param_values: KEEP (used for comments, internal notes)
-- approval_routes / approval_steps: KEEP schema, no data migration needed
