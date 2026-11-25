#!/bin/sh
# Runs once on the first primary, with its connection string. Create the service's role and database.
set -eu
psql -q -v ON_ERROR_STOP=1 "$1" <<'SQL'
\getenv user APP_USER
\getenv db APP_DB
\getenv pass APP_PASSWORD
SET log_statement = 'none';
CREATE ROLE :"user" LOGIN PASSWORD :'pass';
CREATE DATABASE :"db" OWNER :"user";
SQL
