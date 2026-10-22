from httpx import Timeout
from apps.secret import ERP_EMAIL, ERP_PASSWORD, LOGIN_URL
from log import logging
from services.api_caller import APICaller

TITLE = "Udin upload failed - manual upload needed"


def notify_udin_upload_failed(generation_uid: str, project_name: str, detail: str) -> None:
    """Best-effort Slack alert via the ERP backend; never raises (must not affect the upload task)."""
    if not (LOGIN_URL and ERP_EMAIL and ERP_PASSWORD):
        logging.warning("slack notify skipped, LOGIN_URL / ERP_EMAIL / ERP_PASSWORD not set")
        return
    try:
        caller = APICaller(base_url=LOGIN_URL, timeout=Timeout(10))  # type: ignore[arg-type]
        try:
            login = caller.call_sync(
                "POST",
                "/auth/login",
                json={"email": ERP_EMAIL, "password": ERP_PASSWORD, "remember_me": False},
                headers={"Accept": "application/json"},
                raise_for_status=False,
            )
            if login.is_error:
                logging.warning(f"slack notify login failed {login.status_code}")
                return
            token = login.json()["data"]["access_token"]
            res = caller.call_sync(
                "POST",
                "/system-slack/send-message",
                json={
                    "messageTitle": TITLE,
                    "title": TITLE,
                    "sectionBlock": [
                        {"message": f"*Generation:* {generation_uid}\n*Project:* {project_name}", "type": "mrkdwn"},
                        {"message": f"*Error:* {detail[:500]}", "type": "mrkdwn"},
                    ],
                    "contextBlock": [{"message": "df-engine • udin_sweep exhausted", "type": "mrkdwn"}],
                },
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                raise_for_status=False,
            )
            if res.is_error:
                logging.warning(f"slack notify failed {res.status_code}: {res.text[:200]}")
        finally:
            caller.sync_client.close()
    except Exception:
        logging.exception(f"slack notify crashed generation_uid={generation_uid}")
