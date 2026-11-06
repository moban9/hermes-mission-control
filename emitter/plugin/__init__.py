"""Mission Control plugin — real context / usage / tool events via Hermes hooks.

Registers Hermes' own plugin hooks and forwards real payloads to the MC API.
No tools, no writes into Hermes. All kwargs are the real Hermes payloads (see
hermes_cli/hooks.py _DEFAULT_PAYLOADS).
"""
import hashlib
import os

from . import emitter

APPROVE_TOOLS: set[str] = set()


def register(ctx):
    global APPROVE_TOOLS
    try:
        emitter.URL = str(ctx.get_config("mc_url", default=emitter.URL)).rstrip("/")
    except Exception:
        pass
    try:
        raw = str(ctx.get_config("approve_tools", default=""))
    except Exception:
        raw = ""
    APPROVE_TOOLS = {t.strip() for t in raw.split(",") if t.strip()}
    ctx.register_hook("pre_llm_call", _pre_llm)
    ctx.register_hook("pre_api_request", _pre_api)
    ctx.register_hook("post_api_request", _post_api)
    ctx.register_hook("pre_tool_call", _pre_tool)
    ctx.register_hook("post_tool_call", _post_tool)


def _agent() -> str | None:
    return os.getenv("MC_AGENT_ID") or None


def _hash(obj) -> str:
    try:
        return hashlib.sha1(repr(obj).encode()).hexdigest()[:10]
    except Exception:
        return ""


def _pre_llm(session_id=None, user_message=None, conversation_history=None,
             model=None, platform=None, is_first_turn=None, **_kw):
    try:
        hist = conversation_history or []
        emitter.emit("agent.state", _agent(), session_id=session_id, model=model,
                     platform=platform, state="thinking",
                     activity="new turn", message_count=len(hist))
    except Exception:
        pass
    return None


def _pre_api(session_id=None, task_id=None, model=None, provider=None,
             message_count=None, tool_count=None, approx_input_tokens=None,
             max_tokens=None, **_kw):
    try:
        emitter.emit("context.snapshot", _agent(), session_id=session_id,
                     task_id=task_id, model=model, provider=provider,
                     messages=message_count, tools=tool_count,
                     approx_input_tokens=approx_input_tokens, max_tokens=max_tokens)
    except Exception:
        pass
    return None


def _post_api(session_id=None, task_id=None, model=None, provider=None,
              usage=None, context_length=None, api_duration=None,
              finish_reason=None, **_kw):
    try:
        u = usage or {}
        emitter.emit("llm.usage", _agent(), session_id=session_id, task_id=task_id,
                     model=model, provider=provider,
                     input_tokens=u.get("input_tokens"),
                     output_tokens=u.get("output_tokens"),
                     latency_ms=int(api_duration * 1000) if api_duration else None,
                     context_length=context_length, finish_reason=finish_reason)
    except Exception:
        pass
    return None


def _pre_tool(tool_name=None, args=None, session_id=None, task_id=None, **_kw):
    try:
        emitter.emit("tool.call", _agent(), tool=tool_name, phase="start",
                     args_hash=_hash(args), session_id=session_id, task_id=task_id)
    except Exception:
        pass
    if tool_name in APPROVE_TOOLS:
        try:
            ok = emitter.request_approval(
                _agent() or "agent",
                f"{tool_name}: {str(args)[:180]}",
                "high",
            )
        except Exception:
            ok = False
        if not ok:
            return {"action": "block",
                    "message": "Denied by operator in Mission Control"}
    return None


def _post_tool(tool_name=None, args=None, duration_ms=None, result=None,
               session_id=None, task_id=None, **_kw):
    try:
        emitter.emit("tool.call", _agent(), tool=tool_name, phase="end",
                     duration_ms=duration_ms, ok=True,
                     session_id=session_id, task_id=task_id)
    except Exception:
        pass
    return None
