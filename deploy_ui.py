#!/usr/bin/env python3
#!/usr/bin/env python3
"""
Deploy Web UI to Cloud Run
"""

import argparse
import os
import subprocess
from pathlib import Path

# Configuration
PROJECT_ID = os.getenv("GCP_PROJECT_ID", "super-home-automation")
REGION = os.getenv("GCP_REGION", "us-central1")
SERVICE_NAME = "order-dashboard"
IMAGE_NAME = f"gcr.io/{PROJECT_ID}/{SERVICE_NAME}"
FUNCTION_URL_BASE = f"https://{REGION}-{PROJECT_ID}.cloudfunctions.net"


def run_command(cmd, check=True):
    print(f"Executing: {cmd}")
    subprocess.run(cmd, shell=True, check=check)


def load_env_vars():
    """Load environment variables from .env file."""
    env_vars = {}
    env_file = Path(".env")

    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    env_vars[key.strip()] = value.strip()
    return env_vars


def deploy():
    print("=== Deploying UI to Cloud Run ===")

    # 1. Submit build to Cloud Build
    print("\n[1/3] Building container image...")
    run_command(f"gcloud builds submit --config cloudbuild.yaml . --project={PROJECT_ID}")

    # Load env vars
    env_vars = load_env_vars()
    env_vars["GCP_PROJECT_ID"] = PROJECT_ID
    env_vars["API_URL"] = f"{FUNCTION_URL_BASE}/order-bot"
    env_vars["ENVIRONMENT"] = "cloud"
    env_vars["LOG_LEVEL"] = "DEBUG"

    # Construct env string for gcloud
    env_string = ",".join(f"{k}={v}" for k, v in env_vars.items())

    # 2. Deploy to Cloud Run
    print("\n[2/3] Deploying to Cloud Run...")
    deploy_cmd = (
        f"gcloud run deploy {SERVICE_NAME} "
        f"--image {IMAGE_NAME} "
        f"--platform managed "
        f"--region {REGION} "
        f"--allow-unauthenticated "
        f"--project {PROJECT_ID} "
        f"--set-env-vars={env_string} "
    )
    run_command(deploy_cmd)

    print("\n[3/3] Deployment Complete!")
    # Get actual URL
    try:
        result = subprocess.run(
            f"gcloud run services describe {SERVICE_NAME} --platform managed --region {REGION} --format 'value(status.url)' --project {PROJECT_ID}",
            shell=True,
            capture_output=True,
            text=True,
        )
        url = result.stdout.strip()
        print(f"URL: {url}")
    except Exception:
        print(f"URL: https://{SERVICE_NAME}-{PROJECT_ID}.a.run.app (approx)")


if __name__ == "__main__":
    deploy()
