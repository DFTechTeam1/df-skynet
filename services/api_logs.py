from typing import Any
from services.api_key_management import ApiKeyManagement
from utils.formatter import format_datetime


class ApiLogsService:
    def format_log(self, record: dict[str, Any], source: str) -> dict[str, Any]:
        """Shape one serialized DfEngineExternalApiCalls row for the API response.

        OpenRouter rows reuse ApiKeyManagement's redaction (it carries a
        management credential and secret key hashes); udin rows don't have
        that shape, so they only get the generic id/created_at cleanup.
        """
        if source == "openrouter":
            return ApiKeyManagement().format_log(record)
        record.pop("id", None)
        record.pop("request_headers", None)
        record["created_at"] = format_datetime(record["created_at"])
        return record
