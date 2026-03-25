#!/usr/bin/env python3
"""
SoulForge WebSocket 设备模拟器
模拟 ESP32 小智设备连接 Gateway，测试握手、文本聊天、触摸事件。

Usage:
    python hardware/scripts/test_ws_device.py
    python hardware/scripts/test_ws_device.py --gateway ws://192.168.1.100:8080/ws
"""

import argparse
import asyncio
import json
import time
import sys

import websockets

# ─── Config ────────────────────────────────────
DEFAULT_GATEWAY = "ws://127.0.0.1:8080/ws"
DEVICE_ID = "test-device-001"
TIMEOUT = 15  # seconds per test


# ─── Helpers ───────────────────────────────────
class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    NC = "\033[0m"


def ok(msg): print(f"  {Colors.GREEN}[PASS]{Colors.NC} {msg}")
def fail(msg): print(f"  {Colors.RED}[FAIL]{Colors.NC} {msg}")
def info(msg): print(f"  {Colors.CYAN}[INFO]{Colors.NC} {msg}")
def header(msg): print(f"\n{Colors.CYAN}── {msg} ──{Colors.NC}")


results = {"pass": 0, "fail": 0}

def record(passed, msg):
    if passed:
        ok(msg)
        results["pass"] += 1
    else:
        fail(msg)
        results["fail"] += 1


# ─── Test: Xiaozhi Protocol Handshake ──────────
async def test_xiaozhi_handshake(gateway_url):
    header("Test 1: 小智协议握手")

    try:
        async with websockets.connect(gateway_url, open_timeout=5) as ws:
            # Send hello
            hello = {"type": "hello", "device_id": DEVICE_ID}
            await ws.send(json.dumps(hello))
            info(f"Sent: {json.dumps(hello)}")

            # Wait for response
            resp_raw = await asyncio.wait_for(ws.recv(), timeout=TIMEOUT)
            resp = json.loads(resp_raw)
            info(f"Recv: {json.dumps(resp, ensure_ascii=False)[:100]}")

            record(resp.get("type") == "hello", f"握手响应 type=hello")
            record("session_id" in resp or "transport" in resp, f"包含 session_id 或 transport")

            return True
    except Exception as e:
        fail(f"连接失败: {e}")
        results["fail"] += 1
        return False


# ─── Test: GenericWS Text Chat ─────────────────
async def test_text_chat(gateway_url):
    header("Test 2: 文本对话 (GenericWS)")

    try:
        async with websockets.connect(gateway_url, open_timeout=5) as ws:
            # Handshake with generic protocol
            hello = {"action": "hello", "device_id": f"{DEVICE_ID}-generic"}
            await ws.send(json.dumps(hello))
            resp_raw = await asyncio.wait_for(ws.recv(), timeout=TIMEOUT)
            resp = json.loads(resp_raw)
            record(resp.get("action") == "hello" and resp.get("status") == "ok",
                   "GenericWS 握手成功")

            # Send chat message
            start = time.time()
            chat = {"action": "chat", "text": "你好呀"}
            await ws.send(json.dumps(chat))
            info(f"Sent: {json.dumps(chat, ensure_ascii=False)}")

            # Collect responses until "stop"
            text_parts = []
            got_start = False
            got_stop = False

            while True:
                try:
                    msg_raw = await asyncio.wait_for(ws.recv(), timeout=TIMEOUT)
                except asyncio.TimeoutError:
                    info("等待超时，可能角色未绑定到设备")
                    break

                if isinstance(msg_raw, bytes):
                    info(f"收到音频帧: {len(msg_raw)} bytes")
                    continue

                msg = json.loads(msg_raw)
                state = msg.get("state", "")

                if state == "start":
                    got_start = True
                elif state == "sentence":
                    text = msg.get("text", "")
                    if text:
                        text_parts.append(text)
                elif state == "stop":
                    got_stop = True
                    break

            latency = int((time.time() - start) * 1000)
            full_text = "".join(text_parts)

            if full_text:
                record(True, f"收到回复: \"{full_text[:60]}\" ({latency}ms)")
            else:
                record(False, f"未收到文本回复 (设备可能没有绑定角色)")
                info("提示: 在管理后台的设备页面绑定角色到此设备")

            return True
    except Exception as e:
        fail(f"文本对话失败: {e}")
        results["fail"] += 1
        return False


