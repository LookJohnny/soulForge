"""把任何前端接成一个"身体"——Protocol 0.2 最小客户端示例。

先起大脑（生活运行时 + 协议服务）:
    uv run python -m engine.server.server --port 8765 --mock-llm --time-scale 2

再跑本脚本（需要 soulforge-harness[ws]，仓库内 uv 环境已带 websockets）:
    uv run python examples/body_websocket.py

它声明自己承载 luna，之后打印大脑下发的每个动作（走位/姿态/台词/注视），
并按协议回执 accepted → done——这正是网页 VRM、机器人、语音管道接入的方式。
"""

import asyncio
import json

import websockets

BRAIN = "ws://127.0.0.1:8765/body"


async def main() -> None:
    async with websockets.connect(BRAIN) as ws:
        await ws.send(
            json.dumps(
                {
                    "type": "hello",
                    "protocol": "0.2",
                    "body_id": "example-body",
                    "backend": "web",
                    "agent_ids": ["luna"],
                    "manifest": {
                        "body_id": "example-body",
                        "backend": "web",
                        "supported_steps": [],
                        "supported_templates": [],
                        "features": {
                            "speech": True,
                            "gaze": True,
                            "nav": False,
                            "props": False,
                        },
                        "step_substitutions": {},
                    },
                }
            )
        )
        async for raw in ws:
            msg = json.loads(raw)
            if msg["type"] == "welcome":
                print(f"✦ 已注册为 {msg['body_id']}，承载 {msg['accepted_agents']}")
            elif msg["type"] == "action":
                line = f" 「{msg['dialogue']}」" if msg.get("dialogue") else ""
                print(f"[{msg['agent_id']}] {msg['name']}{line}")
                for status in ("accepted", "done"):
                    await ws.send(
                        json.dumps(
                            {
                                "type": "observation",
                                "command_id": msg["command_id"],
                                "agent_id": msg["agent_id"],
                                "status": status,
                                "body_id": "example-body",
                            }
                        )
                    )
            elif msg["type"] == "plan_state":
                print(f"◈ {msg['agent_id']} {msg['clock']} 目标：{msg['hour_goal']}")


if __name__ == "__main__":
    asyncio.run(main())
