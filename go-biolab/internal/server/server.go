package server

import (
	"context"
	"encoding/json"
	"fmt"
	"os"

	"github.com/jmoiron/sqlx"
	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"
	"github.com/srikarjy/biolab-mcp/go-biolab/internal/biorxiv"
	"github.com/srikarjy/biolab-mcp/go-biolab/internal/clinicaltrials"
	"github.com/srikarjy/biolab-mcp/go-biolab/internal/db"
	"github.com/srikarjy/biolab-mcp/go-biolab/internal/europepmc"
	"github.com/srikarjy/biolab-mcp/go-biolab/internal/models"
	"github.com/srikarjy/biolab-mcp/go-biolab/internal/pubmed"
	"github.com/srikarjy/biolab-mcp/go-biolab/internal/retrieval"
)

const MaxResultsCap = 50

type App struct {
	db             *sqlx.DB
	pubmed         *pubmed.Client
	europepmc      *europepmc.Client
	clinicaltrials *clinicaltrials.Client
	biorxiv        *biorxiv.Client
	retrievalLog   *retrieval.Log
	mcpServer      *server.MCPServer
}

func NewApp(dbPath string) (*App, error) {
	database, err := db.Connect(dbPath)
	if err != nil {
		return nil, err
	}

	app := &App{
		db:              database,
		pubmed:          pubmed.NewClient(),
		europepmc:       europepmc.NewClient(),
		clinicaltrials:  clinicaltrials.NewClient(),
		biorxiv:         biorxiv.NewClient(),
		retrievalLog:    retrieval.NewLog(database),
	}

	app.mcpServer = server.NewMCPServer(
		"biolab",
		"0.2.0",
		server.WithToolCapabilities(true),
	)

	app.registerTools()
	return app, nil
}

func (a *App) registerTools() {
	searchPubMedTool := mcp.NewTool("search_pubmed",
		mcp.WithDescription("Search PubMed and log every retrieved paper to the audit trail"),
		mcp.WithString("query",
			mcp.Required(),
			mcp.Description("Exact search string, sent to PubMed verbatim — no normalization"),
		),
		mcp.WithString("agent_id",
			mcp.Required(),
			mcp.Description("Which agent is asking, e.g. 'aletheia:advocate'"),
		),
		mcp.WithNumber("max_results",
			mcp.Description("How many papers to retrieve (default 5, max 50)"),
		),
	)
	a.mcpServer.AddTool(searchPubMedTool, a.handleSearchPubMed)

	searchEuropePMCTool := mcp.NewTool("search_europepmc",
		mcp.WithDescription("Search Europe PMC and log every retrieved paper to the audit trail"),
		mcp.WithString("query",
			mcp.Required(),
			mcp.Description("Exact search string, sent to Europe PMC verbatim — no normalization"),
		),
		mcp.WithString("agent_id",
			mcp.Required(),
			mcp.Description("Which agent is asking, e.g. 'aletheia:advocate'"),
		),
		mcp.WithNumber("max_results",
			mcp.Description("How many papers to retrieve (default 5, max 50)"),
		),
	)
	a.mcpServer.AddTool(searchEuropePMCTool, a.handleSearchEuropePMC)

searchClinicalTrialsTool := mcp.NewTool("search_clinicaltrials",
		mcp.WithDescription("Search ClinicalTrials.gov and log every retrieved study to the audit trail"),
		mcp.WithString("query",
			mcp.Required(),
			mcp.Description("Exact search string (condition/disease), sent to ClinicalTrials.gov verbatim"),
		),
		mcp.WithString("agent_id",
			mcp.Required(),
			mcp.Description("Which agent is asking, e.g. 'aletheia:advocate'"),
		),
		mcp.WithNumber("max_results",
			mcp.Description("How many studies to retrieve (default 5, max 50)"),
		),
	)
	a.mcpServer.AddTool(searchClinicalTrialsTool, a.handleSearchClinicalTrials)

	searchBioRxivTool := mcp.NewTool("search_biorxiv",
		mcp.WithDescription("List bioRxiv/medRxiv preprints by category (no free-text search — API limitation)"),
		mcp.WithString("category",
			mcp.Required(),
			mcp.Description("Category: all, neuroscience, bioinformatics, genetics, etc. (see bioRxiv API docs)"),
		),
		mcp.WithString("server",
			mcp.Description("Server: biorxiv or medrxiv (default: biorxiv)"),
		),
		mcp.WithString("agent_id",
			mcp.Required(),
			mcp.Description("Which agent is asking, e.g. 'aletheia:advocate'"),
		),
		mcp.WithNumber("max_results",
			mcp.Description("How many preprints to retrieve (default 5, max 50)"),
		),
	)
	a.mcpServer.AddTool(searchBioRxivTool, a.handleSearchBioRxiv)

	getTool := mcp.NewTool("get_retrieval",
		mcp.WithDescription("Retrieve a full retrieval record by its retrieval_id"),
		mcp.WithString("retrieval_id",
			mcp.Required(),
			mcp.Description("The UUID returned by search_pubmed, search_europepmc, or search_clinicaltrials"),
		),
	)
	a.mcpServer.AddTool(getTool, a.handleGetRetrieval)
}

