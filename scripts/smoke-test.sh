#!/usr/bin/env bash
set -euo pipefail

LANGUAGE="${1:-shona}"
CATEGORY="${2:-H03}"
SEVERITY="${3:-S2}"

echo "AfriGuard smoke test"
echo "Language: ${LANGUAGE} | Category: ${CATEGORY} | Severity: ${SEVERITY}"

if [ ! -f ".env" ]; then
  echo "Creating .env from .env.example"
  cp .env.example .env
fi

echo "Installing package and runtime dependencies..."
python -m pip install -r requirements.txt

echo "Initializing database..."
afriguard bootstrap-db

echo "Running dry generation check..."
afriguard generate --language "${LANGUAGE}" --category "${CATEGORY}" --severity "${SEVERITY}" --n-prompts 1 --dry-run

echo "Smoke test completed. Add OPENAI_API_KEY to .env before a real generation run."
