"""在一个进程中运行 stdio MCP 与本地 Web 服务。"""

from __future__ import annotations

import sys
import threading
import time

import uvicorn


def run(host: str = "127.0.0.1", port: int = 8765) -> None:
    """后台启动 Web，确认监听成功后在主线程运行 MCP。"""
    config = uvicorn.Config(
        "dm_workshop.web:app", host=host, port=int(port),
        log_level="warning", access_log=False,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(
        target=server.run, name="dm-workshop-web", daemon=True,
    )
    thread.start()
    deadline = time.monotonic() + 5
    while thread.is_alive() and not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    if not server.started:
        server.should_exit = True
        thread.join(timeout=1)
        print(
            f"无法启动 Web 服务 http://{host}:{port}，请检查端口是否被占用。",
            file=sys.stderr,
        )
        raise SystemExit(1)

    from dm_workshop.mcp_server import run as run_mcp
    try:
        run_mcp()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
