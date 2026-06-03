"""Patrick's tools — six routable + three infra modules + one helper.

Routable (the tool router dispatches these):
    web_search, db_query, file_read, cloud_write (file_write), shell_exec, api_call

Infrastructure:
    tool_router      — pattern-matched dispatcher + chaining
    telemetry        — JSONL audit log
    conversation_memory — SQLite-backed per-thread history

Helper:
    gemini_chat      — minimal Gemini Flash chat for cloud escalation
"""
