"""Bounded tag-priority recall without changing the question or bank scope."""

import asyncio
import logging

logger = logging.getLogger(__name__)


async def recall_with_priority(client, kwargs: dict, priority_tags: list[str]) -> dict:
    """Reserve one third of the existing result budget for source-level priority facts."""
    budget = kwargs["max_tokens"]
    if not priority_tags or budget < 3:
        response = await client.arecall(**kwargs)
        return response.model_dump(mode="json", by_alias=True, exclude_none=True)
    priority_budget = budget // 3
    primary = {**kwargs, "max_tokens": budget - priority_budget}
    priority = {**kwargs, "max_tokens": priority_budget, "types": ["world", "experience"],
                "tags": list(dict.fromkeys([*(kwargs.get("tags") or []), *priority_tags])),
                "tags_match": "all_strict", "include_source_facts": False}
    calls = await asyncio.gather(client.arecall(**primary), client.arecall(**priority), return_exceptions=True)
    result = {"results": []}
    failures = []
    seen = set()
    # Priority facts must survive consumers that read only the beginning of the response.
    for label, response in (("priority", calls[1]), ("primary", calls[0])):
        if isinstance(response, BaseException):
            if isinstance(response, asyncio.CancelledError):
                raise response
            failures.append(label)
            logger.warning("Hindsight %s recall failed (%s); retaining the other response", label, type(response).__name__)
            continue
        data = response.model_dump(mode="json", by_alias=True, exclude_none=True)
        for item in data.get("results", []):
            if item["id"] not in seen:
                seen.add(item["id"])
                result["results"].append(item)
        for key in ("source_facts", "chunks", "entities"):
            if data.get(key):
                result.setdefault(key, {}).update(data[key])
    if len(failures) == 2:
        raise calls[0]
    result["priority_recall"] = {"state": "partial" if failures else "complete",
                                 "failed_passes": failures, "reserved_tokens": priority_budget}
    return result
