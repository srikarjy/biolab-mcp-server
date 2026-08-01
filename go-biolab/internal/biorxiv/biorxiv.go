package biorxiv

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/srikarjy/biolab-mcp/go-biolab/internal/models"
	"github.com/srikarjy/biolab-mcp/go-biolab/internal/retrieval"
)

const (
	BaseURL = "https://api.biorxiv.org"
	// No free-text search endpoint - only date/category listing
	// Endpoints:
	// GET /details/{server}/{start_date}/{end_date}/{cursor}
	// GET /details/{server}/{interval}/{cursor}
	Timeout = 15 * time.Second
)

type Client struct {
	httpClient *http.Client
}

func NewClient() *Client {
	return &Client{
		httpClient: &http.Client{Timeout: Timeout},
	}
}

type SearchResponse struct {
	Messages []Message `json:"messages"`
	Collection []Preprint `json:"collection"`
}

type Message struct {
	Status       string          `json:"status"`
	Category     string          `json:"category"`
	Interval     string          `json:"interval"`
	Funder       json.RawMessage `json:"funder"`
	Cursor       int             `json:"cursor"`
	Count        int             `json:"count"`
	CountNew     string          `json:"count_new_papers"`
	Total        string          `json:"total"`
}

type Preprint struct {
	Title                 string          `json:"title"`
	Authors               string          `json:"authors"`
	AuthorCorresponding   string          `json:"author_corresponding"`
	AuthorCorrespondingInst string          `json:"author_corresponding_institution"`
	DOI                   string          `json:"doi"`
	Date                  string          `json:"date"`
	Version               string          `json:"version"`
	Type                  string          `json:"type"`
	License               string          `json:"license"`
	Category              string          `json:"category"`
	JATSXML               string          `json:"jatsxml"`
	Abstract              string          `json:"abstract"`
	Funder                json.RawMessage `json:"funder"`
	Published             string          `json:"published"`
	Server                string          `json:"server"`
}

type PreprintDetail struct {
	Preprint
	// Full JATS XML content fetched from jatsxml URL
	FullJATSXML string
}

// List by date range and category (no free-text search)
func (c *Client) ListByDateRange(ctx context.Context, server, startDate, endDate string, maxResults int) ([]Preprint, error) {
	var allPreprints []Preprint
	cursor := 0
	pageSize := 100

	for len(allPreprints) < maxResults {
		endpoint := fmt.Sprintf("%s/details/%s/%s/%s/%d", BaseURL, server, startDate, endDate, cursor)
		req, err := http.NewRequestWithContext(ctx, "GET", endpoint, nil)
		if err != nil {
			return nil, err
		}

		resp, err := c.httpClient.Do(req)
		if err != nil {
			return nil, err
		}

		body, err := io.ReadAll(resp.Body)
		_ = resp.Body.Close()
		if err != nil {
			return nil, err
		}

		var result SearchResponse
		if err := json.Unmarshal(body, &result); err != nil {
			return nil, fmt.Errorf("json unmarshal: %w", err)
		}

		if len(result.Collection) == 0 {
			break
		}

		for _, p := range result.Collection {
			if len(allPreprints) >= maxResults {
				break
			}
			allPreprints = append(allPreprints, p)
		}

		if len(result.Collection) < pageSize {
			break
		}
		cursor += pageSize
	}

	return allPreprints, nil
}

// List by category (latest papers)
func (c *Client) ListByCategory(ctx context.Context, server, category string, maxResults int) ([]Preprint, error) {
	// Use interval format: "last 7 days", "last 30 days", etc.
	endpoint := fmt.Sprintf("%s/details/%s/%s/0", BaseURL, server, category)
	req, err := http.NewRequestWithContext(ctx, "GET", endpoint, nil)
	if err != nil {
		return nil, err
	}

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, err
	}

	body, err := io.ReadAll(resp.Body)
	_ = resp.Body.Close()
	if err != nil {
		return nil, err
	}

	var result SearchResponse
	if err := json.Unmarshal(body, &result); err != nil {
		return nil, fmt.Errorf("json unmarshal: %w", err)
	}

	if len(result.Collection) > maxResults {
		return result.Collection[:maxResults], nil
	}
	return result.Collection, nil
}

func (c *Client) FetchJATSXML(ctx context.Context, jatsURL string) (string, error) {
	req, err := http.NewRequestWithContext(ctx, "GET", jatsURL, nil)
	if err != nil {
		return "", err
	}

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return "", err
	}
	defer func() { _ = resp.Body.Close() }()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", err
	}

	return string(body), nil
}

func (c *Client) ListAndFetch(ctx context.Context, server, category string, maxResults int) ([]models.BioRxivPreprint, error) {
	// bioRxiv API requires date ranges. Use last 30 days by default.
	endDate := time.Now().UTC().Format("2006-01-02")
	startDate := time.Now().UTC().AddDate(0, -1, 0).Format("2006-01-02") // 30 days ago
	
	return c.ListByDateRangeAndCategory(ctx, server, startDate, endDate, category, maxResults)
}

