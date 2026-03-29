#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "Usage: $0 <acr-name> <image-tag> [image-repo]"
  exit 1
fi

ACR_NAME="$1"
IMAGE_TAG="$2"
IMAGE_REPO="${3:-onboarding-agent}"

ACR_LOGIN_SERVER="$(az acr show --name "$ACR_NAME" --query loginServer -o tsv)"
IMAGE_REF="${ACR_LOGIN_SERVER}/${IMAGE_REPO}:${IMAGE_TAG}"

echo "Logging in to ACR: ${ACR_NAME}"
az acr login --name "$ACR_NAME"

echo "Building image: ${IMAGE_REF}"
docker build -t "$IMAGE_REF" .

echo "Pushing image: ${IMAGE_REF}"
docker push "$IMAGE_REF"

echo "Done: ${IMAGE_REF}"
