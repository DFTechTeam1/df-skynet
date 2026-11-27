import pytest
from services.mysql.factory.df_engine_generations import DfEngineGenerationsFactory
from services.mysql.factory.df_engine_generation_results import DfEngineGenerationResultsFactory
from tests.generation_fixtures import (  # noqa: F401  (fixtures)
    fake_generation_backends,
    generation_menu_feature,
    generation_project_settings,
    guardrail,
    image_model,
    pic_api_key,
    pic_employee_id,
    project_lead,
)

EDIT_URL = "/api/generations/image-edit"
EDIT_RESULTS_URL = "/api/generation-edit-results"
MAIN_RESULTS_URL = "/api/generation-main-results"


@pytest.mark.asyncio
async def test_edit_trigger_leaves_source_untouched_until_upload_completes(
    authed_client,
    project_task,
    user_id,
    generation_menu_feature,
    image_model,
    pic_api_key,
    generation_project_settings,
    fake_generation_backends,
):
    """Full loop against real endpoints (Celery/OpenRouter faked): a root file is
    edited via `POST /generations/image-edit/{file_uid}`, whose immediate response
    must chain `parent_id` back to the source. Since the actual new
    `DfEngineGenerationResults` row is only written later by the (here, un-run)
    `udin_uploader` Celery task, both `/generation-edit-results` and
    `/generation-main-results` must still describe the untouched source
    immediately afterwards - the trigger does not mutate the source synchronously."""
    menu, feature = generation_menu_feature
    source_generation = DfEngineGenerationsFactory.create(
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(user_id),
        sourceable_id=1,
        model_id=image_model.id,
        menu_id=menu.id,
        feature_id=feature.id,
    )
    source = DfEngineGenerationResultsFactory.create(
        generation_id=source_generation.id, created_by=int(user_id), is_main=True, version=1
    )

    edit_resp = await authed_client.call(
        "POST",
        f"{EDIT_URL}/{source.uid}",
        json={
            "prompt": "make it look like golden hour",
            "model_uid": str(image_model.uid),
            "menu_uid": str(menu.uid),
            "feature_uid": str(feature.uid),
            "references": [],
            "parameter": {},
        },
    )
    assert edit_resp.status_code == 200
    assert edit_resp.json()["data"]["parent_id"] == source.id
    assert len(fake_generation_backends) == 1

    edit_results_resp = await authed_client.call("GET", f"{EDIT_RESULTS_URL}/{source_generation.uid}")
    main_results_resp = await authed_client.call("GET", f"{MAIN_RESULTS_URL}/{source_generation.uid}")
    assert edit_results_resp.json()["data"]["file_uid"] == str(source.uid)
    assert edit_results_resp.json()["data"]["is_main"] is True
    assert edit_results_resp.json()["data"]["version"] == 1
    assert main_results_resp.json()["data"]["file_uid"] == str(source.uid)
