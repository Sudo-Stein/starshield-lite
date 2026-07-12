"""Optional external alert hooks.

Console-only by default. Use ``services/notifications.py`` for webhook delivery
(Discord, Slack, generic HTTP POST).
"""


def send_alert(message: str, channel: str = "console") -> None:
    """Dispatch an alert. Currently prints to console only."""
    print(f"[ALERT:{channel}] {message}")
