import multiprocessing
import sys

if getattr(sys, "frozen", False):
    multiprocessing.freeze_support()

import uvicorn

if __name__ == "__main__":
    multiprocessing.freeze_support()
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        log_level="warning",
    )