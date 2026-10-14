# AI Team V1

[中文说明](README.zh-CN.md)

A DSH-style interactive workspace for hierarchical multi-model collaboration. The deterministic browser demo shows one GPT coordinator, DeepSeek/Grok/GPT first-level branches, and same-family second-level workers.

Features: independent thread conversations, topology, pause/resume/step controls, event inspection, artifact downloads, uncertain-delivery reconciliation using the original request ID, and evidence-gated final acceptance.

The public demo contains scripted fixtures, not model inference. It does not connect to local agents or credentials. Browser records live in memory and reset on refresh. The Python SQLite control plane is a separate local extension point; the demo does not call its API.

From the repository root, with Python 3.11+ and macOS zsh:

```sh
uv sync --project v1 --python 3.12
./scripts/start-v1.sh
# Open http://127.0.0.1:8766/
./scripts/stop-v1.sh
```

With Node 24+, `npm ci --ignore-scripts && npm test` runs the simulator and DOM interaction tests. `npm run build:demo` packages the static frontend in `dist/`.

See [architecture](ARCHITECTURE.md), [roadmap](ROADMAP.md), and [acceptance gates](ACCEPTANCE.md). DSH theme CSS is reused under MIT; the original license is retained in `web/vendor/DSH-LICENSE.txt`.
