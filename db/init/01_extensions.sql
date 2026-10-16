-- Enable the pg_stat_statements extension.
-- shared_preload_libraries (in docker-compose) LOADS the module;
-- CREATE EXTENSION makes its view available inside this database.
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;