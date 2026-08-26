"""Self-check for the hand-written RelatedFactory cascade wiring in
df_engine_menus.py / df_engine_features.py — not a pure-logic unit test like
its neighbors here, but the cheapest existing bucket to run it from.
"""

from apps.secret import DB_SYNC_URL
from services.mysql import make_sync_session
from services.mysql.factory.df_engine_features import DfEngineFeaturesFactory
from services.mysql.factory.df_engine_menus import DfEngineMenusFactory
from services.mysql.model.users import Users


def _any_user_id() -> int:
    session = make_sync_session(DB_SYNC_URL)
    user = session.query(Users).first()
    assert user is not None, "dev DB has no user row to satisfy created_by NOT NULL"
    return user.id


def test_menu_factory_cascades_into_feature_and_prompt_template():
    """Creating a Menu auto-creates one linked feature, which auto-creates one linked prompt template."""
    uid = _any_user_id()
    menu = DfEngineMenusFactory.create(
        created_by=uid,
        df_engine_menu_feature_mapping__df_engine_features__created_by=uid,
        df_engine_menu_feature_mapping__df_engine_features__df_engine_feature_prompt_mapping__df_engine_prompt_templates__created_by=uid,
    )

    menu_mappings = menu.df_engine_menu_feature_mappings
    assert len(menu_mappings) == 1
    feature = menu_mappings[0].df_engine_features
    assert feature is not None

    feature_mappings = feature.df_engine_feature_prompt_mappings
    assert len(feature_mappings) == 1
    assert feature_mappings[0].df_engine_prompt_templates is not None


def test_menu_factory_cascade_can_be_suppressed():
    """`df_engine_menu_feature_mapping=None` opts a test out of the auto-created chain."""
    uid = _any_user_id()
    menu = DfEngineMenusFactory.create(created_by=uid, df_engine_menu_feature_mapping=None)
    assert menu.df_engine_menu_feature_mappings == []


def test_feature_factory_cascade_can_be_suppressed():
    """`df_engine_feature_prompt_mapping=None` opts a test out of the auto-created prompt template."""
    uid = _any_user_id()
    feature = DfEngineFeaturesFactory.create(created_by=uid, df_engine_feature_prompt_mapping=None)
    assert feature.df_engine_feature_prompt_mappings == []