func getString(args map[string]interface{}, key string) string {
	if v, ok := args[key]; ok {
		if s, ok := v.(string); ok {
			return s
		}
	}
	return ""
}

func getInt(args map[string]interface{}, key string, def int) int {
	if v, ok := args[key]; ok {
		switch val := v.(type) {
		case float64:
			return int(val)
		case int:
			return val
		case int64:
			return int(val)
		}
	}
	return def
}

func (a *App) handleSearchPubMed(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	args := request.Params.Arguments
	query := getString(args, "query")
	agentID := getString(args, "agent_id")
	maxResults := getInt(args, "max_results", 5)

	if query == "" {
		return mcp.NewToolResultError("query must not be empty"), nil
	}
	if agentID == "" {
		return mcp.NewToolResultError("agent_id must not be empty"), nil
	}
	if maxResults < 1 || maxResults > MaxResultsCap {
		return mcp.NewToolResultError(fmt.Sprintf("max_results must be between 1 and %d", MaxResultsCap)), nil
	}

	papers, err := a.pubmed.SearchAndFetch(ctx, query, maxResults)
	if err != nil {
		return mcp.NewToolResultError(fmt.Sprintf("PubMed search failed: %v", err)), nil
	}
	if len(papers) == 0 {
		return mcp.NewToolResultError(fmt.Sprintf("no PubMed results for query: %s", query)), nil
	}

	results := make([]map[string]interface{}, 0, len(papers))
	for _, paper := range papers {
		snapshot := retrieval.BuildSnapshotFromPubMed(paper)
		sourceMeta := retrieval.BuildSourceMetadata(paper)

		record := retrieval.BuildRecord(
			query,
			paper.PMID,
			agentID,
			"pubmed",
			sourceMeta,
			paper.RawXML,
			snapshot,
		)

		if err := a.retrievalLog.Write(ctx, record); err != nil {
			return mcp.NewToolResultError(fmt.Sprintf("DB write failed: %v", err)), nil
		}

		results = append(results, map[string]interface{}{
			"pmid":          paper.PMID,
			"retrieval_id":  record.RetrievalID,
			"title":         paper.Title,
			"abstract":      paper.Abstract,
		})
	}

	output := map[string]interface{}{
		"query_echo": query,
		"papers":     results,
	}
	jsonOut, _ := json.Marshal(output)
	return mcp.NewToolResultText(string(jsonOut)), nil
}

