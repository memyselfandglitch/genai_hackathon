#!/usr/bin/env bash
# Build backend/Dockerfile with Cloud Build and deploy to Cloud Run (FastAPI + /ui/).
# Usage (from repo root or any cwd):
#   ./scripts/deploy_cloud_run.sh
# Or:
#   PROJECT=my-gcp-project REGION=us-central1 ./scripts/deploy_cloud_run.sh
#
# Optional: mount secrets instead of plain env (recommended):
#   gcloud secrets create GOOGLE_API_KEY --data-file=- <<<"your-key"
#   Grant roles/secretmanager.secretAccessor to the Cloud Run service account, then:
#   gcloud run deploy ... --set-secrets="GOOGLE_API_KEY=GOOGLE_API_KEY:latest"

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

PROJECT="${PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-executive-assistant}"
REPO="${ARTIFACT_REPO:-cloud-run-images}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${SERVICE}:latest"

if [[ -z "${PROJECT}" || "${PROJECT}" == "(unset)" ]]; then
  echo "Set PROJECT or run: gcloud config set project YOUR_PROJECT_ID" >&2
  exit 1
fi

echo "Project: ${PROJECT}  Region: ${REGION}  Service: ${SERVICE}"
gcloud artifacts repositories describe "${REPO}" --location="${REGION}" >/dev/null 2>&1 \
  || gcloud artifacts repositories create "${REPO}" \
      --repository-format=docker \
      --location="${REGION}" \
      --description="Cloud Run images"

gcloud builds submit --tag "${IMAGE}" --project="${PROJECT}" .

if [[ -n "${GOOGLE_API_KEY:-}" ]]; then
  gcloud run deploy "${SERVICE}" \
    --image "${IMAGE}" \
    --region "${REGION}" \
    --project "${PROJECT}" \
    --platform managed \
    --allow-unauthenticated \
    --set-env-vars "GOOGLE_API_KEY=${GOOGLE_API_KEY}"
else
  echo "GOOGLE_API_KEY not set; deploying without it (set in Cloud Console or use --set-secrets)." >&2
  gcloud run deploy "${SERVICE}" \
    --image "${IMAGE}" \
    --region "${REGION}" \
    --project "${PROJECT}" \
    --platform managed \
    --allow-unauthenticated
fi

echo "Done. Service URL:"
gcloud run services describe "${SERVICE}" --region "${REGION}" --project "${PROJECT}" --format='value(status.url)'
