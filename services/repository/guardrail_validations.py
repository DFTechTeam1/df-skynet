from typing import Any, Optional
from services.mysql.model import DfEngineGuardrailValidations
from services.repository.base import BaseRepository


class GuardrailValidationRepository(BaseRepository):
    async def get_guardrail_validation(
        self,
        filters: Optional[tuple[Any, ...]] = None,
        columns: Optional[tuple[Any, ...]] = None,
        options: Optional[tuple[Any, ...]] = None,
        joins: Optional[tuple[Any, ...]] = None,
        raise_if_null: bool = True,
        context: Optional[dict[str, Any]] = None,
        fetch_one: bool = True,
        limit: Optional[int] = None,
        group_by: Optional[tuple[Any, ...]] = None,
        having: Optional[tuple[Any, ...]] = None,
        order_by: Optional[tuple[Any, ...]] = None,
        offset: Optional[int] = None,
    ) -> Any:
        return await self._get(
            DfEngineGuardrailValidations,
            (DfEngineGuardrailValidations.cost,),
            "guardrail_validation_not_found",
            filters,
            columns,
            options,
            joins,
            raise_if_null,
            context,
            fetch_one,
            limit,
            group_by,
            having,
            order_by,
            offset,
        )
