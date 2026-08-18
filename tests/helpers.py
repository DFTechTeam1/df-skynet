from typing import Any, Optional, Type, TypeVar
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlmodel import SQLModel
from services.mysql.model import Users
from utils.formatter import format_creator
from utils.serializer import serialize

ModelT = TypeVar("ModelT", bound=SQLModel)


async def create_record(db_session: AsyncSession, model: Type[ModelT], data: dict[str, Any]) -> ModelT:
    record = model(**data)
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)
    return record


async def expected_user(db_session: AsyncSession, user_id: int) -> Optional[dict[str, Any]]:
    user = (
        await db_session.execute(
            select(Users)
            .where(Users.id == int(user_id))  # type: ignore
            .options(selectinload(Users.employees))  # type: ignore
        )
    ).scalar_one()
    return format_creator(serialize(user))


def find_by_name(items: list[dict[str, Any]], name: str) -> dict[str, Any]:
    return next(t for t in items if t["name"] == name)


def response_names(body: dict[str, Any]) -> list[str]:
    return [t["name"] for t in body["data"]]
