#!/bin/sh
set -e

# Fix ownership of the audit data volume on first run.
# The container starts as root so it can chown the mount point,
# then drops privileges to appuser before starting the app.
# This is the same pattern used by the official PostgreSQL and Redis images.
if [ -d /audit_data ]; then
    chown -R appuser:appuser /audit_data
fi

exec gosu appuser "$@"
