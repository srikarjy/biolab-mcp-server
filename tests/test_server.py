"""One live end-to-end test: real MCP stdio client/server connection, real PubMed
call, real SQLite file. This is the only test in the suite that proves the pieces
actually work wired together, not just each module in isolation — see
QUESTIONS_AND_ANSWERS.md for why this exists alongside the fixture-free unit tests.
"""

import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PROJECT_ROOT = Path(__file__).resolve().parent.parent


async def _call_search_pubmed(db_path: str, arguments: dict):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "biolab.server"],
        cwd=str(PROJECT_ROOT),
        env={**os.environ, "BIOLAB_DB_PATH": db_path},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await session.call_tool("search_pubmed", arguments)


def _row_count(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    return conn.execute("SELECT count(*) FROM retrievals").fetchone()[0]


@pytest.mark.asyncio
async def test_search_pubmed_live_end_to_end(tmp_path):
    db_path = str(tmp_path / "test.db")
    result = await _call_search_pubmed(
        db_path,
        {"query": "BRCA1 pancreatic cancer", "agent_id": "test:agent", "max_results": 2},
    )

    assert result.isError is False
    payload = json.loads(result.content[0].text)
    assert payload["query_echo"] == "BRCA1 pancreatic cancer"
    assert len(payload["papers"]) == 2
    for paper in payload["papers"]:
        assert paper["pmid"]
        assert paper["retrieval_id"]
        assert paper["title"]
        assert paper["abstract"]

    assert _row_count(db_path) == 2


@pytest.mark.asyncio
async def test_search_pubmed_empty_query_errors_and_writes_nothing(tmp_path):
    db_path = str(tmp_path / "test.db")
    result = await _call_search_pubmed(db_path, {"query": "", "agent_id": "test:agent"})

    assert result.isError is True
    assert _row_count(db_path) == 0


@pytest.mark.asyncio
async def test_search_pubmed_max_results_over_cap_errors_and_writes_nothing(tmp_path):
    db_path = str(tmp_path / "test.db")
    result = await _call_search_pubmed(
        db_path, {"query": "BRCA1", "agent_id": "test:agent", "max_results": 999}
    )

    assert result.isError is True
    assert _row_count(db_path) == 0
