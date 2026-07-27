"""向运行中的 PetNest 本地事件服务发送一个 JSON 事件。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import socket
import sys
from typing import Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def parse_arguments(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    """解析不含敏感数据持久化的命令行参数。"""
    parser = argparse.ArgumentParser(description="向 PetNest 发送本地事件")
    parser.add_argument("event", help="事件名，例如 agent.working")
    parser.add_argument("--source", default="cli", help="事件来源（默认：cli）")
    parser.add_argument("--port", type=int, default=18486, help="本地服务端口")
    parser.add_argument("--payload", help="可选 JSON 对象 payload")
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> int:
    """发送一行 JSON；连接失败时返回非零状态。"""
    args = parse_arguments(arguments)
    payload: dict[str, object] = {}
    if args.payload:
        try:
            parsed = json.loads(args.payload)
        except json.JSONDecodeError as error:
            print(f"payload 不是有效 JSON：{error}", file=sys.stderr)
            return 2
        if not isinstance(parsed, dict):
            print("payload 必须是 JSON 对象", file=sys.stderr)
            return 2
        payload = parsed
    message: dict[str, object] = {"event": args.event, "source": args.source}
    if payload:
        message["payload"] = payload
    try:
        with socket.create_connection(("127.0.0.1", args.port), timeout=2) as client:
            client.sendall(json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n")
    except OSError as error:
        print(f"无法连接 PetNest 本地事件服务：{error}", file=sys.stderr)
        return 1
    print(f"已发送事件：{args.event}（来源：{args.source}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
