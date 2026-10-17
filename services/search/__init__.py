from functools import lru_cache
from typing import Literal
from services.search.providers.algolia import AlgoliaProvider
from apps.secret import ALGOLIA_APP_ID, ALGOLIA_SEARCH_API_KEY, ALGOLIA_WRITE_API_KEY


@lru_cache(maxsize=None)
def get_search_engine(engine: Literal["algolia"] = "algolia") -> AlgoliaProvider:
    if engine == "algolia":
        return AlgoliaProvider(ALGOLIA_APP_ID, ALGOLIA_WRITE_API_KEY, ALGOLIA_SEARCH_API_KEY)
    raise ValueError(f"Unknown search engine: {engine}")
