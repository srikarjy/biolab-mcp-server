---
title: Biolab MCP Server
emoji: 🧬
colorFrom: blue
colorTo: green
sdk: docker
app_port: 8000
---

# Biolab MCP Server

MCP server for auditable biological database queries — every retrieval
logged with full context (PubMed, Europe PMC, ClinicalTrials.gov, bioRxiv/medRxiv).

This Space runs the server over streamable-http at `/mcp`. Storage is a
remote [Turso](https://turso.tech) database (`TURSO_DATABASE_URL` /
`TURSO_AUTH_TOKEN` Space secrets) — this container's own disk is ephemeral
and holds nothing durable.

Source: https://github.com/srikarjy/biolab-mcp-server
