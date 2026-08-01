package europepmc

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/xml"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/srikarjy/biolab-mcp/go-biolab/internal/models"
	"github.com/srikarjy/biolab-mcp/go-biolab/internal/retrieval"
)

const (
	BaseURL   = "https://www.ebi.ac.uk/europepmc/webservices/rest"
	SearchURL = BaseURL + "/search"
	FetchURL  = BaseURL + "/{id}/fullTextXML"
	Timeout   = 15 * time.Second
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
	XMLName   xml.Name `xml:"responseWrapper"`
	HitCount  int      `xml:"hitCount"`
	Request   struct {
		QueryString string `xml:"queryString"`
		ResultType  string `xml:"resultType"`
	} `xml:"request"`
	Results []SearchResult `xml:"resultList>result"`
}

type SearchResult struct {
	ID              string `xml:"id"`
	Source          string `xml:"source"`
	PMID            string `xml:"pmid"`
	DOI             string `xml:"doi"`
	Title           string `xml:"title"`
	AuthorString    string `xml:"authorString"`
	JournalTitle    string `xml:"journalTitle"`
	JournalISOAbbr  string `xml:"journalISOAbbr"`
	ISSN            string `xml:"issn"`
	Volume          string `xml:"volume"`
	Issue           string `xml:"issue"`
	PageInfo        string `xml:"pageInfo"`
	PubYear         string `xml:"pubYear"`
	PubType         string `xml:"pubType"`
	IsOpenAccess    string `xml:"isOpenAccess"`
	AbstractText    string `xml:"abstractText"`
	Affiliation     string `xml:"affiliation"`
	FullTextURLList FullTextURLList `xml:"fullTextUrlList>fullTextUrl"`
}

type FullTextURLList struct {
	URL       string `xml:"url"`
	DocStyle  string `xml:"docStyle"`
	Site      string `xml:"site"`
}

func (c *Client) Search(ctx context.Context, query string, maxResults int) ([]SearchResult, error) {
	params := url.Values{}
	params.Set("query", query)
	params.Set("format", "xml")
	params.Set("pageSize", fmt.Sprintf("%d", maxResults))
	params.Set("resultType", "lite")

	req, err := http.NewRequestWithContext(ctx, "GET", SearchURL+"?"+params.Encode(), nil)
	if err != nil {
		return nil, err
	}

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer func() { _ = resp.Body.Close() }()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}

	var result SearchResponse
	if err := xml.Unmarshal(body, &result); err != nil {
		return nil, fmt.Errorf("xml unmarshal: %w", err)
	}

	return result.Results, nil
}

func (c *Client) FetchFullText(ctx context.Context, id, source string) (string, error) {
	fetchURL := strings.Replace(FetchURL, "{id}", id, 1)
	params := url.Values{}
	params.Set("format", "xml")

	req, err := http.NewRequestWithContext(ctx, "GET", fetchURL+"?"+params.Encode(), nil)
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

func (c *Client) SearchAndFetch(ctx context.Context, query string, maxResults int) ([]models.EuropePMCArticle, error) {
	results, err := c.Search(ctx, query, maxResults)
	if err != nil {
		return nil, err
	}

	articles := make([]models.EuropePMCArticle, 0, len(results))
	for _, r := range results {
		fullTextXML, _ := c.FetchFullText(ctx, r.ID, r.Source)
		
		article := models.EuropePMCArticle{
			ID:              r.ID,
			Source:          r.Source,
			PMID:            r.PMID,
			DOI:             r.DOI,
			Title:           r.Title,
			AuthorString:    r.AuthorString,
			JournalTitle:    r.JournalTitle,
			JournalISOAbbr:  r.JournalISOAbbr,
			ISSN:            r.ISSN,
			Volume:          r.Volume,
			Issue:           r.Issue,
			PageInfo:        r.PageInfo,
			PubYear:         r.PubYear,
			PubType:         r.PubType,
			IsOpenAccess:    r.IsOpenAccess == "Y",
			AbstractText:    r.AbstractText,
			Affiliation:     r.Affiliation,
			FullTextXML:     fullTextXML,
		}
		articles = append(articles, article)
	}

	return articles, nil
}

func BuildRecord(
	queryText, externalID, agentID, source string,
	article models.EuropePMCArticle,
) models.RetrievalRecord {
	snapshot := BuildSnapshot(article)
	sourceMeta := BuildSourceMetadata(article)
	
	return retrieval.BuildRecord(
		queryText,
		externalID,
		agentID,
		source,
		sourceMeta,
		article.FullTextXML,
		snapshot,
	)
}

func BuildSnapshot(article models.EuropePMCArticle) models.Snapshot {
	return models.Snapshot{
		Title:       article.Title,
		Abstract:    article.AbstractText,
		Authors:     parseAuthors(article.AuthorString),
		Journal: models.Journal{
			Title:           article.JournalTitle,
			ISOAbbreviation: article.JournalISOAbbr,
			ISSN:            article.ISSN,
			PubDate:         article.PubYear,
		},
		PublicationTypes: parsePubTypes(article.PubType),
		DOI:              article.DOI,
	}
}

func BuildSourceMetadata(article models.EuropePMCArticle) models.SourceMetadata {
	hash := sha256.Sum256([]byte(article.FullTextXML))
	return models.SourceMetadata{
		MedlineStatus: article.Source,
		PubStatus:     hex.EncodeToString(hash[:16]),
	}
}

func parseAuthors(authorString string) []models.Author {
	if authorString == "" {
		return nil
	}
	
	// Author string format: "Smith J, Jones K, Brown L"
	parts := strings.Split(authorString, ", ")
	authors := make([]models.Author, 0, len(parts))
	for _, part := range parts {
		part = strings.TrimSpace(part)
		if part == "" {
			continue
		}
		// Try to parse "LastName Initials" format
		fields := strings.Fields(part)
		if len(fields) >= 2 {
			lastName := fields[0]
			initials := strings.Join(fields[1:], " ")
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

func parsePubTypes(pubType string) []string {
	if pubType == "" {
		return nil
	}
	// Split by semicolon and comma
	parts := strings.Split(pubType, ";")
	result := make([]string, 0)
	for _, p := range parts {
		subparts := strings.Split(p, ",")
		for _, sp := range subparts {
			sp = strings.TrimSpace(sp)
			if sp != "" {
				result = append(result, sp)
			}
		}
	}
	return result
}