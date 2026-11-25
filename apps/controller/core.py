from functools import cached_property
from typing import Any
from fastapi import Depends
from apps.controller import Controller, ApiController
from apps.dependency.rate_limitter import rate_limit
from apps.dependency.auth import get_user
from services.mysql import get_db
from services.redis import CacheKeys, get_redis
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis
from services.repository.chat_assistants import ChatAssistantRepository
from services.repository.chat_sessions import ChatSessionRepository
from services.repository.currencies import CurrencyRepository
from services.repository.generation_results import GenerationResultRepository
from services.repository.generations import GenerationRepository
from services.repository.guardrail_validations import GuardrailValidationRepository
from services.repository.uploaded_files import UploadedFileRepository
from services.repository.menus import MenuRepository
from services.repository.model_options import ModelOptionRepository
from services.repository.projects import ProjectRepository
from services.repository.settings import AdminSettingRepository
from services.repository.users import UserRepository


class CoreDependencies(ApiController):
    throttle: Any = Depends(rate_limit())
    user: dict[str, Any] = Depends(get_user)
    db: AsyncSession = Depends(get_db)
    redis: Redis = Depends(get_redis)

    @cached_property
    def cache_key(self) -> CacheKeys:
        return CacheKeys()

    @cached_property
    def project_repo(self) -> ProjectRepository:
        return ProjectRepository(self.db)

    @cached_property
    def menu_repo(self) -> MenuRepository:
        return MenuRepository(self.db)

    @cached_property
    def admin_repo(self) -> AdminSettingRepository:
        return AdminSettingRepository(self.db)

    @cached_property
    def user_repo(self) -> UserRepository:
        return UserRepository(self.db)

    @cached_property
    def chat_assistant_repo(self) -> ChatAssistantRepository:
        return ChatAssistantRepository(self.db)

    @cached_property
    def chat_session_repo(self) -> ChatSessionRepository:
        return ChatSessionRepository(self.db)

    @cached_property
    def generation_repo(self) -> GenerationRepository:
        return GenerationRepository(self.db)

    @cached_property
    def guardrail_validation_repo(self) -> GuardrailValidationRepository:
        return GuardrailValidationRepository(self.db)

    @cached_property
    def generation_result_repo(self) -> GenerationResultRepository:
        return GenerationResultRepository(self.db)

    @cached_property
    def uploaded_file_repo(self) -> UploadedFileRepository:
        return UploadedFileRepository(self.db)

    @cached_property
    def model_option_repo(self) -> ModelOptionRepository:
        return ModelOptionRepository(self.db)

    @cached_property
    def currency_repo(self) -> CurrencyRepository:
        return CurrencyRepository(self.db)


class PlainDependencies(Controller):
    throttle: Any = Depends(rate_limit())
