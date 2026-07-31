package clinicaltrials

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"time"

	"github.com/srikarjy/biolab-mcp/go-biolab/internal/models"
	"github.com/srikarjy/biolab-mcp/go-biolab/internal/retrieval"
)

const (
	BaseURL   = "https://clinicaltrials.gov/api/v2"
	SearchURL = BaseURL + "/studies"
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
	Studies []Study `json:"studies"`
}

type Study struct {
	ProtocolSection ProtocolSection `json:"protocolSection"`
}

type ProtocolSection struct {
	IdentificationModule IdentificationModule `json:"identificationModule"`
	StatusModule         StatusModule         `json:"statusModule"`
	DescriptionModule    DescriptionModule    `json:"descriptionModule"`
	ConditionsModule     ConditionsModule     `json:"conditionsModule"`
	DesignModule         DesignModule         `json:"designModule"`
	ArmsInterventionsModule ArmsInterventionsModule `json:"armsInterventionsModule"`
	EligibilityModule    EligibilityModule    `json:"eligibilityModule"`
	ContactsLocationsModule ContactsLocationsModule `json:"contactsLocationsModule"`
}

type IdentificationModule struct {
	NCTId          string   `json:"nctId"`
	OrgStudyIdInfo OrgStudyIdInfo `json:"orgStudyIdInfo"`
	Organization   OrgInfo  `json:"organization"`
	BriefTitle     string   `json:"briefTitle"`
	OfficialTitle  string   `json:"officialTitle"`
}

type OrgStudyIdInfo struct {
	ID string `json:"id"`
}

type OrgInfo struct {
	FullName string `json:"fullName"`
	Class    string `json:"class"`
}

type StatusModule struct {
	StatusVerifiedDate string `json:"statusVerifiedDate"`
	OverallStatus      string `json:"overallStatus"`
	ExpandedAccessInfo ExpandedAccessInfo `json:"expandedAccessInfo"`
	StartDateStruct    DateStruct `json:"startDateStruct"`
	PrimaryCompletionDateStruct DateStruct `json:"primaryCompletionDateStruct"`
	CompletionDateStruct DateStruct `json:"completionDateStruct"`
	StudyFirstSubmitDate string `json:"studyFirstSubmitDate"`
	StudyFirstSubmitQCDate string `json:"studyFirstSubmitQcDate"`
	StudyFirstPostDateStruct DateStruct `json:"studyFirstPostDateStruct"`
	LastUpdateSubmitDate string `json:"lastUpdateSubmitDate"`
	LastUpdatePostDateStruct DateStruct `json:"lastUpdatePostDateStruct"`
}

type ExpandedAccessInfo struct {
	HasExpandedAccess bool `json:"hasExpandedAccess"`
}

type DateStruct struct {
	Date string `json:"date"`
	Type string `json:"type"`
}

type DescriptionModule struct {
	BriefSummary       string `json:"briefSummary"`
	DetailedDescription string `json:"detailedDescription"`
}

type ConditionsModule struct {
	Conditions []string `json:"conditions"`
	Keywords   []string `json:"keywords"`
}

type DesignModule struct {
	StudyType     string `json:"studyType"`
	Phases        []string `json:"phases"`
	DesignInfo    DesignInfo `json:"designInfo"`
	EnrollmentInfo EnrollmentInfo `json:"enrollmentInfo"`
}

type DesignInfo struct {
	Allocation        string `json:"allocation"`
	InterventionModel string `json:"interventionModel"`
	PrimaryPurpose    string `json:"primaryPurpose"`
	MaskingInfo       MaskingInfo `json:"maskingInfo"`
}

type MaskingInfo struct {
	Masking string `json:"masking"`
}

type EnrollmentInfo struct {
	Count int    `json:"count"`
	Type  string `json:"type"`
}

type ArmsInterventionsModule struct {
	ArmGroups []ArmGroup `json:"armGroups"`
	Interventions []Intervention `json:"interventions"`
}

type ArmGroup struct {
	Label       string `json:"label"`
	Type        string `json:"type"`
	Description string `json:"description"`
}

type Intervention struct {
	Type        string `json:"type"`
	Name        string `json:"name"`
	Description string `json:"description"`
}

type EligibilityModule struct {
	Criteria            string   `json:"criteria"`
	HealthyVolunteers   bool     `json:"healthyVolunteers"`
	Sex                 string   `json:"sex"`
	GenderBased         string   `json:"genderBased"`
	MinimumAge          string   `json:"minimumAge"`
	MaximumAge          string   `json:"maximumAge"`
	StdAges             []string `json:"stdAges"`
}

type ContactsLocationsModule struct {
	Locations []Location `json:"locations"`
}

type Location struct {
	Facility string `json:"facility"`
	Status   string `json:"status"`
	City     string `json:"city"`
	State    string `json:"state"`
	Zip      string `json:"zip"`
	Country  string `json:"country"`
	Contacts []Contact `json:"contacts"`
}

type Contact struct {
	Name  string `json:"name"`
	Role  string `json:"role"`
	Phone string `json:"phone"`
	Email string `json:"email"`
}

func (c *Client) Search(ctx context.Context, query string, maxResults int) ([]Study, error) {
	params := url.Values{}
	params.Set("query.cond", query)
	params.Set("pageSize", fmt.Sprintf("%d", maxResults))
	params.Set("format", "json")

	req, err := http.NewRequestWithContext(ctx, "GET", SearchURL+"?"+params.Encode(), nil)
	if err != nil {
		return nil, err
	}

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}

	var result SearchResponse
	if err := json.Unmarshal(body, &result); err != nil {
		return nil, fmt.Errorf("json unmarshal: %w", err)
	}

	return result.Studies, nil
}

