"""Patrick's tools — six routable + two infra modules + one helper.

Routable (the tool router dispatches these):
    web_search, db_query, file_read, cloud_write (file_write), shell_exec, api_call

Infrastructure:
    tool_router      — pattern-matched dispatcher + chaining
    telemetry        — JSONL audit log

Helper:
    gemini_chat      — minimal Gemini Flash chat for cloud escalation
"""
