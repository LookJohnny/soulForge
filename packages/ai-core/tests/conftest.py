import sys
from pathlib import Path

# Add ai-core src to path for test discovery
src_dir = str(Path(__file__).resolve().parent.parent / "src")
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)
