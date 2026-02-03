#!/usr/bin/env python3
"""
Deploy Super Order Automation to Google Cloud Functions

This script handles the complete deployment workflow:
1. Stores/updates token.pickle in Secret Manager (base64 encoded)
2. Renews Gmail API Watch
3. Deploys the Cloud Function
4. Verifies deployment

Usage:
    python deploy.py
    python deploy.py --skip-secret
    python deploy.py --skip-watch
    python deploy.py --skip-renew-watch
    python deploy.py --help
"""
import os
import sys
import argparse
import subprocess
import base64
from pathlib import Path

# Configuration
PROJECT_ID = "super-home-automation"
REGION = "us-central1"
FUNCTION_NAME = "order-bot"
PUBSUB_TOPIC = "gmail-incoming-orders"
SECRET_NAME = "super-order-gmail-token"
TOKEN_FILE = "token.pickle"

# Colors for terminal output
class Colors:
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    GRAY = '\033[90m'
    RESET = '\033[0m'
    BOLD = '\033[1m'


def print_header(text):
    print(f"\n{Colors.CYAN}{'='*40}")
    print(f"  {text}")
    print(f"{'='*40}{Colors.RESET}\n")


def print_step(step_num, total, text):
    print(f"{Colors.YELLOW}[{step_num}/{total}] {text}...{Colors.RESET}")


def print_success(text):
    print(f"  {Colors.GREEN}[OK] {text}{Colors.RESET}")


def print_warning(text):
    print(f"  {Colors.YELLOW}[WARN] {text}{Colors.RESET}")


def print_error(text):
    print(f"  {Colors.RED}[ERROR] {text}{Colors.RESET}")


def print_info(text):
    print(f"  {Colors.GRAY}{text}{Colors.RESET}")


