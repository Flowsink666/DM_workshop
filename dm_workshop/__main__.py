"""DM Workshop 命令行入口。"""

from __future__ import annotations

import argparse


def main() -> None:
    """解析运行模式，并按需加载 MCP 或 Web 依赖。"""
    parser = argparse.ArgumentParser(prog="dm-workshop")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("mcp", help="启动 stdio MCP 服务")
    web = sub.add_parser("web", help="启动本机 Web 管理台")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.command == "mcp":
        from dm_workshop.mcp_server import run
        run()
    else:
        import uvicorn
        uvicorn.run("dm_workshop.web:app", host=args.host, port=args.port,
                    reload=False)


if __name__ == "__main__":
    main()
