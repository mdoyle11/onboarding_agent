#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "Usage: $0 <envelope-id> <employee-email> [base-url]"
  echo "Example: $0 16262271-419d-8c5b-80b5-db9366371e0d mdoyle@bridgeprepacademy.com https://onboarding-agent.mangotree-19278628.eastus.azurecontainerapps.io"
  exit 1
fi

ENVELOPE_ID="$1"
EMPLOYEE_EMAIL="$2"
BASE_URL="${3:-https://onboarding-agent.mangotree-19278628.eastus.azurecontainerapps.io}"

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
