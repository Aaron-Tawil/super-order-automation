import os
import sys

# Ensure project root is in path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import Cloud Functions to register them as entry points for GCP
from src.cloud_functions.ingestion_fn import order_bot  # noqa: F401
from src.cloud_functions.processor_fn import process_order_event  # noqa: F401
from src.cloud_functions.watch_fn import renew_watch  # noqa: F401