func (c *Client) ListByDateRangeAndCategory(ctx context.Context, server, startDate, endDate, category string, maxResults int) ([]models.BioRxivPreprint, error) {
	preprints, err := c.ListByDateRangeAndCategoryRaw(ctx, server, startDate, endDate, category, maxResults)
	if err != nil {
		return nil, err
	}

	results := make([]models.BioRxivPreprint, 0, len(preprints))
	for _, p := range preprints {
		fullJATSXML, _ := c.FetchJATSXML(ctx, p.JATSXML)
		
		preprint := models.BioRxivPreprint{
			Title:               p.Title,
			Authors:             p.Authors,
			AuthorCorresponding: p.AuthorCorresponding,
			AuthorCorrespondingInst: p.AuthorCorrespondingInst,
			DOI:                 p.DOI,
			Date:                p.Date,
			Version:             p.Version,
			Type:                p.Type,
			License:             p.License,
			Category:            p.Category,
			JATSXML:             p.JATSXML,
			Abstract:            p.Abstract,
			Funder:              string(p.Funder),
			Published:           p.Published,
			Server:              p.Server,
			FullJATSXML:         fullJATSXML,
		}
		results = append(results, preprint)
	}

	return results, nil
}

func (c *Client) ListByDateRangeAndCategoryRaw(ctx context.Context, server, startDate, endDate, category string, maxResults int) ([]Preprint, error) {
	var allPreprints []Preprint
	cursor := 0
	pageSize := 100

	for len(allPreprints) < maxResults {
		endpoint := fmt.Sprintf("%s/details/%s/%s/%s/%d", BaseURL, server, startDate, endDate, cursor)
		req, err := http.NewRequestWithContext(ctx, "GET", endpoint, nil)
		if err != nil {
			return nil, err
		}

		resp, err := c.httpClient.Do(req)
		if err != nil {
			return nil, err
		}

		body, err := io.ReadAll(resp.Body)
		_ = resp.Body.Close()
		if err != nil {
			return nil, err
		}

		var result SearchResponse
		if err := json.Unmarshal(body, &result); err != nil {
			return nil, fmt.Errorf("json unmarshal: %w", err)
		}

		if len(result.Collection) == 0 {
			break
		}

		for _, p := range result.Collection {
			if len(allPreprints) >= maxResults {
				break
			}
			// Filter by category if specified
			if category != "" && category != "all" && !strings.EqualFold(p.Category, category) {
				continue
			}
			allPreprints = append(allPreprints, p)
		}

		if len(result.Collection) < pageSize {
			break
		}
		cursor += pageSize
	}

	return allPreprints, nil
}

func BuildRecord(
	queryText, externalID, agentID, server, category string,
	preprint models.BioRxivPreprint,
) models.RetrievalRecord {
	snapshot := BuildSnapshot(preprint)
	sourceMeta := BuildSourceMetadata(preprint, server, category)
	
	return retrieval.BuildRecord(
		queryText,
		externalID,
		agentID,
		"biorxiv",
		sourceMeta,
		preprint.FullJATSXML,
		snapshot,
	)
}

func BuildSnapshot(preprint models.BioRxivPreprint) models.Snapshot {
	return models.Snapshot{
		Title:       preprint.Title,
		Abstract:    preprint.Abstract,
		Authors:     parseAuthors(preprint.Authors),
		Journal: models.Journal{
			Title:          "bioRxiv",
			PubDate:        preprint.Date,
		},
		PublicationTypes: []string{"preprint", preprint.Type},
		DOI:              preprint.DOI,
	}
}

func BuildSourceMetadata(preprint models.BioRxivPreprint, server, category string) models.SourceMetadata {
	hash := sha256.Sum256([]byte(preprint.FullJATSXML))
	return models.SourceMetadata{
		MedlineStatus: preprint.Category,
		PubStatus:     fmt.Sprintf("%s:%s", server, hex.EncodeToString(hash[:12])),
	}
}

func parseAuthors(authorString string) []models.Author {
	if authorString == "" {
		return nil
	}
	
	// Author string format: "Sinha, A. K.; Lee, C.; Holt, J. C."
	parts := strings.Split(authorString, ";")
	authors := make([]models.Author, 0, len(parts))
	for _, part := range parts {
		part = strings.TrimSpace(part)
		if part == "" {
			continue
		}
		// Try to parse "LastName, Initials" format
		if strings.Contains(part, ",") {
			commaIdx := strings.Index(part, ",")
			lastName := strings.TrimSpace(part[:commaIdx])
			initials := strings.TrimSpace(part[commaIdx+1:])
			authors = append(authors, models.Author{
				LastName: lastName,
				Initials: initials,
			})
		} else {
			authors = append(authors, models.Author{
				LastName: part,
			})
		}
	}
	return authors
}