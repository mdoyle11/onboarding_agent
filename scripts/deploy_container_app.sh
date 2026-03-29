#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 <tfvars-path> [plan|apply]"
  exit 1
fi

TFVARS_PATH="$1"
ACTION="${2:-apply}"
TF_DIR="infra/terraform/container-app"

if [[ ! -f "$TFVARS_PATH" ]]; then
  echo "tfvars file not found: $TFVARS_PATH"
  exit 1
fi

TFVARS_ABS_PATH="$(cd "$(dirname "$TFVARS_PATH")" && pwd)/$(basename "$TFVARS_PATH")"

if ! grep -q '^staff_roster_locations_json[[:space:]]*=' "$TFVARS_PATH"; then
  echo "Note: staff_roster_locations_json is not set in $TFVARS_PATH"
  echo "If you use staff roster mappings, run:"
  echo "  scripts/sync_staff_rosters_to_tfvars.sh $TFVARS_PATH"
fi

case "$ACTION" in
  plan)
    ;;
  apply)
    ;;
  *)
    echo "Invalid action: $ACTION"
    echo "Use 'plan' or 'apply'"
    exit 1
    ;;
esac

cd "$TF_DIR"
terraform init
terraform plan -var-file="$TFVARS_ABS_PATH"

if [[ "$ACTION" == "apply" ]]; then
  terraform apply -var-file="$TFVARS_ABS_PATH"
fi
