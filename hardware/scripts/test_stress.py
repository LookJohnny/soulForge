#!/usr/bin/env python3
"""
SoulForge 压力和稳定性测试
测试连续对话、并发设备、触摸连击等场景。

Usage:
    python hardware/scripts/test_stress.py
    python hardware/scripts/test_stress.py --rounds 50 --concurrent 3
"""

import argparse
import asyncio
import json
import sys
import time
import statistics

import websockets

DEFAULT_GATEWAY = "ws://127.0.0.1:8080/ws"

class Colors:
    GREEN = "\033[92m"; RED = "\033[91m"; CYAN = "\033[96m"; YELLOW = "\033[93m"; NC = "\033[0m"

def ok(msg): print(f"  {Colors.GREEN}[OK]{Colors.NC} {msg}")
def fail(msg): print(f"  {Colors.RED}[FAIL]{Colors.NC} {msg}")
def info(msg): print(f"  {Colors.CYAN}[..]{Colors.NC} {msg}")


# ─── Single conversation round ─────────────────
async def single_chat(gateway_url, device_id, text, timeout=20):
    """Send one text message, return (success, latency_ms, response_text)."""
    try:
        async with websockets.connect(gateway_url, open_timeout=5) as ws:
            # Handshake
            await ws.send(json.dumps({"action": "hello", "device_id": device_id}))
            await asyncio.wait_for(ws.recv(), timeout=5)

            # Chat
            start = time.time()
            await ws.send(json.dumps({"action": "chat", "text": text}))

            text_parts = []
            while True:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=timeout)
                except asyncio.TimeoutError:
                    break
                if isinstance(msg, bytes):
                    continue
                data = json.loads(msg)
                if data.get("state") == "sentence":
                    text_parts.append(data.get("text", ""))
                elif data.get("state") == "stop":
                    break

            latency = int((time.time() - start) * 1000)
            reply = "".join(text_parts)
            return (bool(reply), latency, reply[:50])
    except Exception as e:
        return (False, 0, str(e)[:50])


# ─── Test 1: Continuous conversation ───────────
async def test_continuous(gateway_url, rounds):
    print(f"\n{'='*55}")
    print(f"  连续对话测试 ({rounds} 轮)")
    print(f"{'='*55}\n")

    prompts = [
        "你好", "今天天气怎么样", "给我讲个笑话", "你喜欢什么",
        "我有点无聊", "陪我聊聊天", "你觉得呢", "真的吗",
        "太好了", "晚安",
    ]

    success = 0
    latencies = []

    for i in range(rounds):
        text = prompts[i % len(prompts)]
        ok_flag, latency, reply = await single_chat(
            gateway_url, f"stress-continuous-{i}", text
        )

        status = f"{Colors.GREEN}OK{Colors.NC}" if ok_flag else f"{Colors.RED}FAIL{Colors.NC}"
        print(f"  [{i+1:3d}/{rounds}] {status} {latency:5d}ms  \"{text}\" → \"{reply}\"")

        if ok_flag:
            success += 1
            latencies.append(latency)

        # Small delay between rounds
        await asyncio.sleep(0.3)

    # Report
    rate = success / rounds * 100
    print(f"\n  成功率: {success}/{rounds} ({rate:.0f}%)")
    if latencies:
        avg = statistics.mean(latencies)
        p50 = statistics.median(latencies)
        p95 = latencies[int(len(latencies) * 0.95)] if len(latencies) > 5 else max(latencies)
        print(f"  延迟: avg={avg:.0f}ms  p50={p50:.0f}ms  p95={p95:.0f}ms")

    if rate >= 95:
        ok(f"成功率 {rate:.0f}% >= 95%")
    elif rate >= 80:
        print(f"  {Colors.YELLOW}[WARN]{Colors.NC} 成功率 {rate:.0f}% (80-95%)")
    else:
        fail(f"成功率 {rate:.0f}% < 80%")

    return rate >= 80


