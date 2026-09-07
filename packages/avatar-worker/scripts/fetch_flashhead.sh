#!/usr/bin/env bash
set -euo pipefail

# Source only. Sparse checkout avoids upstream demo videos/images, and LFS
# smudging is disabled. This script never downloads Hugging Face model weights.
worker_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
revision="$(cat "$worker_root/flashhead-revision.txt")"
target="${1:?Usage: bash scripts/fetch_flashhead.sh /absolute/source/directory}"
if [[ -e "$target" ]]; then
  printf '%s\n' 'Refusing to overwrite an existing source directory.' >&2
  exit 1
fi
git init "$target"
git -C "$target" remote add origin https://github.com/Soul-AILab/SoulX-FlashHead.git
git -C "$target" fetch --depth=1 --filter=blob:none origin "$revision"
git -C "$target" sparse-checkout init --cone
git -C "$target" sparse-checkout set flash_head
GIT_LFS_SKIP_SMUDGE=1 git -C "$target" checkout --detach FETCH_HEAD
[[ "$(git -C "$target" rev-parse HEAD)" == "$revision" ]]
