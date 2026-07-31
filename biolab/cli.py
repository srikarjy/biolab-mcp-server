"""Biolab CLI — query and explore the retrieval audit trail."""

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
from rich.syntax import Syntax

from biolab import db, retrieval_log

app = typer.Typer(
    name="biolab",
    help="Biolab MCP Server CLI — query and explore the retrieval audit trail.",
    add_completion=False,
)
console = Console()


def _get_conn(db_path: str):
    return db.connect(db_path)


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query (sent to PubMed verbatim)"),
    agent_id: str = typer.Option("cli:user", "--agent", "-a", help="Agent identifier"),
    max_results: int = typer.Option(5, "--max", "-n", help="Max papers to retrieve (1-50)"),
    db_path: str = typer.Option("biolab.db", "--db", help="Path to SQLite database"),
):
    """Search PubMed and log retrievals to the audit trail."""
    from biolab.pubmed_client import search_and_fetch, paper_to_retrieval_input

    if not 1 <= max_results <= 50:
        console.print("[red]max_results must be between 1 and 50[/red]")
        raise typer.Exit(1)

    conn = _get_conn(db_path)
    console.print(f"[cyan]Searching PubMed:[/cyan] {query}")

    papers = search_and_fetch(query, max_results)
    if not papers:
        console.print("[yellow]No results found[/yellow]")
        return

    console.print(f"[green]Found {len(papers)} papers[/green]")

    for paper in papers:
        retrieval_input = paper_to_retrieval_input(paper)
        record = retrieval_log.write_retrieval(
            conn,
            query_text=query,
            external_id=retrieval_input["external_id"],
            agent_id=agent_id,
            source=retrieval_input["source"],
            source_metadata=retrieval_input["source_metadata"],
            raw_response=retrieval_input["raw_response"],
            snapshot=retrieval_input["snapshot"],
        )
        console.print(f"  [bold]{paper.pmid}[/bold] → retrieval_id: [dim]{record.retrieval_id}[/dim]")
        console.print(f"    Title: {paper.title[:80]}...")


@app.command()
def get(
    retrieval_id: str = typer.Argument(..., help="Retrieval ID to look up"),
    db_path: str = typer.Option("biolab.db", "--db", help="Path to SQLite database"),
    raw: bool = typer.Option(False, "--raw", help="Show raw XML response"),
    snapshot: bool = typer.Option(True, "--snapshot/--no-snapshot", help="Show parsed snapshot"),
):
    """Retrieve a full retrieval record by its retrieval_id."""
    conn = _get_conn(db_path)
    record = retrieval_log.get_retrieval(conn, retrieval_id)

    if record is None:
        console.print(f"[red]No retrieval found for id: {retrieval_id}[/red]")
        raise typer.Exit(1)

    console.print(f"[bold]Retrieval ID:[/bold] {record.retrieval_id}")
    console.print(f"[bold]Source:[/bold] {record.source}")
    console.print(f"[bold]External ID:[/bold] {record.external_id}")
    console.print(f"[bold]Query:[/bold] {record.query_text}")
    console.print(f"[bold]Retrieved at:[/bold] {record.retrieved_at}")
    console.print(f"[bold]Agent:[/bold] {record.agent_id}")

    if snapshot:
        snap = json.loads(record.snapshot)
        console.print("\n[bold cyan]Snapshot:[/bold cyan]")
        console.print(f"  Title: {snap.get('title', 'N/A')}")
        console.print(f"  Abstract: {snap.get('abstract', 'N/A')[:200]}...")
        console.print(f"  DOI: {snap.get('doi', 'N/A')}")
        console.print(f"  Journal: {snap.get('journal', {}).get('title', 'N/A')}")
        console.print(f"  Authors: {len(snap.get('authors', []))} authors")
        console.print(f"  Pub Types: {', '.join(snap.get('publication_types', [])) or 'N/A'}")
        console.print(f"  MeSH Terms: {len(snap.get('mesh_terms', []))} terms")

    source_meta = json.loads(record.source_metadata)
    console.print(f"\n[bold]Source Metadata:[/bold] {json.dumps(source_meta)}")
    console.print(f"[bold]Response Hash:[/bold] {record.response_hash}")

    if raw:
        console.print("\n[bold cyan]Raw XML:[/bold cyan]")
        syntax = Syntax(record.raw_response, "xml", theme="monokai", line_numbers=True)
        console.print(syntax)


