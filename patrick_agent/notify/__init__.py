"""Notification system — channels + tiered formatters.

Public API:
    Channel, ChannelConfig, ChannelFormat, DeliveryResult, Severity   (base.py)
    fmt_report, fmt_alert, fmt_job_health, should_interrupt           (formatter.py)
    TelegramChannel                                                    (telegram.py)
"""
