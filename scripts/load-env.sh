#!/bin/bash
# Load .env safely in Bash, normalizing Windows CRLF line endings.

if [ -f .env ]; then
    set -a
    source <(tr -d '\r' < .env)
    set +a
fi
