"""Search port and initial published-content keyword adapter."""

import re
from typing import Protocol

from . import storage


class KnowledgeSearchPort(Protocol):
    def search(self, query: str, limit: int = 5) -> list[dict]: ...


class KeywordSearch:
    def search(self, query: str, limit: int = 5) -> list[dict]:
        query = query.strip().lower()
        if not query:
            return []
        # Bigrams support Chinese phrases without an external tokenizer. This is
        # lexical matching, not a relevance confidence or semantic guarantee.
        terms = set(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2}", query))
        terms |= {
            query[i : i + 2]
            for i in range(len(query) - 1)
            if "\u4e00" <= query[i] <= "\u9fff"
        }
        matches = []
        for row in storage.rows("SELECT * FROM knowledge WHERE status='published'"):
            heading = (row["title"] + " " + row["aliases"]).lower()
            text = heading + " " + row["body"].lower()
            score = sum(3 if term in heading else 1 for term in terms if term in text)
            if score:
                matches.append(
                    (
                        score,
                        {
                            "id": row["id"],
                            "version": row["version"],
                            "type": row["kind"],
                            "title": row["title"],
                            "snippet": row["body"][:4000],
                            "source": f"knowledge:{row['id']}@{row['version']}",
                        },
                    )
                )
        return [
            hit
            for _, hit in sorted(matches, key=lambda pair: pair[0], reverse=True)[
                : min(limit, 10)
            ]
        ]
