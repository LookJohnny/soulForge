# SoulForge Live · 桌面壳（Tauri 2）

把 `studio/server.py` 提供的 `/live` 页面装进两个窗口：

- **main**：完整陪伴应用（1280×820）
- **overlay**：`/live?transparent=1&hud=0` —— 透明、无边框、置顶、可拖拽的桌面伴侣；
  `Cmd/Ctrl+Shift+U` 全局切换显示

## 运行

```bash
uv run python studio/server.py --port 8899        # 先起页面服务（gateway/ai-core 照常）
cd apps/desktop/src-tauri && cargo tauri dev      # 需要 cargo install tauri-cli --version '^2'
```

没有 tauri-cli 时 `cargo build` 也能编译出可执行文件（`target/debug/soulforge-desktop`），
它会连 `devUrl`；release 打包才需要 `frontendDist`。

## 透明悬浮窗的四件事（缺一不可）

1. 窗口 `transparent + decorations:false + shadow:false`
2. `app.macOSPrivateApi: true`
3. 页面本身不画背景：`live.js` 读 `?transparent=1` / `window.__SOULFORGE_HOST__`，去掉背景色、地面、圆盘，`renderer.setClearColor(0,0)`
4. 透明模式下**不能挂后处理**（EffectComposer 会吃掉 alpha）——`/live` 本来就没挂

点击穿透（只让模型区域接收鼠标）aikeya 也没做成：需要模型轮廓与 HTML UI rect 的并集做 hit-test，留待以后。

## 图标

`icons/icon.png` 请放一张 1024×1024 PNG 后再开 `bundle.active`。
