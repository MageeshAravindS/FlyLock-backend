import os
import sys

# Add current directory to path so imports work correctly in Hugging Face
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from server import run_server

if __name__ == "__main__":
    # HuggingFace expects the process to bind to port 7860
    port = int(os.environ.get("PORT", 7860))
    run_server(port)