func (c *Client) FetchStudy(ctx context.Context, nctID string) (string, error) {
	fetchURL := SearchURL + "/" + nctID
	params := url.Values{}
	params.Set("format", "json")

	req, err := http.NewRequestWithContext(ctx, "GET", fetchURL+"?"+params.Encode(), nil)
	if err != nil {
		return "", err
	}

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", err
	}

	return string(body), nil
}

func (c *Client) SearchAndFetch(ctx context.Context, query string, maxResults int) ([]models.ClinicalTrialStudy, error) {
	studies, err := c.Search(ctx, query, maxResults)
	if err != nil {
		return nil, err
	}

	results := make([]models.ClinicalTrialStudy, 0, len(studies))
	for _, s := range studies {
		fullJSON, _ := c.FetchStudy(ctx, s.ProtocolSection.IdentificationModule.NCTId)
		
		phase := joinPhases(s.ProtocolSection.DesignModule.Phases)
		studyType := s.ProtocolSection.DesignModule.StudyType
		
		study := models.ClinicalTrialStudy{
			NCTId:           s.ProtocolSection.IdentificationModule.NCTId,
			BriefTitle:      s.ProtocolSection.IdentificationModule.BriefTitle,
			OfficialTitle:   s.ProtocolSection.IdentificationModule.OfficialTitle,
			Organization:    s.ProtocolSection.IdentificationModule.Organization.FullName,
			OverallStatus:   s.ProtocolSection.StatusModule.OverallStatus,
			StartDate:       s.ProtocolSection.StatusModule.StartDateStruct.Date,
			CompletionDate:  s.ProtocolSection.StatusModule.CompletionDateStruct.Date,
			StudyType:       studyType,
			Phase:           phase,
			BriefSummary:    s.ProtocolSection.DescriptionModule.BriefSummary,
			DetailedDesc:    s.ProtocolSection.DescriptionModule.DetailedDescription,
			Conditions:      s.ProtocolSection.ConditionsModule.Conditions,
			Keywords:        s.ProtocolSection.ConditionsModule.Keywords,
			Interventions:   convertInterventions(s.ProtocolSection.ArmsInterventionsModule.Interventions),
			Design:          convertDesign(s.ProtocolSection.DesignModule),
			ArmGroups:       convertArmGroups(s.ProtocolSection.ArmsInterventionsModule.ArmGroups),
			Eligibility:     convertEligibility(s.ProtocolSection.EligibilityModule),
			Locations:       convertLocations(s.ProtocolSection.ContactsLocationsModule.Locations),
			FullJSON:        fullJSON,
		}
		results = append(results, study)
	}

	return results, nil
}

func joinPhases(phases []string) string {
	if len(phases) == 0 {
		return ""
	}
	result := ""
	for i, p := range phases {
		if i > 0 {
			result += ", "
		}
		result += p
	}
	return result
}

func convertInterventions(interventions []Intervention) []models.Intervention {
	result := make([]models.Intervention, 0, len(interventions))
	for _, i := range interventions {
		result = append(result, models.Intervention{
			Type:        i.Type,
			Name:        i.Name,
			Description: i.Description,
		})
	}
	return result
}

func convertDesign(d DesignModule) models.Design {
	return models.Design{
		StudyType:        d.StudyType,
		Allocation:       d.DesignInfo.Allocation,
		InterventionModel: d.DesignInfo.InterventionModel,
		PrimaryPurpose:   d.DesignInfo.PrimaryPurpose,
		Masking:          d.DesignInfo.MaskingInfo.Masking,
	}
}

func convertArmGroups(groups []ArmGroup) []models.ArmGroup {
	result := make([]models.ArmGroup, 0, len(groups))
	for _, g := range groups {
		result = append(result, models.ArmGroup{
			Label:       g.Label,
			Type:        g.Type,
			Description: g.Description,
		})
	}
	return result
}

func convertEligibility(e EligibilityModule) models.Eligibility {
	hv := "false"
	if e.HealthyVolunteers {
		hv = "true"
	}
	return models.Eligibility{
		Criteria:          e.Criteria,
		HealthyVolunteers: hv,
		Sex:               e.Sex,
		GenderBased:       e.GenderBased,
		MinimumAge:        e.MinimumAge,
		MaximumAge:        e.MaximumAge,
		StdAges:           e.StdAges,
	}
}

func convertLocations(locations []Location) []models.Location {
	result := make([]models.Location, 0, len(locations))
	for _, l := range locations {
		result = append(result, models.Location{
			Facility: l.Facility,
			City:     l.City,
			State:    l.State,
			Country:  l.Country,
		})
	}
	return result
}

func BuildRecord(
	queryText, externalID, agentID string,
	study models.ClinicalTrialStudy,
) models.RetrievalRecord {
	snapshot := BuildSnapshot(study)
	sourceMeta := BuildSourceMetadata(study)
	
	return retrieval.BuildRecord(
		queryText,
		externalID,
		agentID,
		"clinicaltrials",
		sourceMeta,
		study.FullJSON,
		snapshot,
	)
}

func BuildSnapshot(study models.ClinicalTrialStudy) models.Snapshot {
	return models.Snapshot{
		Title:       study.BriefTitle,
		Abstract:    study.BriefSummary,
		Authors:     []models.Author{{LastName: study.Organization}},
		Journal: models.Journal{
			Title:          "ClinicalTrials.gov",
			PubDate:        study.StartDate,
		},
		PublicationTypes: []string{study.StudyType, study.Phase},
		DOI:              "",
	}
}

func BuildSourceMetadata(study models.ClinicalTrialStudy) models.SourceMetadata {
	hash := sha256.Sum256([]byte(study.FullJSON))
	return models.SourceMetadata{
		MedlineStatus: study.OverallStatus,
		PubStatus:     hex.EncodeToString(hash[:16]),
	}
}