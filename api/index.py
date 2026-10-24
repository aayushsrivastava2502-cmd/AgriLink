"""Vercel Serverless Function entry point for AgriLink AI."""
import sys
from pathlib import Path

# Add project root directory to sys.path so modules are discoverable in serverless execution
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import app
