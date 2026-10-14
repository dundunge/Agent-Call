# Security and deployment scope

The public demo is static and browser-local. It does not run agent bridges, read provider credentials, or upload viewer prompts. Run state is not persisted beyond the page lifetime; optional theme preference uses localStorage.

The Python API is a local development service bound to loopback. Do not expose it as a public authenticated service without adding an explicit authentication, origin-validation, concurrency, and deployment design.

Do not commit launch URLs, cookies, tokens, `.env` files, SQLite state, logs, or native session transcripts. Existing provider bridges require explicit host configuration and dedicated integration evidence; the public mock does not verify them.

For a potential security issue, describe the affected code and a sanitized reproduction. Never post working secrets or private native-session contents in public issues.