@app.command()
def list(
    agent_id: str = typer.Option(None, "--agent", "-a", help="Filter by agent ID"),
    source: str = typer.Option(None, "--source", "-s", help="Filter by source (pubmed, etc.)"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max records to show"),
    db_path: str = typer.Option("biolab.db", "--db", help="Path to SQLite database"),
):
    """List recent retrieval records."""
    conn = _get_conn(db_path)

    where_clauses = []
    params = []
    if agent_id:
        where_clauses.append("agent_id = ?")
        params.append(agent_id)
    if source:
        where_clauses.append("source = ?")
        params.append(source)

    where = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
    params.append(limit)

    rows = conn.execute(
        f"""
        SELECT retrieval_id, source, external_id, query_text, retrieved_at, agent_id
        FROM retrievals {where}
        ORDER BY retrieved_at DESC LIMIT ?
        """,
        params,
    ).fetchall()

    if not rows:
        console.print("[yellow]No records found[/yellow]")
        return

    table = Table(title="Retrieval Records")
    table.add_column("Retrieval ID", style="dim")
    table.add_column("Source")
    table.add_column("External ID")
    table.add_column("Query", max_width=40)
    table.add_column("Retrieved At")
    table.add_column("Agent")

    for row in rows:
        table.add_row(
            row[0][:8] + "...",
            row[1],
            row[2],
            row[3][:40] + ("..." if len(row[3]) > 40 else ""),
            row[4][:19].replace("T", " "),
            row[5],
        )

    console.print(table)


@app.command()
def export(
    output: Path = typer.Argument(..., help="Output JSONL file"),
    agent_id: str = typer.Option(None, "--agent", "-a", help="Filter by agent ID"),
    source: str = typer.Option(None, "--source", "-s", help="Filter by source"),
    db_path: str = typer.Option("biolab.db", "--db", help="Path to SQLite database"),
):
    """Export retrieval records to JSONL for analysis."""
    conn = _get_conn(db_path)

    where_clauses = []
    params = []
    if agent_id:
        where_clauses.append("agent_id = ?")
        params.append(agent_id)
    if source:
        where_clauses.append("source = ?")
        params.append(source)

    where = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    rows = conn.execute(
        f"""
        SELECT retrieval_id, source, external_id, query_text, retrieved_at,
               agent_id, source_metadata, raw_response, snapshot, response_hash
        FROM retrievals {where}
        ORDER BY retrieved_at DESC
        """,
        params,
    ).fetchall()

    with output.open("w") as f:
        for row in rows:
            record = {
                "retrieval_id": row[0],
                "source": row[1],
                "external_id": row[2],
                "query_text": row[3],
                "retrieved_at": row[4],
                "agent_id": row[5],
                "source_metadata": json.loads(row[6]),
                "snapshot": json.loads(row[8]),
                "response_hash": row[9],
            }
            f.write(json.dumps(record) + "\n")

    console.print(f"[green]Exported {len(rows)} records to {output}[/green]")


@app.command()
def demo(
    query: str = typer.Option("BRCA1 pancreatic cancer", "--query", "-q", help="Demo query"),
    agent_id: str = typer.Option("demo:user", "--agent", "-a", help="Agent ID for demo"),
    db_path: str = typer.Option("biolab.db", "--db", help="Path to SQLite database"),
):
    """Run the full demo: search → show retrieval_id → get full record."""
    from biolab.pubmed_client import search_and_fetch, paper_to_retrieval_input

    console.print("[bold cyan]═══ BIOLAB DEMO ═══[/bold cyan]")
    console.print(f"Query: [bold]{query}[/bold]")
    console.print(f"Agent: [bold]{agent_id}[/bold]\n")

    conn = _get_conn(db_path)

    # Step 1: Search
    console.print("[cyan]Step 1: Search PubMed[/cyan]")
    papers = search_and_fetch(query, 2)
    if not papers:
        console.print("[yellow]No results[/yellow]")
        return

    console.print(f"Found [bold]{len(papers)}[/bold] papers\n")

    # Step 2: Store and show retrieval_ids
    console.print("[cyan]Step 2: Store in audit trail (each paper gets a retrieval_id)[/cyan]")
    retrieval_ids = []
    for paper in papers:
        retrieval_input = paper_to_retrieval_input(paper)
        record = retrieval_log.write_retrieval(
            conn,
            query_text=query,
            external_id=retrieval_input["external_id"],
            agent_id=agent_id,
            source=retrieval_input["source"],
            source_metadata=retrieval_input["source_metadata"],
            raw_response=retrieval_input["raw_response"],
            snapshot=retrieval_input["snapshot"],
        )
        retrieval_ids.append(record.retrieval_id)
        console.print(f"  PMID {paper.pmid} → [bold green]{record.retrieval_id}[/bold green]")
        console.print(f"    Title: {paper.title[:70]}...")

    # Step 3: Retrieve full record by retrieval_id
    console.print(f"\n[cyan]Step 3: Retrieve full audit record by retrieval_id[/cyan]")
    for rid in retrieval_ids:
        console.print(f"\n  [bold]Retrieval ID:[/bold] {rid}")
        record = retrieval_log.get_retrieval(conn, rid)
        if record:
            snap = json.loads(record.snapshot)
            console.print(f"  Title: {snap.get('title')}")
            console.print(f"  DOI: {snap.get('doi')}")
            console.print(f"  Journal: {snap.get('journal', {}).get('title')}")
            console.print(f"  Retrieved: {record.retrieved_at}")
            console.print(f"  Source: {record.source}")
            console.print(f"  Hash: {record.response_hash[:16]}...")

    console.print("\n[bold green]✓ Demo complete[/bold green]")
    console.print("Each retrieval_id creates an unforgeable link from conclusion → raw source.")


if __name__ == "__main__":
    app()