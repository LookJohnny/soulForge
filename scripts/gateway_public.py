"""HTTP-only public edge: expose inference, never development WS or controls."""

import argparse
import os

from aiohttp import web, ClientSession, ClientTimeout, ClientError
from studio.gateway_proxy import local_url


def build_app(gateway_url: str) -> web.Application:
    gateway_url = local_url(gateway_url)
    app = web.Application(client_max_size=256 * 1024)

    async def health(_request):
        return web.json_response({"status": "ok", "service": "gateway-public-relay"})

    async def inference(request):
        headers = {"Content-Type": "application/json"}
        for key in ("Authorization", "X-Conversation-Id"):
            if request.headers.get(key):
                headers[key] = request.headers[key]
        response = None
        try:
            async with ClientSession(trust_env=False) as client:
                async with client.post(gateway_url + "/v1/chat/completions", data=await request.read(),
                                       headers=headers, timeout=ClientTimeout(total=90),
                                       allow_redirects=False) as upstream:
                    response = web.StreamResponse(status=upstream.status, headers={
                        "Content-Type": upstream.headers.get("Content-Type", "application/json"),
                        "Cache-Control": "no-store",
                    })
                    if upstream.headers.get("WWW-Authenticate"):
                        response.headers["WWW-Authenticate"] = upstream.headers["WWW-Authenticate"]
                    await response.prepare(request)
                    async for chunk in upstream.content.iter_any():
                        await response.write(chunk)
                    await response.write_eof()
                    return response
        except (OSError, TimeoutError, ClientError):
            if response is not None and response.prepared:
                response.force_close()
                return response
            return web.json_response({"error": "Gateway is unavailable"}, status=502)

    app.router.add_get("/health", health)
    app.router.add_post("/v1/chat/completions", inference)
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8091)
    args = parser.parse_args()
    if not os.environ.get("GATEWAY_API_TOKEN", "").strip():
        raise SystemExit("GATEWAY_API_TOKEN is required before exposing the inference relay")
    web.run_app(build_app(os.environ.get("GATEWAY_API_URL", "http://127.0.0.1:8081")),
                host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
