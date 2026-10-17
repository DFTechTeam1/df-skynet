from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from services.search.base import And, Equal, Or, SearchRequest
from services.search.providers.algolia import AlgoliaProvider


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr("services.search.providers.algolia.SearchClientSync", lambda *a, **k: MagicMock())
    return AlgoliaProvider("app", "write", "search")


def test_filter_rendering(provider):
    f = And([Equal("project_uid", 'a"b'), Or([Equal("kind", "image"), Equal("n", 1), Equal("is_main", True)])])
    assert provider._format_filter(f) == 'project_uid:"a\\"b" AND (kind:"image" OR n=1 OR is_main:true)'
    assert provider._format_value(False) == "false"
    with pytest.raises(TypeError):
        provider._format_filter("nope")  # type: ignore


def test_request_maps_every_option(provider):
    out = provider._format_request(
        SearchRequest("i", "q", Equal("a", 1), limit=5, page=2, restrict_attributes=["name"])
    )
    assert out == {
        "indexName": "i",
        "query": "q",
        "hitsPerPage": 5,
        "page": 2,
        "restrictSearchableAttributes": ["name"],
        "filters": "a=1",
    }
    assert provider._format_request(SearchRequest("i")) == {"indexName": "i", "query": ""}


def test_upsert_maps_id_and_skips_empty(provider):
    provider.upsert("i", [])
    provider.writer.save_objects.assert_not_called()
    provider.upsert("i", [{"id": "1", "a": 1}, {"objectID": "2", "id": "x"}])
    objects = provider.writer.save_objects.call_args.kwargs["objects"]
    assert objects == [{"a": 1, "objectID": "1"}, {"objectID": "2"}]


def test_delete_skips_empty(provider):
    provider.delete("i", [])
    provider.writer.delete_objects.assert_not_called()
    provider.delete("i", ["1"])
    provider.writer.delete_objects.assert_called_once_with(index_name="i", object_ids=["1"])


def test_search_drops_vendor_metadata_and_keeps_order(provider):
    hit = SimpleNamespace(to_dict=lambda: {"objectID": "1", "name": "a", "_highlightResult": {}})
    wrapper = SimpleNamespace(actual_instance=SimpleNamespace(hits=[hit], nb_hits=1))
    provider.reader.search.return_value = SimpleNamespace(results=[wrapper])
    [res] = provider.search([SearchRequest("i", "a")])
    assert res.total == 1 and res.hits[0].id == "1" and res.hits[0].data == {"objectID": "1", "name": "a"}
    assert provider.search([]) == []


def test_filter_never_parenthesises_the_top_level_group(provider):
    """Algolia rejects `(X AND (Y OR Z))` as `(X AND Y) OR Z`; the top level must be bare."""
    scope = Or([Equal("task_uid", "t"), Equal("song_uid", "t")])
    kinds = Or([Equal("kind", "image"), Equal("kind", "image_edit")])
    assert (
        provider._format_filter(And([scope, kinds]))
        == '(task_uid:"t" OR song_uid:"t") AND (kind:"image" OR kind:"image_edit")'
    )
    assert provider._format_filter(And([Equal("a", 1), And([Equal("b", 2), Equal("c", 3)])])) == "a=1 AND b=2 AND c=3"
    with pytest.raises(ValueError):
        provider._format_filter(Or([Equal("a", 1), And([Equal("b", 2), Equal("c", 3)])]))


def test_configure_index_sets_only_searchable_and_filter_fields(provider):
    provider.configure_index("i", ["name", "path"], ["project_uid", "kind"])
    provider.writer.set_settings.assert_called_once_with(
        index_name="i",
        index_settings={
            "searchableAttributes": ["name", "path"],
            "attributesForFaceting": ["filterOnly(project_uid)", "filterOnly(kind)"],
        },
    )
