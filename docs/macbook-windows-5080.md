# MacBook + Windows RTX 5080：迁移与自建视频部署

本指南按当前仓库脚本与官方 WSL 文档核对，尚未在这台 Windows 5080 上构建镜像或运行模型。5080 的 16GB 显存能否容纳当前 Lite 的完整推理峰值、首帧时间和持续帧率，都需要实测；这里没有“5080 已通过”的结论。先运行 **`MODEL_TYPE=lite`**。worker 模板与 Dockerfile 默认仍是 `pro`，不能漏掉覆盖。

分工如下：

| 机器 | 运行内容 | 对外连接 |
| --- | --- | --- |
| MacBook | PostgreSQL、Redis、ai-core、Character Runtime、Gateway、Studio、media-body | 浏览器访问本机 Studio；通过 SSH 隧道调用 worker |
| Windows 5080 | NVIDIA Windows 驱动、WSL2、Docker Desktop、单卡 FlashHead Lite worker | 仅 SSH 接受 MacBook 连接；worker 端口只发布到 Windows loopback |

Windows worker 只接收大脑已生成的音频，不运行第二套角色、大脑或记忆数据库。自建视频页是 `http://127.0.0.1:8899/joi?body=selfhost`。不要把 Tavus、VRM 或 Unity 的启动当成这条路径的验收。

## 1. 先保存旧 Mac 的数据，再迁移代码

GitHub 保存源码、锁文件、配置模板和可发布资源，**不保存以下私人运行状态**：

| 内容 | 迁移方式 |
| --- | --- |
| 根 `.env`、其他本地环境配置 | 私下转移；保持 `MASTER_SECRET`，更新机器地址；`SERVICE_TOKEN` 必须换新 |
| PostgreSQL 的用户、角色 UUID、五层记忆、事件与关系 | 完整 `pg_dump` / `pg_restore`，不是重新 seed |
| `outputs/runtime-memory/` 下的 SQLite outbox | 与数据库同一次停写备份；自定义 `SOULFORGE_MEMORY_OUTBOX` 也要备份 |
| `configs/characters.json` 的当前权威角色定义 | 提交后的版本随 GitHub；额外保存私人快照，核对是否有未发布修改 |
| MinIO 中的声音/头像/文档等对象、其他自建 RAG 数据 | 单独备份实际使用的数据；数据库中的 URL 不包含对象本身 |
| 本地 Unity 模型/动画、Mixamo 原始素材、VRM、`assets/souls/luna.soul` 等 `.soul` 文件 | 按授权私下迁移或重新取得；不能假设 clone 后完整外观已经存在 |
| FlashHead / wav2vec2 权重、授权参考头像 | 放在 Windows 私人模型目录，按固定版本重新下载或私下复制 |

自建真人 worker 不依赖 Unity 模型、Mixamo 动画或 VRM。不要为迁移而将未授权素材、`.env`、SQL dump、SQLite、真实对话或完整 `outputs/` 上传 GitHub。

**保持身份：**保留旧安装实际的 `SOULFORGE_BRAND_ID`、`SOULFORGE_USER_ID`（原先留空则继续沿用同品牌的派生规则）和数据库角色 UUID。换电脑不应通过换品牌/用户来“重新初始化”；outbox 会检查其所属品牌与用户。

**凭据：**此次发布审计发现旧 `SERVICE_TOKEN` 曾出现在已跟踪脚本中，因此不要在新电脑继续使用旧值。换成新随机值，并让 ai-core、Runtime、Gateway 使用同一份根 `.env`。这不要求更换 `MASTER_SECRET`；后者用于已有加密数据，随意更换可能让旧数据无法解密。Gateway、media-body、GPU worker 的 token 各自独立。

### 1.1 停止应用写入

先在旧 Mac 关闭视频会话，在运行 `scripts/live-up.sh` 的终端按 Ctrl-C，并停止单独启动的 media-body、管理后台及其他数据库写入程序。此时暂时保留 PostgreSQL 运行，以便导出。不要同时在两台 Mac 启动同一用户的 Runtime。

