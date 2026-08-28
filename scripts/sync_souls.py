#!/usr/bin/env python3
"""configs/characters.json → ai-core character table, so the voice brain (gateway/ai-core)
and the life brain (engine) describe the same people. The first persona is bound to the
web body device (web_vrm-live). Needs SOUL_BRAND_ID + SERVICE_TOKEN in .env.

    uv run python scripts/sync_souls.py            # all
    uv run python scripts/sync_souls.py luna       # one
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from studio import soul_io  # noqa: E402

if __name__ == "__main__":
    if len(sys.argv) > 1:
        out = soul_io.sync_persona(sys.argv[1], bind_device="web_vrm-live")
    else:
        out = soul_io.sync_all()
    print(json.dumps(out, ensure_ascii=False, indent=2))
