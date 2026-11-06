import sys
import asyncio
from pathlib import Path

backend_dir = Path(__file__).resolve().parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn


def main():
    config = uvicorn.Config("app.main:app", host="127.0.0.1", port=8000, reload=False)
    if sys.platform == "win32":
        config.get_loop_factory = lambda: asyncio.SelectorEventLoop
    server = uvicorn.Server(config)
    server.run()


if __name__ == "__main__":
    main()
