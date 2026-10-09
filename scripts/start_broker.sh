#!/bin/sh
# The existing Java constructors require their own broker usernames.
set -eu
rabbitmq-server &
pid=$!
trap 'kill -TERM "$pid"; wait "$pid"' TERM INT
attempt=0
until rabbitmqctl await_startup >/dev/null 2>&1; do
	attempt=$((attempt + 1))
	if [ "$attempt" -ge 60 ]; then
		kill -TERM "$pid"
		wait "$pid"
		exit 1
	fi
	sleep 1
done
rabbitmqctl add_user applicant "$APPLICANT_BROKER_PASSWORD" >/dev/null 2>&1 || rabbitmqctl change_password applicant "$APPLICANT_BROKER_PASSWORD" >/dev/null
rabbitmqctl set_permissions -p / applicant '.*' '.*' '.*' >/dev/null
rabbitmqctl add_user credential "$CREDENTIAL_BROKER_PASSWORD" >/dev/null 2>&1 || rabbitmqctl change_password credential "$CREDENTIAL_BROKER_PASSWORD" >/dev/null
rabbitmqctl set_permissions -p / credential '.*' '.*' '.*' >/dev/null
touch /tmp/lab2-broker-users-ready
wait "$pid"
