from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, PositiveInt
from pydantic import model_validator


InvestigationStatus = Literal["evidence_found", "no_source_evidence"]
DiffStatus = Literal["available", "no_diff", "unavailable", "invalid_diff"]
SourceEvidenceOverlapStatus = Literal["available", "unavailable"]
HistoricalAstStatus = Literal[
    "available",
    "not_found",
    "unavailable",
    "invalid_input",
    "invalid_source",
]
DeletedHistoricalAstStatus = Literal[
    "available",
    "not_found",
    "unavailable",
    "invalid_input",
    "invalid_source",
    "not_required",
]


class _ReportModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class SourceFunctionEvidence(_ReportModel):
    function_name: str
    start_line: PositiveInt
    end_line: PositiveInt
    is_async: bool

    @model_validator(mode="after")
    def validate_line_boundaries(self) -> "SourceFunctionEvidence":
        if self.start_line > self.end_line:
            raise ValueError("start_line must be less than or equal to end_line")
        return self


class SourceEvidence(_ReportModel):
    file: str
    line_number: PositiveInt
    matching_keywords: list[str]
    relevance_score: PositiveInt
    code_snippet: str
    start_line: PositiveInt
    end_line: PositiveInt
    context: str
    function: SourceFunctionEvidence | None

    @model_validator(mode="after")
    def validate_context_boundaries(self) -> "SourceEvidence":
        if self.start_line > self.end_line:
            raise ValueError("start_line must be less than or equal to end_line")
        return self


class GitHistoryEntry(_ReportModel):
    commit_hash: str
    short_hash: str
    author: str
    date: str
    message: str
    changed_files: list[str]


class ChangedLine(_ReportModel):
    line_number: PositiveInt
    content: str


class LineFunctionMatch(_ReportModel):
    line_number: PositiveInt
    function_names: list[str]


class ChangeEvidence(_ReportModel):
    file_path: str
    commit_hash: str
    added_lines: list[ChangedLine]
    deleted_lines: list[ChangedLine]
    overlaps_suspicious_source_evidence: bool
    source_evidence_overlap_status: SourceEvidenceOverlapStatus
    added_lines_overlap_historical_function: bool
    matching_function_names: list[str]
    matching_added_function_names: list[str]
    matching_deleted_function_names: list[str]
    added_line_function_matches: list[LineFunctionMatch]
    deleted_line_function_matches: list[LineFunctionMatch]
    historical_ast_status: HistoricalAstStatus
    deleted_historical_ast_status: DeletedHistoricalAstStatus
    status: DiffStatus
    note: str
    error_reason: str | None = None
    historical_ast_error_reason: str | None = None
    source_evidence_overlap_error_reason: str | None = None
    deleted_historical_ast_error_reason: str | None = None

    @model_validator(mode="after")
    def validate_source_overlap(self) -> "ChangeEvidence":
        if (
            self.source_evidence_overlap_status == "unavailable"
            and self.overlaps_suspicious_source_evidence
        ):
            raise ValueError(
                "source evidence overlap cannot be true when its status "
                "is unavailable"
            )
        return self


class RelevantCommit(_ReportModel):
    file: str
    commit_hash: str
    message: str
    matching_keywords: list[str]
    keyword_score: float = Field(ge=0, le=1)
    source_relevance_score: float = Field(ge=0, le=1)
    recency_score: float = Field(ge=0, le=1)
    relevance_score: float = Field(ge=0, le=1)
    change_evidence: ChangeEvidence


class InvestigationStatistics(_ReportModel):
    source_matches: NonNegativeInt
    files_investigated: NonNegativeInt
    commits_found: NonNegativeInt
    potentially_relevant_commits: NonNegativeInt


class Diagnosis(_ReportModel):
    root_cause_confirmed: bool
    message: str


class InvestigationReport(_ReportModel):
    incident: dict[str, Any]
    investigation_status: InvestigationStatus
    source_evidence: list[SourceEvidence]
    git_history: dict[str, list[GitHistoryEntry]]
    potentially_relevant_commits: list[RelevantCommit]
    statistics: InvestigationStatistics
    diagnosis: Diagnosis

    @model_validator(mode="after")
    def validate_report_consistency(self) -> "InvestigationReport":
        has_source_evidence = bool(self.source_evidence)
        expected_status = (
            "evidence_found" if has_source_evidence else "no_source_evidence"
        )
        if self.investigation_status != expected_status:
            raise ValueError(
                "investigation_status must agree with source_evidence"
            )

        if self.statistics.source_matches != len(self.source_evidence):
            raise ValueError(
                "statistics.source_matches must equal len(source_evidence)"
            )

        if self.statistics.files_investigated != len(self.git_history):
            raise ValueError(
                "statistics.files_investigated must equal len(git_history)"
            )

        history_commit_count = sum(
            len(commits) for commits in self.git_history.values()
        )
        if self.statistics.commits_found != history_commit_count:
            raise ValueError(
                "statistics.commits_found must equal the total Git-history "
                "record count"
            )

        if (
            self.statistics.potentially_relevant_commits
            != len(self.potentially_relevant_commits)
        ):
            raise ValueError(
                "statistics.potentially_relevant_commits must equal "
                "len(potentially_relevant_commits)"
            )

        return self
