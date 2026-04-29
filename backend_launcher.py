import multiprocessing
import sys

if getattr(sys, "frozen", False):
    multiprocessing.freeze_support()

import uvicorn
from main import app  # explicit import so PyInstaller bundles main.py

if __name__ == "__main__":
    multiprocessing.freeze_support()
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
