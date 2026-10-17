from typing import Any
from algoliasearch.search.client import SearchClientSync
from services.search.base import And, Equal, Filter, Or, SearchHit, SearchRequest, SearchResult


class AlgoliaProvider:
    """Algolia implementation of `SearchProvider` (see services/search/base.py).

    Two clients are used on purpose: `upsert`/`delete` go through the write key,
    `search` goes through the search-only key, so the write key never has to
    reach anything that only reads.

    Mapping between the neutral contract and Algolia:
        document "objectID"/"id" ->  Algolia `objectID` on upsert; hits come back with `objectID` as stored
        Equal / And / Or tree    ->  `filters` string, e.g. (user_id=1 AND (type:"pdf" OR type:"docx"))
        SearchRequest.limit      ->  `hitsPerPage` (None = Algolia default, 20)
        SearchRequest.page       ->  `page` (0-based)
        SearchRequest list       ->  one multi-query call, results in request order

    Algolia setup: string/bool fields used in a filter must be declared in the
    index's `attributesForFaceting` (as `filterOnly(field)`), otherwise Algolia
    rejects the query. Numeric fields (`field=1`) need no declaration.

    Example:
        provider = AlgoliaProvider(app_id, write_key, search_key)
        provider.upsert("uploaded_files", [{"objectID": "1", "type": "pdf", "user_id": 1}])
        for res in provider.search([SearchRequest("uploaded_files", filter=Equal("user_id", 1))]):
            print([hit.data for hit in res.hits])
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
    def _format_filter(cls, f: Filter, nested: bool = False) -> str:
        """Translate the Equal/And/Or tree into Algolia's `filters` string.

        Equal("user_id", 1)                      -> user_id=1
        Equal("type", "pdf")                     -> type:"pdf"
        And([a, b]) / Or([a, b])                 -> a AND b / a OR b, nested recursively

        Parentheses are only added around a group nested inside another one. Algolia reads a fully parenthesised
        `(X AND (Y OR Z))` as `(X AND Y) OR Z` and rejects it, while `X AND (Y OR Z)` is accepted. A nested group of
        the same operator is merged into its parent, since `a AND (b AND c)` is just `a AND b AND c`.

        Raises:
            TypeError: for a filter type this provider cannot translate.
            ValueError: for an `And` inside an `Or`; Algolia only accepts `(X OR Y) AND Z`, never `(X AND Y) OR Z`.
        """
        if isinstance(f, Equal):
            is_number = isinstance(f.value, (int, float)) and not isinstance(f.value, bool)
            return f"{f.field}{'=' if is_number else ':'}{cls._format_value(f.value)}"
        if isinstance(f, (And, Or)):
            if isinstance(f, Or) and any(isinstance(i, And) for i in f.items):
                raise ValueError("Algolia does not support an And inside an Or")
            op = " AND " if isinstance(f, And) else " OR "
            parts = [
                cls._format_filter(i, nested=not isinstance(i, type(f)))
                if isinstance(i, (And, Or))
                else cls._format_filter(i)
                for i in f.items
            ]
            text = op.join(parts)
            return f"({text})" if nested else text
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
        if r.restrict_attributes:
            p["restrictSearchableAttributes"] = r.restrict_attributes
        if r.filter is not None:
            p["filters"] = self._format_filter(r.filter)
        return p

    def configure_index(self, index: str, searchable: list[str], filterable: list[str]) -> None:
        """Make `searchable` the index's searchable attributes (in ranking order) and `filterable` usable in filters
        (`filterOnly`). Only these two settings are written and the rest of the index is left alone, so repeating it is
        harmless. Without them Algolia rejects `restrictSearchableAttributes` and string filters."""
        self.writer.set_settings(
            index_name=index,
            index_settings={
                "searchableAttributes": searchable,
                "attributesForFaceting": [f"filterOnly({field})" for field in filterable],
            },
        )

    def upsert(self, index: str, docs: list[dict[str, Any]]) -> None:
        """Insert or replace documents in one batched call (the SDK splits large
        lists itself). Each doc must contain "objectID" or "id"; "objectID" wins
        if both are given, and "id" is stored as `objectID`.
        Blocks until Algolia has finished indexing, so a search right after sees the new data.
        An empty list is a no-op.

        Raises:
            KeyError: if a doc has neither "objectID" nor "id".
        """
        if not docs:
            return
        objects = [
            {**{k: v for k, v in d.items() if k != "id"}, "objectID": d.get("objectID") or d["id"]} for d in docs
        ]
        self.writer.save_objects(index_name=index, objects=objects, wait_for_tasks=True)

    def delete(self, index: str, ids: list[str]) -> None:
        """Delete documents by id (their `objectID`) in one batched call.
        Asynchronous: a search right after may still return the deleted docs.
        An empty list is a no-op."""
        if not ids:
            return
        self.writer.delete_objects(index_name=index, object_ids=ids)

    def search(self, requests: list[SearchRequest]) -> list[SearchResult]:
        """Run all requests in a single Algolia multi-query call. Each request
        keeps its own index, query, filter and paging. Results are returned in
        the same order as `requests`; there is no cross-index ranking.

        Each hit's `data` is the document as indexed, `objectID` included. Algolia's
        own metadata (`_highlightResult`, `_snippetResult`, ...) is dropped.
        An empty list returns [] without a call.
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
                hits.append(
                    SearchHit(id=data["objectID"], data={k: v for k, v in data.items() if not k.startswith("_")})
                )
            out.append(SearchResult(hits=hits, total=res.nb_hits))
        return out
