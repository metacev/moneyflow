"""启动入口：启动本地服务并自动打开浏览器（Windows / macOS / Linux 通用）。"""
from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def find_free_port(start: int = 8765) -> int:
    for port in range(start, start + 60):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start


def main() -> None:
    parser = argparse.ArgumentParser(description="QuantFactorLab 因子策略实验室")
    parser.add_argument("--port", type=int, default=0, help="端口，0 表示自动选择")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

    port = args.port or find_free_port()
    url = f"http://{args.host}:{port}"

    import uvicorn

    from app.server import app as asgi_app

    banner = f"""
============================================================
  QuantFactorLab · 因子策略实验室  v0.1.0
  地址: {url}
  关闭本窗口即可停止服务（或按 Ctrl+C）
============================================================
"""
    print(banner)

    if not args.no_browser:
        threading.Thread(target=lambda: (time.sleep(1.2), webbrowser.open(url)), daemon=True).start()

    uvicorn.run(asgi_app, host=args.host, port=port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
