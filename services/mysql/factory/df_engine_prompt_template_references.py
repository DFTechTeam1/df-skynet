from apps.secret import DB_SYNC_URL
from factory.alchemy import SQLAlchemyModelFactory
from services.mysql import make_sync_session
from services.mysql.model.df_engine_prompt_template_references import DfEnginePromptTemplateReferences


class DfEnginePromptTemplateReferencesFactory(SQLAlchemyModelFactory):
    class Meta:  # type: ignore
        model = DfEnginePromptTemplateReferences
        sqlalchemy_session = make_sync_session(DB_SYNC_URL)
        sqlalchemy_session_persistence = "commit"

    id = None
    main_template_id = None
    reference_id = None
