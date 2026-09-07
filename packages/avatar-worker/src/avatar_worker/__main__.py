import os

import uvicorn


def main():
    uvicorn.run("avatar_worker.app:create_app", factory=True,
        host=os.environ.get("AVATAR_WORKER_HOST", "127.0.0.1"),
        port=int(os.environ.get("AVATAR_WORKER_PORT", "8092")), workers=1,
        access_log=False)


if __name__ == "__main__":
    main()
