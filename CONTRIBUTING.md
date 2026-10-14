# Contributing

The V1 UI source lives in `v1/agent_team_v1/web/`. Keep the frontend browser-local and preserve the Agent Call distinction between delivery, execution, and caller acceptance.

Use Node 24+ and Python 3.11+. Run `npm ci --ignore-scripts`, `npm test`, and `PYTHONPATH=v1 python -m unittest discover -s v1/tests -p 'test_*.py'` before submitting a change. A Python environment can be created with `uv sync --project v1 --python 3.12`.

Build the static demo with `npm run build:demo`. Changes to vendor theme files must retain the upstream license and source notice. Real adapter changes need dedicated integration evidence and must not alter the public mock into a local credential bridge.