下列数据库命令针对本仓库根 `docker-compose.yml` 的 PostgreSQL 16。若旧 `.env` 的 `DATABASE_URL` 指向其他数据库，改用那个实际源的备份方式；不要误备份一个空的本地容器。不要把连接串打印到共享终端或粘贴到文档。

在旧仓库根目录执行，将备份放在仓库之外：

```bash
umask 077
export SF_TRANSFER="$HOME/SoulForge-transfer/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$SF_TRANSFER"
git rev-parse HEAD > "$SF_TRANSFER/source-commit.txt"
cp .env "$SF_TRANSFER/root.env"
cp configs/characters.json "$SF_TRANSFER/characters.json"
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner --no-acl' > "$SF_TRANSFER/soulforge.dump"
test -s "$SF_TRANSFER/soulforge.dump"
```

应在要迁移的代码已提交、推送之后记录 commit；未提交代码不会出现在 `source-commit.txt` 指向的快照中。`scripts/backup/restore.sh` 的旧 SQL 行筛选流程不是完整 COPY 数据恢复，本次迁移不要使用它。

使用 SQLite backup API 保存队列，避免漏掉 WAL 中已提交的待写记忆。以下脚本不输出记忆内容或 token：

```bash
.venv/bin/python - <<'PY'
import json, os, sqlite3
from pathlib import Path
from dotenv import dotenv_values
root = Path.cwd()
backup = Path(os.environ["SF_TRANSFER"])
env = dotenv_values(root / ".env", interpolate=False)
sources = {p.resolve() for p in (root / "outputs/runtime-memory").rglob("*.sqlite3")}
custom = env.get("SOULFORGE_MEMORY_OUTBOX")
if custom:
    path = Path(custom).expanduser()
    path = path if path.is_absolute() else root / path
    if not path.is_file():
        raise SystemExit("Configured outbox is missing; resolve before migrating.")
    sources.add(path.resolve())
manifest = []
for index, source in enumerate(sorted(sources)):
    target = backup / "outbox" / f"{index}.sqlite3"
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as src:
        with sqlite3.connect(target) as dst:
            src.backup(dst)
        count = src.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]
    relative = str(source.relative_to(root)) if source.is_relative_to(root) else "outputs/runtime-memory/migrated-custom.sqlite3"
    manifest.append({"file": str(target.relative_to(backup)), "restore_path": relative,
                     "pending_rows": count, "is_configured_custom": bool(custom and source == path.resolve())})
(backup / "outbox-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print("Outbox snapshots:", len(manifest))
PY
(cd "$SF_TRANSFER" && shasum -a 256 soulforge.dump > soulforge.dump.sha256)
```

默认队列尚未创建时 manifest 可以为空；若已经存在待写记忆，应能看到相应快照。自定义队列在仓库外时，恢复到文中约定的新相对路径，并对应修改新 `.env`。

MinIO 若已有私人对象，在应用停止写入后可冷备份其数据目录：

```bash
docker compose stop minio
docker run --rm --volumes-from soulforge-minio:ro busybox:1.37.0 tar -C /data -cf - . > "$SF_TRANSFER/minio-data.tar"
```

仅在确实使用了 MinIO 时执行；此命令会拉取小型 BusyBox 辅助镜像，只读挂载已停止的容器数据卷，避免依赖 MinIO 镜像里是否存在 tar。若旧安装还使用 Milvus，需先停止所有相关写入，并将其 etcd、MinIO、Milvus 数据按一致快照迁移；上面的 PostgreSQL 导出和单独 MinIO 备份不等于 Milvus 完整备份。Redis 缓存可重建，但如果其他功能依赖它的会话/队列状态，要另做停机数据卷备份，不能当作已包含。

通过加密移动盘、受保护的文件传输或其他私人通道，将整个 `SF_TRANSFER` 目录及所需授权素材交给新 MacBook。保留旧机器与备份，直到新机器核验完成。

## 2. 在 MacBook 重建同一安装

