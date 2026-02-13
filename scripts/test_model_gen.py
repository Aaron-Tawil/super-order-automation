
import os
import sys
from google import genai
from google.genai import types

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

def test_generation():
    """Tests generation with gemini-3-pro-preview using default credentials."""
    project_id = os.getenv("GCP_PROJECT_ID", "super-home-automation")
    location = "global"
    model_name = "gemini-2.5-flash"
    
    print(f"Initializing Vertex AI Client (Project: {project_id}, Location: {location})...")
    
    try:
        client = genai.Client(
            vertexai=True,
            project=project_id,
            location=location
        )
        
        print(f"\nAttempting to generate content with {model_name}...")
        response = client.models.generate_content(
            model=model_name,
            contents="Say 'Hello, World!' if you can hear me."
        )
        
        print(f"Success! Response: {response.text}")

    except Exception as e:
        print(f"Error generating content: {e}")

if __name__ == "__main__":
    test_generation()