# ─── Test: Touch Event ─────────────────────────
async def test_touch_event(gateway_url):
    header("Test 3: 触摸事件")

    try:
        async with websockets.connect(gateway_url, open_timeout=5) as ws:
            # Handshake
            hello = {"type": "hello", "device_id": f"{DEVICE_ID}-touch"}
            await ws.send(json.dumps(hello))
            await asyncio.wait_for(ws.recv(), timeout=5)

            # Send touch events
            touches = [
                {"type": "touch", "gesture": "pat", "zone": "head", "pressure": 0.6, "duration_ms": 500},
                {"type": "touch", "gesture": "hug", "zone": "belly", "pressure": 0.8, "duration_ms": 3000},
                {"type": "touch", "gesture": "poke", "zone": "cheek", "pressure": 0.3, "duration_ms": 200},
            ]

            for t in touches:
                await ws.send(json.dumps(t))
                info(f"Sent touch: {t['gesture']}@{t['zone']} (pressure={t['pressure']})")

                # Touch may trigger an immediate response for strong gestures
                try:
                    resp_raw = await asyncio.wait_for(ws.recv(), timeout=3)
                    if isinstance(resp_raw, str):
                        resp = json.loads(resp_raw)
                        text = resp.get("text", "")
                        if text:
                            info(f"  触摸回应: \"{text[:40]}\"")
                except asyncio.TimeoutError:
                    pass  # Not all touches trigger immediate responses

                await asyncio.sleep(0.5)

            record(True, f"发送了 {len(touches)} 个触摸事件 (查看 Gateway 日志确认处理)")
            return True
    except Exception as e:
        fail(f"触摸测试失败: {e}")
        results["fail"] += 1
        return False


# ─── Test: Heartbeat ───────────────────────────
async def test_heartbeat(gateway_url):
    header("Test 4: 心跳保活")

    try:
        async with websockets.connect(gateway_url, open_timeout=5) as ws:
            hello = {"action": "hello", "device_id": f"{DEVICE_ID}-ping"}
            await ws.send(json.dumps(hello))
            await asyncio.wait_for(ws.recv(), timeout=5)

            # Send pings
            for i in range(3):
                await ws.send(json.dumps({"action": "ping"}))
                await asyncio.sleep(0.5)

            record(True, "发送 3 次心跳，连接保持正常")
            return True
    except Exception as e:
        fail(f"心跳失败: {e}")
        results["fail"] += 1
        return False


# ─── Test: Reconnect ──────────────────────────
async def test_reconnect(gateway_url):
    header("Test 5: 断线重连")

    try:
        # First connection
        ws1 = await websockets.connect(gateway_url, open_timeout=5)
        hello = {"type": "hello", "device_id": f"{DEVICE_ID}-reconnect"}
        await ws1.send(json.dumps(hello))
        await asyncio.wait_for(ws1.recv(), timeout=5)
        info("第一次连接成功")

        # Disconnect
        await ws1.close()
        info("主动断开")
        await asyncio.sleep(1)

        # Reconnect
        ws2 = await websockets.connect(gateway_url, open_timeout=5)
        await ws2.send(json.dumps(hello))
        resp = await asyncio.wait_for(ws2.recv(), timeout=5)
        await ws2.close()

        record(True, "断线后重新连接成功")
        return True
    except Exception as e:
        fail(f"重连失败: {e}")
        results["fail"] += 1
        return False


# ─── Main ──────────────────────────────────────
async def main(gateway_url):
    print(f"\n{'='*50}")
    print(f"  SoulForge WebSocket 设备模拟测试")
    print(f"  Gateway: {gateway_url}")
    print(f"  Device:  {DEVICE_ID}")
    print(f"{'='*50}")

    await test_xiaozhi_handshake(gateway_url)
    await test_text_chat(gateway_url)
    await test_touch_event(gateway_url)
    await test_heartbeat(gateway_url)
    await test_reconnect(gateway_url)

    # Summary
    print(f"\n{'='*50}")
    total = results['pass'] + results['fail']
    print(f"  {Colors.GREEN}PASS: {results['pass']}{Colors.NC}  "
          f"{Colors.RED}FAIL: {results['fail']}{Colors.NC}  "
          f"TOTAL: {total}")
    print(f"{'='*50}\n")

    return results['fail'] == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SoulForge WebSocket 设备模拟器")
    parser.add_argument("--gateway", default=DEFAULT_GATEWAY, help="Gateway WebSocket URL")
    args = parser.parse_args()

    success = asyncio.run(main(args.gateway))
    sys.exit(0 if success else 1)