准备 Git、Docker Desktop（Apple Silicon 版）、uv、Node.js 22.12+ 与 pnpm 10.11.0；启动 Docker Desktop。Python 环境与 `node_modules` 在新机器重新建立，不复制旧 `.venv`。

语音网关依赖原生 Opus 库与 ffmpeg，`uv sync` 不会安装系统库。在已配置 Homebrew 的新 MacBook 上执行：

```bash
brew install opus ffmpeg
export DYLD_FALLBACK_LIBRARY_PATH="$(brew --prefix)/lib${DYLD_FALLBACK_LIBRARY_PATH:+:$DYLD_FALLBACK_LIBRARY_PATH}"
```

在启动服务或测试的新终端里也设置上述变量，或按自己的 shell 配置保存它。仅 `pip/uv` 安装 `opuslib` 仍可能报 `Could not find Opus library`；本指南使用的 uv Python 3.12 新环境已实际遇到并核实该依赖。

在新 MacBook 选择私人备份目录，并 clone 已推送的代码：

```bash
export SF_TRANSFER="$HOME/SoulForge-transfer/替换为实际备份目录"
mkdir -p "$HOME/Projects"
cd "$HOME/Projects"
git clone git@github.com:LookJohnny/soulForge.git
cd soulForge
git checkout --detach "$(cat "$SF_TRANSFER/source-commit.txt")"
cp "$SF_TRANSFER/root.env" .env
chmod 600 .env
uv sync --frozen --all-packages --python 3.12
(cd "$SF_TRANSFER" && shasum -a 256 -c soulforge.dump.sha256)
```

SSH clone 需要新 Mac 已有 GitHub 访问权限；也可使用仓库 HTTPS 地址。固定 commit 便于核验迁移，之后继续开发时再切到需要的分支。对照私人 `characters.json` 快照检查当前权威定义；如果确实有未发布修改，确认后再恢复这些定义。

编辑 `.env`：

- 核对新电脑上的 `DATABASE_URL`、`REDIS_URL`；默认 Compose 数据库账号见根 `docker-compose.yml`，不是把旧云数据库地址原样当作本机地址。
- 保持品牌/用户身份与 `MASTER_SECRET`；替换旧 `SERVICE_TOKEN`，保持相关服务一致。同步需要迁移的应用专属 `.env`，不要让旧 `packages/database/.env` 指向另一套数据库。
- 将旧电脑的绝对文件路径改成新机器路径。
- 设置 `LIVE_TUNNEL_PROVIDER=none`、`TAVUS_SYNC_ON_START=false`，避免迁移验收期间自动同步外部 Tavus 配置。
- GPU 就绪前可先设 `SELFHOST_MEDIA_ENABLED=false`，让大脑、记忆与 Studio 独立验证。

### 2.1 恢复数据库和 outbox

下面恢复命令只用于**全新、没有业务表数据**的目标库。不要在已有安装上使用清库/覆盖选项；先确认新电脑没有需要保留的数据库。根 Compose 会发布 PostgreSQL/Redis 端口，应放在可信本地网络，不能当作公网部署配置。

```bash
docker compose up -d postgres redis
docker compose exec -T postgres pg_isready -U soulforge -d soulforge
docker compose exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-acl --exit-on-error' < "$SF_TRANSFER/soulforge.dump"
```

等待 `pg_isready` 成功后再恢复；dump 已包含 schema 和迁移历史，**先恢复再执行可能新增的迁移**。不要运行 `db:seed` 来替代原记忆。

在根目录安全读取 `.env`，用同一连接安装 Node 依赖并检查迁移：

```bash
.venv/bin/python - <<'PY'
import os, subprocess
from dotenv import dotenv_values
env = dict(os.environ)
env.update({k: v for k, v in dotenv_values(".env", interpolate=False).items() if v is not None})
commands = [
    ["pnpm", "install", "--frozen-lockfile"],
    ["pnpm", "--dir", "packages/database", "exec", "prisma", "migrate", "deploy"],
    ["pnpm", "--dir", "packages/database", "exec", "prisma", "generate"],
]
for command in commands:
    subprocess.run(command, env=env, check=True)
PY
```

