# AI Team V1 · 多 Agent 会话工作台

V1 以 DSH 面板为 UI 基础，演示一个主控、三个一级线程和三个同组二级线程。点击每个线程可以查看独立消息、派发、模拟工具、回收结果和三层状态。

```text
GPT-6.1-Sol 主控
├─ DeepSeek V4 Pro · 研究
│  └─ DeepSeek V4 Flash · 证据抽取
├─ Grok · 风险
│  └─ 同组 Grok · 反例检查
└─ GPT-6.1-Sol · 实现
   └─ GPT-6 Luna · 验收复核
```

网页的模型名称是演示配置，运行内容来自预设脚本。公开网页不连接本机 Agent，不调用模型 API。模拟记录仅存在当前页面内存中，刷新重置；可导出 JSON 和 Markdown 模拟产物。

## 体验

- 运行、暂停、继续、单步与 1× / 2× / 4× 播放。
- 左侧层级线程树，中间独立会话，右侧任务、协议与架构检查器。
- 拓扑视图、事件筛选、原 requestId 与结果回收。
- “送达超时”场景：停止推进，查询原请求，再继续执行。
- 全部线程完成后，核对三项证据才记录主控验收通过。

## 本地启动

在 macOS Terminal 的仓库根目录运行。需要 Python 3.11+；前端运行没有 npm 安装要求。

```zsh
cd /path/to/Agent-Call
# 如果已有 uv：创建 Python 3.12 环境。
uv sync --project v1 --python 3.12
./scripts/start-v1.sh
open http://127.0.0.1:8766/
```

也可以用已有的 Python 3.11+ 启动：

```zsh
AITEAM_PYTHON=/absolute/path/to/python3 ./scripts/start-v1.sh
```

脚本使用当前用户的 launchd 服务，只监听 `127.0.0.1`。运行副本、日志和 SQLite 位于 `~/Library/Caches/AI-Team/<checkout-hash>/`，不修改系统服务、不要求管理员权限。当前登录会话中可持续运行；重新登录后再执行启动脚本。代码更新后，先停止再启动，以复制新版本。

```zsh
./scripts/status-v1.sh
./scripts/stop-v1.sh
```

只在前台启动（也适用于其他系统）：

```zsh
PYTHONPATH=v1 v1/.venv/bin/python -m agent_team_v1 \
  --db .agent-team-v1/state.sqlite3 serve --host 127.0.0.1 --port 8766
```

## 测试与静态发布包

自动化测试需要 Node.js 24+。jsdom 仅用于开发测试；发布网页无需 Node 或后端。

```zsh
npm ci --ignore-scripts
npm test
PYTHONPATH=v1 v1/.venv/bin/python -m unittest discover -s v1/tests -p 'test_*.py'
npm run build:demo
```

`dist/` 只包含 HTML、CSS、JavaScript 和 DSH 许可证。仓库的 GitHub Actions 会先测试，再把该目录发布到 GitHub Pages。

## 本地控制面

Python 包保留 SQLite 账本、串行重复派发保护、未知送达停止与证据验收。它与浏览器模拟器是两个独立模块，当前页面不调用该 API；CLI 支持 `create / dispatch / status / events / observe / accept`。

```zsh
PYTHONPATH=v1 v1/.venv/bin/python -m agent_team_v1 --help
```

[架构与分工](ARCHITECTURE.md) · [阶段路线与验收](ROADMAP.md) · [发布验收记录](ACCEPTANCE.md)
