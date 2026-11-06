# Hermes hooks — the real contract (Path A)

Source of truth in the Hermes install: `hermes_cli/plugins.py` (`VALID_HOOKS`) and
`hermes_cli/hooks.py` (`_DEFAULT_PAYLOADS`). The Mission Control plugin
(`emitter/plugin/`) registers these hooks through `ctx.register_hook(...)`. **No
Hermes internals are patched** — this is the supported plugin surface.

## Hooks used

| Hook | Fires | Real payload fields | What the MC does |
|---|---|---|---|
| `pre_llm_call` | before a model turn | `session_id, user_message, conversation_history, is_first_turn, model, platform` | turn start (agent state) |
| `pre_api_request` | before a physical provider call | `session_id, task_id, model, provider, message_count, tool_count, approx_input_tokens, request_char_count, max_tokens` | context composition (counts + approx tokens) |
| `post_api_request` | after a provider call | `usage{input_tokens, output_tokens}, context_length, api_duration, finish_reason, moa_references, …` | exact usage + latency |
| `pre_tool_call` | before a tool call — **blockable** | `tool_name, args, session_id, task_id, tool_call_id` | tool start + approval gate |
| `post_tool_call` | after a tool call | `tool_name, args, result, duration_ms, session_id, task_id, tool_call_id` | tool end (duration, ok) |

## Blocking = the approval gate (no fake flag)

`pre_tool_call` is in `plugins_dispatch._HOOK_TIMEOUT_FAIL_CLOSED_HOOKS`. A callback
that returns `{"action": "block", "message": ...}` stops the tool call. The plugin
uses this for the `approve_tools` list:

1. tool call fires `pre_tool_call`
2. plugin calls `emitter.request_approval(agent, action, risk)`
3. the MC records the approval + notifies Discord
4. the plugin blocks on the MC long-poll until the decision
5. allow → the hook returns `None` (the tool runs); deny → `{"action": "block"}`

The block is real: the agent's tool call genuinely waits; a timeout denies.

## What is real vs estimated

- **Real:** usage tokens (`post_api_request`), message/tool counts and approx input
  tokens (`pre_api_request`), model, provider, latency, tool calls, tool duration.
- **Estimated:** the context *split* (system / task / tools / history / memory).
  The hooks give the total and the counts, not the per-section breakdown. The UI
  labels that split as an estimate; it never invents a precise number.

## Registration

```python
def register(ctx):
    ctx.register_hook("pre_llm_call", _pre_llm)
    ctx.register_hook("pre_api_request", _pre_api)
    ctx.register_hook("post_api_request", _post_api)
    ctx.register_hook("pre_tool_call", _pre_tool)
    ctx.register_hook("post_tool_call", _post_tool)
```

See `emitter/plugin/__init__.py`. The plugin is self-contained (`emitter/plugin/emitter.py`).

## Install per profile

The plugin is installed into `<profile>/plugins/hermes-mission-control/` and enabled
in that profile's `config.yaml` (`plugins.enabled`). A hook runs only in the profile
that runs the turn, so the plugin must be installed in **every** profile to cover the
whole fleet. See `docs/deploy.md`.
