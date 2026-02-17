import os
import sys

from google import genai
from google.genai import types

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))


def list_vertex_models():
    """Lists available Vertex AI models using default credentials."""
    project_id = "super-home-automation"
    location = "us-central1"

    print(f"Initializing Vertex AI Client (Project: {project_id}, Location: {location})...")

    try:
        client = genai.Client(vertexai=True, project=project_id, location=location)

        print("\nFetching available models from Vertex AI...")
        # For Vertex, list might behave differently or need specific calls
        response = client.models.list()

        print(f"{'Name':<60} {'Display Name':<40}")
        print("-" * 100)

        count = 0
        for model in response:
            # Vertex model names are often full paths like projects/.../locations/.../publishers/.../models/...
            # We want to see if 'gemini-3-pro-preview' is in there
            if "gemini" in model.name.lower():
                print(f"{model.name:<60}")
                count += 1

        print("-" * 100)
        print(f"Total Gemini models found: {count}")

    except Exception as e:
        print(f"Error listing Vertex models: {e}")


if __name__ == "__main__":
    list_vertex_models()
