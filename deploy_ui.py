#!/usr/bin/env python3
#!/usr/bin/env python3
"""
Deploy Web UI to Cloud Run
"""
import os
import subprocess
import argparse

# Configuration
PROJECT_ID = os.getenv("GCP_PROJECT_ID", "super-home-automation")
REGION = os.getenv("GCP_REGION", "us-central1")
SERVICE_NAME = "order-dashboard"
IMAGE_NAME = f"gcr.io/{PROJECT_ID}/{SERVICE_NAME}"

def run_command(cmd, check=True):
    print(f"Executing: {cmd}")
    subprocess.run(cmd, shell=True, check=check)

def deploy():
    print("=== Deploying UI to Cloud Run ===")
    
    # 1. Submit build to Cloud Build
    print("\n[1/3] Building container image...")
    run_command(f"gcloud builds submit --config cloudbuild.yaml . --project={PROJECT_ID}")
    
    # 2. Deploy to Cloud Run
    print("\n[2/3] Deploying to Cloud Run...")
    deploy_cmd = (
        f"gcloud run deploy {SERVICE_NAME} "
        f"--image {IMAGE_NAME} "
        f"--platform managed "
        f"--region {REGION} "
        f"--allow-unauthenticated "
        f"--project {PROJECT_ID} "
        f"--set-env-vars=GCP_PROJECT_ID={PROJECT_ID},API_URL=https://{REGION}-{PROJECT_ID}.cloudfunctions.net/order-bot "
    )
    run_command(deploy_cmd)
    
    print("\n[3/3] Deployment Complete!")
    print(f"URL: https://{SERVICE_NAME}-{PROJECT_ID}.a.run.app") # This is a guess, gcloud will output the real one

if __name__ == "__main__":
    deploy()