恢复 outbox；目标文件若已存在，此脚本拒绝覆盖：

```bash
.venv/bin/python - <<'PY'
import json, os, shutil, sqlite3
from pathlib import Path
root = Path.cwd().resolve()
backup = Path(os.environ["SF_TRANSFER"])
for row in json.loads((backup / "outbox-manifest.json").read_text()):
    target = (root / row["restore_path"]).resolve()
    if not target.is_relative_to(root) or target.exists():
        raise SystemExit("Restore target is unsafe or exists; inspect before continuing.")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup / row["file"], target)
    target.chmod(0o600)
    with sqlite3.connect(target.as_uri() + "?mode=ro", uri=True) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == row["pending_rows"]
print("Outbox snapshots restored and checked.")
PY
```

有 `is_configured_custom=true` 时，把新根 `.env` 的 `SOULFORGE_MEMORY_OUTBOX` 改为那一项 `restore_path`。SQLite 队列中有待写记录是正常状态，启动后应继续向恢复后的 PostgreSQL 投递，不能为了清除告警而删除队列。

若备份了 MinIO，仅向新建的空数据卷恢复，再启动服务：

```bash
docker compose create minio
docker run --rm -i --volumes-from soulforge-minio busybox:1.37.0 tar -C /data -xf - < "$SF_TRANSFER/minio-data.tar"
docker compose up -d minio minio-init
```

比较源/目标的用户、角色、记忆、关系记录数量，并在迁移后的同一角色里核对少量已知历史事实；不要将真实记忆内容放进发布日志。`scripts/live-up.sh status` 只证明其标明的健康范围，不能替代这一步数据核验。

## 3. Windows：WSL2 与 GPU 容器准备

以下 PowerShell 命令在 Windows 执行；后续 Bash 命令在 Ubuntu WSL 中执行。推荐当前受支持的 Windows 11，并先安装支持 RTX 5080 的 NVIDIA **Windows** 驱动。

管理员 PowerShell：

```powershell
wsl --install -d Ubuntu-22.04
wsl --update
wsl --set-default-version 2
wsl --list --verbose
```

按系统提示重启，首次打开 Ubuntu 创建 Linux 用户。如果 Ubuntu 已安装，不要重复初始化；检查现有发行版是否为 WSL2。

