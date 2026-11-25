from sqlalchemy import text
from sqlalchemy.orm import Session
from config.variables import USD_TO_IDR_RATE
from log import logging
from services.repository.base import BaseRepository

CALL_USD_RATE = text("CALL get_currency_rate('USD')")
FALLBACK_USD_PER_IDR = round(float(1 / USD_TO_IDR_RATE), 8)


def get_usd_rate(db: Session) -> float:
    """USD per 1 IDR, so `idr = usd / rate`. Falls back to `FALLBACK_USD_PER_IDR` if the call fails
    or returns nothing."""
    try:
        row = db.execute(CALL_USD_RATE).fetchone()
        if row and row[0]:
            return round(float(row[0]), 8)
        logging.warning(f"[get-usd-rate] no rate returned, using fallback={FALLBACK_USD_PER_IDR}")
    except Exception:
        logging.exception(f"[get-usd-rate] failed, using fallback={FALLBACK_USD_PER_IDR}")
    return FALLBACK_USD_PER_IDR


class CurrencyRepository(BaseRepository):
    async def get_usd_rate(self) -> float:
        return await self.db.run_sync(get_usd_rate)
