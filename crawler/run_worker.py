import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent / "src"
sys.path.insert(0, str(ROOT))

from worker.consumer import main

if __name__ == "__main__":
    import asyncio, sys
    print("sys.path:", sys.path)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Interrupted")