安装 Docker Desktop for Windows，使用 **Linux containers / WSL 2 engine**，在 Settings → Resources → WSL Integration 启用该 Ubuntu。不要同时在这套 Ubuntu 中再部署另一套 Docker daemon。官方入口：[Microsoft 安装 WSL](https://learn.microsoft.com/en-us/windows/wsl/install)、[Docker WSL 配置](https://docs.docker.com/desktop/features/wsl/)、[Docker Windows GPU 支持](https://docs.docker.com/desktop/features/gpu/)。

**驱动不要装反：**WSL 使用 Windows 驱动映射的 `libcuda`，不要在 WSL 安装 Linux NVIDIA 驱动，也不要安装会带驱动的 `cuda` / `cuda-drivers` 元包。本指南的 CUDA Toolkit 位于仓库 Dockerfile 的 CUDA 12.8 devel 镜像里，无需给 Ubuntu 再装一套 host Toolkit。[NVIDIA WSL 指南](https://docs.nvidia.com/cuda/wsl-user-guide/index.html)

在 Ubuntu WSL 检查：

```bash
/usr/lib/wsl/lib/nvidia-smi
docker version
docker run --rm --gpus all nvidia/cuda:12.8.1-base-ubuntu22.04 nvidia-smi
```

这些命令会拉取基础镜像，但不下载 FlashHead 权重或调用收费模型。必须先确认容器能看到 5080。PyTorch 2.7 引入 Blackwell/CUDA 12.8 支持；这与当前 Dockerfile 的 PyTorch 2.7.1 路线匹配，但不等于 FlashAttention 和完整 worker 已在目标机验证。[PyTorch 说明](https://pytorch.org/blog/pytorch-2-7/)

若以后改成独立 Linux 主机，使用该 Linux 系统的 NVIDIA 驱动、Docker Engine 和 [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)；不要套用“WSL 不装 Linux 驱动”到裸机 Linux。

## 4. Windows：固定源码、模型与授权头像

在 WSL 的 Linux 文件系统中保存源码和模型，例如 `~/Projects`、`~/soulforge-assets`，不要复制 Mac 的 Python 虚拟环境。GPU 主机只需要 worker 目录及模型，不需要 Mac 的数据库或完整根 `.env`。

```bash
mkdir -p "$HOME/Projects" "$HOME/soulforge-assets/models" "$HOME/soulforge-assets/portraits"
cd "$HOME/Projects"
git clone https://github.com/LookJohnny/soulForge.git
cd soulForge
# 私有仓库先配置自己的 GitHub 认证；两机使用同一已发布 commit。
git checkout --detach 替换为MacBook核对过的仓库commit
docker build -t soulforge-avatar-worker:5080-lite packages/avatar-worker
```

Dockerfile 会调用 `packages/avatar-worker/scripts/fetch_flashhead.sh`，固定官方源码 commit `9bc03de06bb0de82cd6bc477804512ae06144bf2`，不下载模型。它使用 Python 3.10、CUDA 12.8、PyTorch 2.7.1、FlashAttention 2.8.0.post2；编译需要网络、磁盘和系统内存。构建失败应检查实际错误，不能用 CPU 或假画面回退当作成功。构建完成后可记录镜像 ID 与依赖以便下次重建：

```bash
docker image inspect --format '{{.Id}}' soulforge-avatar-worker:5080-lite > "$HOME/soulforge-assets/worker-image-id.txt"
docker run --rm --entrypoint pip soulforge-avatar-worker:5080-lite freeze > "$HOME/soulforge-assets/worker-pip-freeze.txt"
```

权重来自 [SoulX-FlashHead-1_3B](https://huggingface.co/Soul-AILab/SoulX-FlashHead-1_3B) 与 [facebook/wav2vec2-base-960h](https://huggingface.co/facebook/wav2vec2-base-960h)。先核对两者模型卡与许可；FlashHead 的 Apache-2.0 不替代肖像、声音或其他输入素材的授权。

用独立下载环境，记录每个模型的不可变 revision，后续换机复用这份 manifest。以下首次执行会真实下载模型；Lite 必须包含 **`Model_Lite` 和 `VAE_LTX`**，不能只下载 DiT 权重：

```bash
sudo apt-get update
sudo apt-get install -y python3-venv git
python3 -m venv "$HOME/.venvs/soulforge-download"
"$HOME/.venvs/soulforge-download/bin/pip" install 'huggingface_hub>=0.34,<2'
"$HOME/.venvs/soulforge-download/bin/python" - <<'PY'
import json
from pathlib import Path
from huggingface_hub import HfApi, snapshot_download
assets = Path.home() / "soulforge-assets"
manifest = assets / "model-revisions.json"
repos = {
    "Soul-AILab/SoulX-FlashHead-1_3B": ("SoulX-FlashHead-1_3B", ["Model_Lite/**", "VAE_LTX/**", "README.md", "LICENSE*"]),
    "facebook/wav2vec2-base-960h": ("wav2vec2-base-960h", None),
}
if manifest.exists():
    revisions = json.loads(manifest.read_text())
else:
    revisions = {repo: HfApi().model_info(repo).sha for repo in repos}
    assert all(len(rev) == 40 for rev in revisions.values())
    manifest.write_text(json.dumps(revisions, indent=2) + "\n")
for repo, (folder, patterns) in repos.items():
    snapshot_download(repo_id=repo, revision=revisions[repo],
                      local_dir=assets / "models" / folder, allow_patterns=patterns)
PY
```

首次查询得到的 revision 不是本仓库预先验证的权重版本，manifest 用于让同一次验收可复现。再次下载沿用保存的 revision，不自动切到新 `main`。已有经验证模型时，优先复制模型目录和同一份 manifest。

把**有使用权的参考头像**放为 `~/soulforge-assets/portraits/avatar.png`。当前 worker 不负责生成头像，缺少头像时不会启动；建议单人正面、头肩清晰，并提前裁好构图。不要拿未发布的 Unity/VRM 或 `.soul` 文件替代这张图像。

## 5. Windows：只启动一个 Lite worker

在 WSL 创建只含 worker 设置的私人环境文件；第一次创建后将其中 `AVATAR_WORKER_TOKEN` 通过私人方式填到 MacBook 根 `.env` 的同名字段，不要放入前端代码：

```bash
umask 077
mkdir -p "$HOME/.config/soulforge"
python3 - <<'PY'
from pathlib import Path
import secrets
path = Path.home() / ".config/soulforge/avatar-worker.env"
with path.open("x") as file:
    file.write("AVATAR_WORKER_TOKEN=" + secrets.token_hex(32) + "\n")
    file.write("MODEL_TYPE=lite\nAVATAR_SOURCE_IMAGE=/assets/portraits/avatar.png\n")
    file.write("MODEL_DIR=/assets/models/SoulX-FlashHead-1_3B\n")
    file.write("WAV2VEC_DIR=/assets/models/wav2vec2-base-960h\n")
path.chmod(0o600)
PY
docker run -d --name soulforge-avatar-worker --gpus all --restart unless-stopped \
  -p 127.0.0.1:8092:8092 \
  --env-file "$HOME/.config/soulforge/avatar-worker.env" \
  -e MODEL_TYPE=lite \
  --mount "type=bind,source=$HOME/soulforge-assets,target=/assets,readonly" \
  soulforge-avatar-worker:5080-lite
curl --fail http://127.0.0.1:8092/health
```

环境文件已存在时不要重复生成，否则两机 token 可能不再一致。容器名已存在时先检查原容器，不要并行开启第二个 worker。当前实现只支持单卡、一个请求；`WORLD_SIZE>1` 会拒绝启动。

`/health` 应看到 `model: SoulX-FlashHead/lite`、`sample_rate:16000`、`fps:25`、`block_samples:15360`、`frames_per_chunk:24`，且 `ready:true`。模型尚未加载、CUDA 不可用、源码不匹配或缺少资源会明确 not-ready。`ready` 仍不保证首轮编译完成、显存峰值可容纳或实际视频自然度。

在 Windows PowerShell 再检查一次，确认 Docker Desktop 把 loopback 端口发布到了 Windows：

```powershell
Invoke-RestMethod http://127.0.0.1:8092/health
```

如果只有 WSL 能访问、Windows loopback 不能访问，先修正 Docker Desktop WSL integration/端口发布；不要通过把 8092 开到整个局域网来掩盖这一步失败。

## 6. 从 MacBook 建立 SSH 隧道

在 Windows 配置 OpenSSH Server 与自己账户的 SSH 公钥登录，核对主机指纹。管理员 PowerShell 的基础服务安装步骤：

```powershell
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
Start-Service sshd
Set-Service -Name sshd -StartupType Automatic
Get-NetFirewallRule -Name OpenSSH-Server-In-TCP
```

将入站 SSH 防火墙规则限制到可信网络和 MacBook 的实际地址（或双方 VPN 地址），例如在现有规则上设置 `-RemoteAddress`；不开放 worker 8092，也不把数据库端口开放到 Windows。管理员账户与普通账户的 authorized_keys 路径不同，按 [Microsoft OpenSSH 指南](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_install_firstuse) 配置。首次连接不要跳过主机指纹校验。

MacBook 终端（示例用户名/IP 必须替换）：

```bash
SF_GPU_SSH='windows_user@192.168.1.50'
ssh -NT -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=3 \
  -L 127.0.0.1:8092:127.0.0.1:8092 "$SF_GPU_SSH"
```

保持该终端运行。这里远端 `127.0.0.1` 指 **Windows SSH 主机**，依赖上一步 Windows PowerShell 健康检查已经成功。独立 Linux 主机则将 `SF_GPU_SSH` 换为 Linux SSH 地址，并同样只发布 loopback worker 端口。HTTP token 留在两端服务配置，SSH 负责加密链路。

## 7. MacBook 接入与验收

根 `.env` 保留已有大脑配置，并设置：

```dotenv
SELFHOST_MEDIA_ENABLED=true
SELFHOST_MEDIA_PORT=8902
SELFHOST_MEDIA_URL=http://127.0.0.1:8902
SELFHOST_MEDIA_TOKEN=<独立随机密钥，至少24字符>
AVATAR_WORKER_URL=http://127.0.0.1:8092
AVATAR_WORKER_TOKEN=<与Windows私人worker.env完全一致>
LIVE_TUNNEL_PROVIDER=none
TAVUS_SYNC_ON_START=false
```

不要原样保留尖括号占位符。根 `.env` 的值覆盖旧 shell export；只在终端 `export` 同名变量可能不起作用。执行：

```bash
scripts/selfhost-up.sh --install
scripts/live-up.sh --check
scripts/live-up.sh
```

`--install` 使用独立 `packages/media-body/.venv` 与该包的 `uv.lock`，不会替代大脑 `.venv`。设为统一启动后，不要另开 `scripts/selfhost-up.sh` 争用 8902。另一个 MacBook 终端执行只读检查：

```bash
scripts/live-up.sh status
scripts/selfhost-up.sh --status
```

`--check` 和健康读取不发起模型请求；正式启动后的自主 Runtime 与用户交互可能调用已配置的模型，费用不只来自下面的 probe。

确认 Runtime 健康里的 `durable_outbox`、`pending_writes` 和错误状态符合预期，数据库恢复的原用户/角色可读取，待写队列持续投递。随后打开 `http://127.0.0.1:8899/joi?body=selfhost`。

**以下是真实调用**：会使用配置的大脑/语音服务及 5080，可能产生其服务费用。先运行短文本验收，收到的实际音画会保存为 MP4 和计时 JSON：

```bash
PYTHONPATH=packages/media-body/src packages/media-body/.venv/bin/python -m media_body.probe \
  --text '你好，请用一句话介绍自己。' --output outputs/selfhost-probe
```

probe 最多接收 60 秒，再进行有界清理；输出区分服务端生成时间与本地解码时间。MP4 是接收轨道的重新编码，两轨按首个解码帧的本地时间近似对齐，不是精确 RTCP 同步或真人听感证明。单独记录冷启动和预热后的结果，不能只用第二轮速度掩盖首次编译问题。

最后在真实浏览器测试连续发声、口型与声音同步、插话时音画同时停止、随后能按上下文继续。核对 Lite 实际峰值显存、每块生成耗时及长句连续性；Windows 休眠、Docker 停止、SSH 断开都会让 worker 不可用。GPU 更换不会自动解决首句语音等待、整块 JPEG 传输、角色自然度或当前未提供的语义眼神/身体动作控制。

## 8. 本指南核对的仓库入口

- [根环境模板](../.env.example)、[Compose 数据服务](../docker-compose.yml)、[Prisma schema](../packages/database/prisma/schema.prisma)
- [统一启动脚本](../scripts/live-up.sh)、[监督器](../scripts/live_stack.py)、[live stack 说明](live-stack.md)
- [独立 media 安装/启动](../scripts/selfhost-up.sh)、[media-body 协议](../packages/media-body/README.md)
- [worker Dockerfile](../packages/avatar-worker/Dockerfile)、[固定源码脚本](../packages/avatar-worker/scripts/fetch_flashhead.sh)、[适配器](../packages/avatar-worker/src/avatar_worker/backend.py)
- [GPU worker 协议与验证边界](self-hosted-gpu-worker.md)、[单认知与持久记忆](unified-cognition.md)

这里验证的是命令与现有接口的一致性，没有执行换机、数据库恢复、WSL 安装、权重下载、Docker 构建、5080 推理或收费模型调用。发布源码不等于完成这台 Windows 5080 的运行验收。