# ─── Test 2: Concurrent devices ────────────────
async def test_concurrent(gateway_url, num_devices):
    print(f"\n{'='*55}")
    print(f"  并发设备测试 ({num_devices} 个设备同时对话)")
    print(f"{'='*55}\n")

    async def device_task(idx):
        device_id = f"concurrent-device-{idx}"
        ok_flag, latency, reply = await single_chat(gateway_url, device_id, f"设备{idx}号说你好")
        return (idx, ok_flag, latency, reply)

    start = time.time()
    tasks = [device_task(i) for i in range(num_devices)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    total_time = int((time.time() - start) * 1000)

    success = 0
    for r in results:
        if isinstance(r, Exception):
            fail(f"设备异常: {r}")
        else:
            idx, ok_flag, latency, reply = r
            status = f"{Colors.GREEN}OK{Colors.NC}" if ok_flag else f"{Colors.RED}FAIL{Colors.NC}"
            print(f"  设备{idx}: {status} {latency}ms \"{reply}\"")
            if ok_flag:
                success += 1

    print(f"\n  {success}/{num_devices} 成功 (总耗时: {total_time}ms)")
    if success == num_devices:
        ok("全部设备对话成功")
    else:
        fail(f"{num_devices - success} 个设备失败")

    return success == num_devices


# ─── Test 3: Rapid touch ──────────────────────
async def test_rapid_touch(gateway_url, count=50):
    print(f"\n{'='*55}")
    print(f"  快速触摸连击测试 ({count} 次)")
    print(f"{'='*55}\n")

    gestures = ["pat", "stroke", "poke", "hug", "squeeze", "shake", "hold"]
    zones = ["head", "back", "belly", "cheek", "hand_left", "hand_right"]

    try:
        async with websockets.connect(gateway_url, open_timeout=5) as ws:
            await ws.send(json.dumps({"type": "hello", "device_id": "touch-stress"}))
            await asyncio.wait_for(ws.recv(), timeout=5)

            start = time.time()
            for i in range(count):
                gesture = gestures[i % len(gestures)]
                zone = zones[i % len(zones)]
                touch = {
                    "type": "touch",
                    "gesture": gesture,
                    "zone": zone,
                    "pressure": 0.3 + (i % 7) * 0.1,
                    "duration_ms": 200 + (i % 5) * 100,
                }
                await ws.send(json.dumps(touch))

                # Drain any immediate responses without blocking
                try:
                    await asyncio.wait_for(ws.recv(), timeout=0.1)
                except asyncio.TimeoutError:
                    pass

            elapsed = int((time.time() - start) * 1000)
            rate = count / (elapsed / 1000)

            ok(f"发送 {count} 次触摸，耗时 {elapsed}ms ({rate:.0f} 次/秒)")
            ok("连接保持正常，未崩溃")

            # Verify connection still alive
            await ws.send(json.dumps({"action": "ping"}))
            ok("触摸后连接仍然活跃")

            return True
    except Exception as e:
        fail(f"触摸压力测试失败: {e}")
        return False


# ─── Main ──────────────────────────────────────
async def main(args):
    print(f"\n{'='*55}")
    print(f"  SoulForge 压力测试")
    print(f"  Gateway:    {args.gateway}")
    print(f"  对话轮次:   {args.rounds}")
    print(f"  并发设备:   {args.concurrent}")
    print(f"{'='*55}")

    results = []

    results.append(await test_continuous(args.gateway, args.rounds))
    results.append(await test_concurrent(args.gateway, args.concurrent))
    results.append(await test_rapid_touch(args.gateway))

    print(f"\n{'='*55}")
    passed = sum(results)
    total = len(results)
    print(f"  总结: {passed}/{total} 测试通过")
    print(f"{'='*55}\n")

    return all(results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SoulForge 压力测试")
    parser.add_argument("--gateway", default=DEFAULT_GATEWAY)
    parser.add_argument("--rounds", type=int, default=10, help="连续对话轮次 (默认10)")
    parser.add_argument("--concurrent", type=int, default=3, help="并发设备数 (默认3)")
    args = parser.parse_args()

    success = asyncio.run(main(args))
    sys.exit(0 if success else 1)
