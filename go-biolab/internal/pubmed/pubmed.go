package pubmed

import (
	"context"
	"encoding/json"
	"encoding/xml"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/srikarjy/biolab-mcp/go-biolab/internal/models"
)

const (
	ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
	EFETCH_URL  = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
	Timeout     = 10 * time.Second
)

type Client struct {
	httpClient *http.Client
}

func NewClient() *Client {
	return &Client{
		httpClient: &http.Client{Timeout: Timeout},
	}
}

type ESearchResponse struct {
	ESearchResult struct {
		IDList []string `json:"idlist"`
	} `json:"esearchresult"`
}

func (c *Client) Search(ctx context.Context, query string, maxResults int) ([]string, error) {
	params := url.Values{}
	params.Set("db", "pubmed")
	params.Set("term", query)
	params.Set("retmode", "json")
	params.Set("retmax", fmt.Sprintf("%d", maxResults))

	req, err := http.NewRequestWithContext(ctx, "GET", ESEARCH_URL+"?"+params.Encode(), nil)
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

	var result ESearchResponse
	if err := json.Unmarshal(body, &result); err != nil {
		return nil, err
	}

	return result.ESearchResult.IDList, nil
}

type PubmedArticle struct {
	MedlineCitation MedlineCitation `xml:"MedlineCitation"`
	PubmedData      PubmedData      `xml:"PubmedData"`
}

type MedlineCitation struct {
	PMID           string           `xml:"PMID"`
	Status         string           `xml:"Status,attr"`
	Article        Article          `xml:"Article"`
	MeshHeadingList []MeshHeading   `xml:"MeshHeadingList>MeshHeading"`
}

type Article struct {
	ArticleTitle       string        `xml:"ArticleTitle"`
	Abstract           Abstract      `xml:"Abstract"`
	AuthorList         []Author      `xml:"AuthorList>Author"`
	Journal            Journal       `xml:"Journal"`
	PublicationTypeList []string     `xml:"PublicationTypeList>PublicationType"`
	ArticleIdList      []ArticleId   `xml:"ArticleIdList>ArticleId"`
}

type Abstract struct {
	AbstractText []string `xml:"AbstractText"`
}

type Author struct {
	LastName  string `xml:"LastName"`
	ForeName  string `xml:"ForeName"`
	Initials  string `xml:"Initials"`
}

type Journal struct {
	Title           string `xml:"Title"`
	ISOAbbreviation string `xml:"ISOAbbreviation"`
	ISSN            string `xml:"ISSN"`
	PubDate         string `xml:"PubDate"`
}

type ArticleId struct {
	IdType string `xml:"IdType,attr"`
	Value  string `xml:",chardata"`
}

type MeshHeading struct {
	DescriptorName string `xml:"DescriptorName"`
}

type PubmedData struct {
	PublicationStatus string      `xml:"PublicationStatus"`
	ArticleIdList     []ArticleId `xml:"ArticleIdList>ArticleId"`
}

type EFetchResponse struct {
	PubmedArticles []PubmedArticle `xml:"PubmedArticle"`
}

func (c *Client) Fetch(ctx context.Context, pmids []string) ([]models.PubMedPaper, error) {
	if len(pmids) == 0 {
		return []models.PubMedPaper{}, nil
	}

	params := url.Values{}
	params.Set("db", "pubmed")
	params.Set("id", strings.Join(pmids, ","))
	params.Set("rettype", "abstract")
	params.Set("retmode", "xml")

	req, err := http.NewRequestWithContext(ctx, "GET", EFETCH_URL+"?"+params.Encode(), nil)
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

	var result EFetchResponse
	if err := xml.Unmarshal(body, &result); err != nil {
		return nil, fmt.Errorf("xml unmarshal: %w", err)
	}

	papers := make([]models.PubMedPaper, 0, len(result.PubmedArticles))
	for _, article := range result.PubmedArticles {
		rawXML, _ := xml.Marshal(article)
		paper := models.PubMedPaper{
			PMID:              article.MedlineCitation.PMID,
			Title:             fullText(article.MedlineCitation.Article.ArticleTitle),
			Abstract:          strings.Join(article.MedlineCitation.Article.Abstract.AbstractText, " "),
			MedlineStatus:     article.MedlineCitation.Status,
			PubStatus:         article.PubmedData.PublicationStatus,
			RawXML:            string(rawXML),
			Authors:           convertAuthors(article.MedlineCitation.Article.AuthorList),
			Journal:           convertJournal(article.MedlineCitation.Article.Journal),
			PublicationTypes:  article.MedlineCitation.Article.PublicationTypeList,
			MeshTerms:         convertMeshTerms(article.MedlineCitation.MeshHeadingList),
			DOI:               extractDOI(article.PubmedData.ArticleIdList),
		}
		papers = append(papers, paper)
	}

	return papers, nil
}

func fullText(s string) string {
	return strings.TrimSpace(s)
}

func convertAuthors(authors []Author) []models.Author {
	result := make([]models.Author, 0, len(authors))
	for _, a := range authors {
		if a.LastName != "" || a.ForeName != "" || a.Initials != "" {
			result = append(result, models.Author{
				LastName: a.LastName,
				ForeName: a.ForeName,
				Initials: a.Initials,
			})
		}
	}
	return result
}

func convertJournal(j Journal) models.Journal {
	return models.Journal{
		Title:           j.Title,
		ISOAbbreviation: j.ISOAbbreviation,
		ISSN:            j.ISSN,
		PubDate:         j.PubDate,
	}
}

func convertMeshTerms(mesh []MeshHeading) []string {
	result := make([]string, 0, len(mesh))
	for _, m := range mesh {
		if m.DescriptorName != "" {
			result = append(result, m.DescriptorName)
		}
	}
	return result
}

func extractDOI(ids []ArticleId) string {
	for _, id := range ids {
		if id.IdType == "doi" {
			return id.Value
		}
	}
	return ""
}

func (c *Client) SearchAndFetch(ctx context.Context, query string, maxResults int) ([]models.PubMedPaper, error) {
	pmids, err := c.Search(ctx, query, maxResults)
	if err != nil {
		return nil, err
	}
	return c.Fetch(ctx, pmids)
}