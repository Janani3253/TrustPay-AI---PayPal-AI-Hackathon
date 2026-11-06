import os
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
    port = int(os.getenv("PORT", 8000))
    # In cloud environments like Render, bind to 0.0.0.0 to accept traffic
    is_cloud = bool(os.getenv("RENDER") or "PORT" in os.environ or os.getenv("APP_ENV") == "production")
    host = os.getenv("HOST", "0.0.0.0" if is_cloud else "127.0.0.1")
    reload = os.getenv("APP_ENV", "").lower() == "development" and not is_cloud

    config = uvicorn.Config("app.main:app", host=host, port=port, reload=reload)
    if sys.platform == "win32":
        config.get_loop_factory = lambda: asyncio.SelectorEventLoop
    server = uvicorn.Server(config)
    server.run()


if __name__ == "__main__":
    main()
