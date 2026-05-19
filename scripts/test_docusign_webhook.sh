#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 || $# -gt 3 ]]; then
  echo "Usage: $0 <envelope-id> <employee-email> <base-url>"
  echo "Example: $0 00000000-0000-0000-0000-000000000000 test.employee@example.com https://your-container-app.region.azurecontainerapps.io"
  exit 1
fi

ENVELOPE_ID="$1"
EMPLOYEE_EMAIL="$2"
BASE_URL="$3"

curl -v -i --max-time 15 -X POST \
  "${BASE_URL}/webhook/docusign" \
  -H "Content-Type: application/json" \
  -d "{
    \"envelopeId\": \"${ENVELOPE_ID}\",
    \"status\": \"completed\",
    \"customFields\": {
      \"textCustomFields\": [
        {
          \"name\": \"employee_email\",
          \"value\": \"${EMPLOYEE_EMAIL}\"
        }
      ]
    }
  }"