func (a *App) handleSearchEuropePMC(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	args := request.Params.Arguments
	query := getString(args, "query")
	agentID := getString(args, "agent_id")
	maxResults := getInt(args, "max_results", 5)

	if query == "" {
		return mcp.NewToolResultError("query must not be empty"), nil
	}
	if agentID == "" {
		return mcp.NewToolResultError("agent_id must not be empty"), nil
	}
	if maxResults < 1 || maxResults > MaxResultsCap {
		return mcp.NewToolResultError(fmt.Sprintf("max_results must be between 1 and %d", MaxResultsCap)), nil
	}

	articles, err := a.europepmc.SearchAndFetch(ctx, query, maxResults)
	if err != nil {
		return mcp.NewToolResultError(fmt.Sprintf("Europe PMC search failed: %v", err)), nil
	}
	if len(articles) == 0 {
		return mcp.NewToolResultError(fmt.Sprintf("no Europe PMC results for query: %s", query)), nil
	}

	results := make([]map[string]interface{}, 0, len(articles))
	for _, article := range articles {
		externalID := article.PMID
		if externalID == "" {
			externalID = article.DOI
		}
		if externalID == "" {
			externalID = article.ID
		}

		record := europepmc.BuildRecord(query, externalID, agentID, "europepmc", article)

		if err := a.retrievalLog.Write(ctx, record); err != nil {
			return mcp.NewToolResultError(fmt.Sprintf("DB write failed: %v", err)), nil
		}

		results = append(results, map[string]interface{}{
			"id":            article.ID,
			"retrieval_id":  record.RetrievalID,
			"title":         article.Title,
			"abstract":      article.AbstractText,
		})
	}

	output := map[string]interface{}{
		"query_echo": query,
		"papers":     results,
	}
	jsonOut, _ := json.Marshal(output)
	return mcp.NewToolResultText(string(jsonOut)), nil
}

func (a *App) handleSearchClinicalTrials(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	args := request.Params.Arguments
	query := getString(args, "query")
	agentID := getString(args, "agent_id")
	maxResults := getInt(args, "max_results", 5)

	if query == "" {
		return mcp.NewToolResultError("query must not be empty"), nil
	}
	if agentID == "" {
		return mcp.NewToolResultError("agent_id must not be empty"), nil
	}
	if maxResults < 1 || maxResults > MaxResultsCap {
		return mcp.NewToolResultError(fmt.Sprintf("max_results must be between 1 and %d", MaxResultsCap)), nil
	}

	studies, err := a.clinicaltrials.SearchAndFetch(ctx, query, maxResults)
	if err != nil {
		return mcp.NewToolResultError(fmt.Sprintf("ClinicalTrials.gov search failed: %v", err)), nil
	}
	if len(studies) == 0 {
		return mcp.NewToolResultError(fmt.Sprintf("no ClinicalTrials.gov results for query: %s", query)), nil
	}

	results := make([]map[string]interface{}, 0, len(studies))
	for _, study := range studies {
		externalID := study.NCTId

		record := clinicaltrials.BuildRecord(query, externalID, agentID, study)

		if err := a.retrievalLog.Write(ctx, record); err != nil {
			return mcp.NewToolResultError(fmt.Sprintf("DB write failed: %v", err)), nil
		}

		results = append(results, map[string]interface{}{
			"nct_id":        study.NCTId,
			"retrieval_id":  record.RetrievalID,
			"title":         study.BriefTitle,
			"abstract":      study.BriefSummary,
		})
	}

	output := map[string]interface{}{
		"query_echo": query,
		"papers":     results,
	}
	jsonOut, _ := json.Marshal(output)
	return mcp.NewToolResultText(string(jsonOut)), nil
}

