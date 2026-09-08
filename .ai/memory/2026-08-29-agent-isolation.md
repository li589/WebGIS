# Memory: Agent profiles isolation (2026-08-29)

- Presets: `Code/agentKits/presets/provider_catalog.json` (not hardcoded URLs).
- Stores: `_runtime/agent/global_profiles.json` (admin) + `_runtime/agent/users/{uid}/profiles.json` (personal).
- Chat effective profile: personal active if set, else global.
- Read-only server tool: `search_layers`; session history under `_runtime/agent/sessions/`.
- Response fields: `steps`, `usage`, `ui_intents`.
