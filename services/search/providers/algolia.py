from typing import Any
from algoliasearch.search.client import SearchClientSync
from services.search.base import And, Equal, Filter, Or, SearchHit, SearchRequest, SearchResult


class AlgoliaProvider:
    """Algolia implementation of `SearchProvider` (see services/search/base.py).

    Two clients are used on purpose: `upsert`/`delete` go through the write key,
    `search` goes through the search-only key, so the write key never has to
    reach anything that only reads.

    Mapping between the neutral contract and Algolia:
        document "id"            <-> Algolia `objectID`
        Equal / And / Or tree    ->  `filters` string, e.g. (user_id=1 AND (type:"pdf" OR type:"docx"))
        SearchRequest.limit      ->  `hitsPerPage` (None = Algolia default, 20)
        SearchRequest.page       ->  `page` (0-based)
        SearchRequest list       ->  one multi-query call, results in request order

    Algolia setup: every field used in a filter must be declared in the index's
    `attributesForFaceting` (as `filterOnly(field)`), otherwise Algolia rejects
    the query.

    Example:
        provider = AlgoliaProvider(app_id, write_key, search_key)
        provider.upsert("uploaded_files", [{"id": "1", "type": "pdf", "user_id": 1}])
        [res] = provider.search([SearchRequest("uploaded_files", "", Equal("user_id", 1))])
    """

    def __init__(self, app_id: str, write_key: str, search_key: str) -> None:
        self.writer = SearchClientSync(app_id, write_key)
        self.reader = SearchClientSync(app_id, search_key)

    @staticmethod
    def _format_value(v: Any) -> str:
        """Render one value for Algolia's filter syntax: bool -> true/false,
        numbers as-is, everything else quoted with `\\` and `"` escaped so a
        value can never break out of the quotes and inject filter syntax."""
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return str(v)
        return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'

    @classmethod
    def _format_filter(cls, f: Filter) -> str:
        """Translate the Equal/And/Or tree into Algolia's `filters` string.

        Equal("user_id", 1)                      -> user_id=1
        Equal("type", "pdf")                     -> type:"pdf"
        And([a, b]) / Or([a, b])                 -> (a AND b) / (a OR b), nested recursively

        Raises:
            TypeError: for a filter type this provider cannot translate.
        """
        if isinstance(f, Equal):
            return f"{f.field}:{cls._format_value(f.value)}"
        if isinstance(f, (And, Or)):
            op = " AND " if isinstance(f, And) else " OR "
            return "(" + op.join(cls._format_filter(i) for i in f.items) + ")"
        raise TypeError(f"Unsupported filter: {type(f).__name__}")

    def _format_request(self, r: SearchRequest) -> dict[str, Any]:
        """Translate one SearchRequest into an Algolia query dict.
        `hitsPerPage`, `page` and `filters` are only sent when set, so unset
        values fall back to Algolia's defaults."""
        p: dict[str, Any] = {"indexName": r.index, "query": r.query}
        if r.limit is not None:
            p["hitsPerPage"] = r.limit
        if r.page is not None:
            p["page"] = r.page
        if r.filter is not None:
            p["filters"] = self._format_filter(r.filter)
        return p

    def upsert(self, index: str, docs: list[dict[str, Any]]) -> None:
        """Insert or replace documents in one batched call (the SDK splits large
        lists itself). Each doc must contain "id"; it is stored as `objectID`.
        Indexing finishes asynchronously on Algolia's side, so an immediate
        search may not see the new data. An empty list is a no-op.

        Raises:
            KeyError: if a doc has no "id".
        """
        if not docs:
            return
        objects = [{**{k: v for k, v in d.items() if k != "id"}, "objectID": d["id"]} for d in docs]
        self.writer.save_objects(index_name=index, objects=objects)

    def delete(self, index: str, ids: list[str]) -> None:
        """Delete documents by id (their `objectID`) in one batched call.
        Asynchronous like `upsert`. An empty list is a no-op."""
        if not ids:
            return
        self.writer.delete_objects(index_name=index, object_ids=ids)

    def search(self, requests: list[SearchRequest]) -> list[SearchResult]:
        """Run all requests in a single Algolia multi-query call. Each request
        keeps its own index, query, filter and paging. Results are returned in
        the same order as `requests`; there is no cross-index ranking.

        In each hit, the Algolia `objectID` is replaced by "id" so no vendor
        field name reaches app code. An empty list returns [] without a call.
        """
        if not requests:
            return []

        resp = self.reader.search({"requests": [self._format_request(r) for r in requests]})
        out: list[SearchResult] = []
        for wrapper in resp.results:
            res: Any = wrapper.actual_instance  # oneOf wrapper in the Algolia SDK
            hits = []
            for h in res.hits:
                data = h.to_dict()
                # contract: hit.id / hit.data["id"] are the id you indexed, no vendor field names
                hits.append(
                    SearchHit(
                        id=data["objectID"],
                        data={**{k: v for k, v in data.items() if k != "objectID"}, "id": data["objectID"]},
                    )
                )
            out.append(SearchResult(hits=hits, total=res.nb_hits))
        return out