func (a *App) handleSearchBioRxiv(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	args := request.Params.Arguments
	category := getString(args, "category")
	server := getString(args, "server")
	agentID := getString(args, "agent_id")
	maxResults := getInt(args, "max_results", 5)

	if category == "" {
		return mcp.NewToolResultError("category must not be empty"), nil
	}
	if server == "" {
		server = "biorxiv"
	}
	if agentID == "" {
		return mcp.NewToolResultError("agent_id must not be empty"), nil
	}
	if maxResults < 1 || maxResults > MaxResultsCap {
		return mcp.NewToolResultError(fmt.Sprintf("max_results must be between 1 and %d", MaxResultsCap)), nil
	}

	preprints, err := a.biorxiv.ListAndFetch(ctx, server, category, maxResults)
	if err != nil {
		return mcp.NewToolResultError(fmt.Sprintf("bioRxiv search failed: %v", err)), nil
	}
	if len(preprints) == 0 {
		return mcp.NewToolResultError(fmt.Sprintf("no bioRxiv results for category: %s", category)), nil
	}

	results := make([]map[string]interface{}, 0, len(preprints))
	for _, preprint := range preprints {
		externalID := preprint.DOI
		if externalID == "" {
			externalID = preprint.Date + "-" + preprint.Category
		}

		record := biorxiv.BuildRecord(
			fmt.Sprintf("category:%s", category),
			externalID,
			agentID,
			server,
			category,
			preprint,
		)

		if err := a.retrievalLog.Write(ctx, record); err != nil {
			return mcp.NewToolResultError(fmt.Sprintf("DB write failed: %v", err)), nil
		}

		results = append(results, map[string]interface{}{
			"doi":           preprint.DOI,
			"retrieval_id":  record.RetrievalID,
			"title":         preprint.Title,
			"abstract":      preprint.Abstract,
		})
	}

	output := map[string]interface{}{
		"query_echo": fmt.Sprintf("category:%s", category),
		"papers":     results,
	}
	jsonOut, _ := json.Marshal(output)
	return mcp.NewToolResultText(string(jsonOut)), nil
}

func (a *App) handleGetRetrieval(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	args := request.Params.Arguments
	retrievalID := getString(args, "retrieval_id")
	if retrievalID == "" {
		return mcp.NewToolResultError("retrieval_id must not be empty"), nil
	}

	record, err := a.retrievalLog.Get(ctx, retrievalID)
	if err != nil {
		return mcp.NewToolResultError(fmt.Sprintf("DB query failed: %v", err)), nil
	}
	if record == nil {
		return mcp.NewToolResultError(fmt.Sprintf("no retrieval found for id: %s", retrievalID)), nil
	}

	var sourceMeta models.SourceMetadata
	var snapshot models.Snapshot
	if err := json.Unmarshal([]byte(record.SourceMetadata), &sourceMeta); err != nil {
		return mcp.NewToolResultError(fmt.Sprintf("parsing source metadata: %v", err)), nil
	}
	if err := json.Unmarshal([]byte(record.Snapshot), &snapshot); err != nil {
		return mcp.NewToolResultError(fmt.Sprintf("parsing snapshot: %v", err)), nil
	}

	output := map[string]interface{}{
		"retrieval_id":    record.RetrievalID,
		"source":          record.Source,
		"external_id":     record.ExternalID,
		"query_text":      record.QueryText,
		"retrieved_at":    record.RetrievedAt,
		"agent_id":        record.AgentID,
		"source_metadata": sourceMeta,
		"raw_response":    record.RawResponse,
		"snapshot":        snapshot,
		"response_hash":   record.ResponseHash,
	}
	jsonOut, _ := json.Marshal(output)
	return mcp.NewToolResultText(string(jsonOut)), nil
}

func (a *App) Run() error {
	return server.ServeStdio(a.mcpServer)
}

func (a *App) Close() error {
	return a.retrievalLog.Close()
}

func Main() {
	dbPath := os.Getenv("BIOLAB_DB_PATH")
	if dbPath == "" {
		dbPath = "biolab.db"
	}

	app, err := NewApp(dbPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Failed to initialize: %v\n", err)
		os.Exit(1)
	}
	defer func() { _ = app.Close() }()

	if err := app.Run(); err != nil {
		fmt.Fprintf(os.Stderr, "Server error: %v\n", err)
		os.Exit(1)
	}
}