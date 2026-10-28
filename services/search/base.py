from dataclasses import dataclass
from typing import Any, Optional, Protocol, Union
from pydantic import BaseModel


class SearchHit(BaseModel):
    """One matching document."""

    id: str
    data: dict[str, Any]


class SearchResult(BaseModel):
    """Result of one SearchRequest."""

    hits: list[SearchHit]
    total: int


@dataclass
class Equal:
    """field == value. The field must be filterable in the engine
    (Algolia: listed in `attributesForFaceting` as `filterOnly(field)`)."""

    field: str
    value: Any


@dataclass
class And:
    """All nested filters must match. Filters nest freely."""

    items: list["Filter"]


@dataclass
class Or:
    """At least one nested filter must match. This is OR between filter
    conditions, not between query words. `In` is an `Or` of `Equal`."""

    items: list["Filter"]


Filter = Union[Equal, And, Or]


@dataclass
class SearchRequest:
    """One search against one index, with its own query, filter and paging.

    Args:
        index: index name.
        query: free text; "" lists everything (use with filter/paging).
        filter: optional Equal/And/Or tree. Always scope by owner/tenant
            server-side; never take that filter from client input.
        limit: results per page; None = provider default (Algolia: 20).
        page: 0-based page number; None = first page.
        restrict_attributes: only match the query against these fields; None = all searchable fields.
    """

    index: str
    query: str = ""
    filter: Optional[Filter] = None
    limit: Optional[int] = None
    page: Optional[int] = None
    restrict_attributes: Optional[list[str]] = None


class SearchProvider(Protocol):
    """Contract every engine adapter implements.

    App code depends only on this contract. Vendor SDKs are imported only inside
    `providers/`. To switch engines, write a new provider implementing these
    three methods and change `get_search_engine()`.

    Example:
        from services.search import get_search_engine
        from services.search.base import And, Equal, Or, SearchRequest

        search = get_search_engine()

        # index (every doc needs an "id" key)
        search.upsert("uploaded_files", [{"id": "1", "name": "a.pdf", "type": "pdf", "user_id": 1}])

        # one query, one index
        [res] = search.search([SearchRequest("uploaded_files", "report")])

        # several indexes, a different filter for each (one network call)
        files, results = search.search([
            SearchRequest("uploaded_files", "launch",
                          And([Equal("user_id", 1), Or([Equal("type", "pdf"), Equal("type", "docx")])])),
            SearchRequest("generation_results", "launch", Equal("status", "done"), limit=5),
        ])
        for hit in files.hits:
            print(hit.id, hit.data)
    """

    def configure_index(self, index: str, searchable: list[str], filterable: list[str]) -> None:
        """Set which fields free text is matched against (in ranking order) and which fields filters may use.
        Idempotent. Must run before the first search that restricts attributes or filters."""
        ...

    def upsert(self, index: str, docs: list[dict[str, Any]]) -> None:
        """Insert or replace documents. Each doc must contain an "id" key
        (or "objectID", used as-is); the adapter maps it to the engine's own id field. Writes are async on
        the engine side, so an immediate search may not see them yet."""
        ...

    def delete(self, index: str, ids: list[str]) -> None:
        """Delete documents by id."""
        ...

    def search(self, requests: list[SearchRequest]) -> list[SearchResult]:
        """Run all requests in one call. Results are returned in the same
        order as `requests`. There is no cross-index ranking or merging."""
        ...