def run_command(cmd, capture=False, check=True):
    """Run a shell command and optionally capture output."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,  # Required for Windows (gcloud.cmd)
            capture_output=capture,
            text=True,
            check=check
        )
        return result.stdout.strip() if capture else None
    except subprocess.CalledProcessError as e:
        if check:
            raise
        return None


def check_prerequisites():
    """Verify gcloud CLI is installed and project is set."""
    print_step(1, 5, "Checking prerequisites")
    
    # Check gcloud - use shell=True for Windows compatibility (gcloud.cmd)
    try:
        result = subprocess.run(
            "gcloud --version",
            shell=True,
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            raise FileNotFoundError()
    except FileNotFoundError:
        print_error("gcloud CLI not found. Please install Google Cloud SDK.")
        sys.exit(1)
    
    # Check token file
    if not Path(TOKEN_FILE).exists():
        print_error(f"{TOKEN_FILE} not found. Run 'python src/ingestion/gmail_watch.py' to generate it.")
        sys.exit(1)
    
    # Get current project
    result = subprocess.run(
        "gcloud config get-value project",
        shell=True,
        capture_output=True,
        text=True
    )
    current_project = result.stdout.strip()
    print_info(f"Current project: {current_project}")
    print_success("Prerequisites OK")


def update_secret_manager():
    """Store token.pickle in Secret Manager (base64 encoded)."""
    print_step(2, 5, "Updating token in Secret Manager")
    
    # Check if secret exists
    result = subprocess.run(
        f"gcloud secrets describe {SECRET_NAME} --project={PROJECT_ID}",
        shell=True,
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        print_info(f"Creating new secret: {SECRET_NAME}")
        run_command(f"gcloud secrets create {SECRET_NAME} --project={PROJECT_ID} --replication-policy=automatic")
    
    # Read and base64 encode token
    print_info("Base64 encoding token...")
    with open(TOKEN_FILE, "rb") as f:
        token_bytes = f.read()
    token_base64 = base64.b64encode(token_bytes).decode('utf-8')
    
    # Add new version
    print_info("Adding new secret version...")
    process = subprocess.Popen(
        f"gcloud secrets versions add {SECRET_NAME} --project={PROJECT_ID} --data-file=-",
        shell=True,
        stdin=subprocess.PIPE,
        text=True
    )
    process.communicate(input=token_base64)
    
    if process.returncode == 0:
        print_success("Token updated in Secret Manager")
    else:
        print_error("Failed to update secret")
        sys.exit(1)


def renew_gmail_watch():
    """Renew Gmail API Watch."""
    print_step(3, 5, "Renewing Gmail Watch")
    
    try:
        # Add project root to path
        sys.path.insert(0, str(Path(__file__).parent))
        from src.ingestion.gmail_watch import setup_watch
        setup_watch()
        print_success("Gmail Watch renewed")
    except Exception as e:
        print_warning(f"Gmail Watch renewal failed: {e}")
        print_info("This is non-critical, the existing watch may still be valid")


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


def deploy_function(skip_renew_watch: bool = False):
    """Deploy Cloud Function."""
    print_step(4, 5, "Deploying Cloud Function")
    
    print_info(f"Function: {FUNCTION_NAME}")
    print_info(f"Region: {REGION}")
    print_info(f"Trigger: {PUBSUB_TOPIC}")
    
    # Load env vars
    env_vars = load_env_vars()
    env_string = ",".join(f"{k}={v}" for k, v in env_vars.items()) if env_vars else ""
    
    # Deploy 'order-bot' (Main functionality)
    print_info(f"Deploying {FUNCTION_NAME}...")
    cmd_main = (
        f"gcloud functions deploy {FUNCTION_NAME} "
        f"--gen2 "
        f"--runtime=python311 "
        f"--region={REGION} "
        f"--source=. "
        f"--entry-point=order_bot "
        f"--trigger-topic={PUBSUB_TOPIC} "
        f"--project={PROJECT_ID} "
        f"--memory=512Mi "
        f"--timeout=120s "
        f"--set-secrets=GMAIL_TOKEN={SECRET_NAME}:latest"
    )
    if env_string:
        cmd_main += f" --set-env-vars={env_string}"
    
    result_main = subprocess.run(cmd_main, shell=True)
    if result_main.returncode != 0:
        print_error(f"Failed to deploy {FUNCTION_NAME}")
        sys.exit(1)
    else:
        print_success(f"{FUNCTION_NAME} deployed")

    # Deploy 'renew-watch-orders' (Maintenance functionality)
    if skip_renew_watch:
        print_info("Skipping renew-watch-orders deployment (--skip-renew-watch)")
    else:
        print_info("Deploying renew-watch-orders...")
        cmd_renew = (
            f"gcloud functions deploy renew-watch-orders "
            f"--gen2 "
            f"--runtime=python311 "
            f"--region={REGION} "
            f"--source=. "
            f"--entry-point=renew_watch "
            f"--trigger-http "
            f"--allow-unauthenticated "
            f"--project={PROJECT_ID} "
            f"--memory=512Mi "
            f"--timeout=60s "
            f"--set-secrets=GMAIL_TOKEN={SECRET_NAME}:latest"
        )
        
        result_renew = subprocess.run(cmd_renew, shell=True)
        if result_renew.returncode != 0:
            print_warning("Failed to deploy renew-watch-orders (non-critical if logic didn't change)")
        else:
            print_success("renew-watch-orders deployed")


def verify_deployment():
    """Verify the deployed function is active."""
    print_step(5, 5, "Verifying deployment")
    
    result = run_command(
        f"gcloud functions describe {FUNCTION_NAME} --project={PROJECT_ID} --region={REGION} --format=value(state)",
        capture=True,
        check=False
    )
    
    if result == "ACTIVE":
        print_success("Function 'order-bot' is ACTIVE")
    else:
        print_warning(f"Function 'order-bot' state: {result}")


def print_summary():
    """Print deployment summary."""
    print_header("Deployment Complete!")
    
    print(f"{Colors.BOLD}Order Bot URL:{Colors.RESET}")
    print(f"  {Colors.GRAY}https://{REGION}-{PROJECT_ID}.cloudfunctions.net/{FUNCTION_NAME}{Colors.RESET}")

    print(f"{Colors.BOLD}Renew Watch URL:{Colors.RESET}")
    print(f"  {Colors.GRAY}https://{REGION}-{PROJECT_ID}.cloudfunctions.net/renew-watch-orders{Colors.RESET}")
    
    print(f"\n{Colors.BOLD}Monitor logs:{Colors.RESET}")
    print(f"  {Colors.GRAY}gcloud functions logs read {FUNCTION_NAME} --project={PROJECT_ID} --region={REGION} --limit=20{Colors.RESET}")
    
    print(f"\n{Colors.GREEN}SUCCESS! Send an email to orders.superhome.bot@gmail.com to test!{Colors.RESET}\n")


def main():
    parser = argparse.ArgumentParser(description="Deploy Super Order Automation to GCP")
    parser.add_argument("--skip-secret", action="store_true", help="Skip Secret Manager update")
    parser.add_argument("--skip-watch", action="store_true", help="Skip Gmail Watch renewal (local)")
    parser.add_argument("--skip-renew-watch", action="store_true", help="Skip deploying renew-watch-orders function")
    args = parser.parse_args()
    
    print_header("Super Order Automation - Deployment")
    
    check_prerequisites()
    
    if not args.skip_secret:
        update_secret_manager()
    else:
        print_step(2, 5, "Skipping Secret Manager update (--skip-secret)")
    
    # We can probably skip local watch renewal now that we have the cloud job,
    # but keeping it as a fallback/check is good.
    if not args.skip_watch:
        renew_gmail_watch()
    else:
        print_step(3, 5, "Skipping Gmail Watch renewal (--skip-watch)")
    
    deploy_function(skip_renew_watch=args.skip_renew_watch)
    verify_deployment()
    print_summary()


if __name__ == "__main__":
    main()
