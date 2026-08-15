"""Tests for retraction_client: XML-marker parsing (offline fixtures for each
marker combination) plus one live end-to-end check against a famously
retracted paper."""

from unittest.mock import patch

from biolab import retraction_client

RETRACTED_XML = b"""<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation Status="MEDLINE">
      <PMID>1111111</PMID>
      <Article>
        <ArticleTitle>A retracted paper</ArticleTitle>
        <PublicationTypeList>
          <PublicationType>Journal Article</PublicationType>
          <PublicationType>Retracted Publication</PublicationType>
        </PublicationTypeList>
      </Article>
      <CommentsCorrectionsList>
        <CommentsCorrections RefType="RetractionIn">
          <RefSource>Lancet. 2010 Feb 6;375(9713):445</RefSource>
          <PMID>20137807</PMID>
        </CommentsCorrections>
      </CommentsCorrectionsList>
    </MedlineCitation>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation Status="MEDLINE">
      <PMID>2222222</PMID>
      <Article>
        <ArticleTitle>A perfectly fine paper</ArticleTitle>
        <PublicationTypeList>
          <PublicationType>Journal Article</PublicationType>
        </PublicationTypeList>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation Status="MEDLINE">
      <PMID>3333333</PMID>
      <Article>
        <ArticleTitle>A paper under a cloud</ArticleTitle>
        <PublicationTypeList>
          <PublicationType>Journal Article</PublicationType>
        </PublicationTypeList>
      </Article>
      <CommentsCorrectionsList>
        <CommentsCorrections RefType="ExpressionOfConcernIn">
          <RefSource>Some Journal. 2024</RefSource>
        </CommentsCorrections>
      </CommentsCorrectionsList>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>
"""


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_parses_all_marker_combinations():
    with patch(
        "biolab.retraction_client._urlopen_with_retry",
        return_value=_FakeResponse(RETRACTED_XML),
    ):
        statuses = retraction_client.check(["1111111", "2222222", "3333333"])

    by_pmid = {s.pmid: s for s in statuses}
    assert len(by_pmid) == 3

    retracted = by_pmid["1111111"]
    assert retracted.retracted is True
    assert retracted.concern is False
    assert retracted.notice.startswith("Lancet. 2010")
    assert retracted.notice_pmid == "20137807"

    clean = by_pmid["2222222"]
    assert clean.retracted is False
    assert clean.concern is False
    assert clean.notice == ""

    concern = by_pmid["3333333"]
    assert concern.retracted is False
    assert concern.concern is True


def test_empty_input_returns_empty():
    assert retraction_client.check([]) == []


def test_live_wakefield_1998_is_retracted():
    """PMID 9500320 is the 1998 Wakefield MMR paper, retracted by The Lancet
    in 2010 — as close to a permanent ground-truth retraction as exists."""
    statuses = retraction_client.check(["9500320"])
    assert len(statuses) == 1
    assert statuses[0].retracted is True
