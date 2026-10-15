"""Row models: what a valid row of each source file looks like.

Every CSV value arrives as text. A row model turns it into typed values or explains why it
can't; each problem becomes one of ERROR_CODES, stored with the rejected row so the
data-quality report can say exactly what was wrong. Field aliases are the source's column
headers; field names are the staging columns.
"""

import re
from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)
from pydantic_core import PydanticCustomError

# The loader's contract: every rejected row carries one of these codes.
ERROR_CODES = {
    "missing_required": "A required value is empty",
    "invalid_number": "Not a number, or too many digits",
    "negative_value": "A count or amount below zero",
    "invalid_date": "Not a valid YYYY-MM-DD date",
    "invalid_timestamp": "Not a valid timestamp with a time zone",
    "invalid_boolean": "Not true or false",
    "invalid_salesforce_id": "Not a 15- or 18-character Salesforce id",
    "clicks_exceed_impressions": "More link clicks than impressions",
    "conversion_mismatch": "IsConverted disagrees with ConvertedOpportunityId",
    "won_but_not_closed": "IsWon is true but IsClosed is false",
    "end_before_start": "The end date is before the start date",
    "conflicting_duplicate": "Same key as an earlier row in the file, different values",
    "malformed_row": "More values than the header has columns",
    "invalid_value": "Any other invalid value",
}

# Pydantic's error types, translated to the codes above.
_PYDANTIC_CODES = {
    "missing": "missing_required",
    "int_parsing": "invalid_number",
    "int_from_float": "invalid_number",
    "decimal_parsing": "invalid_number",
    "decimal_max_digits": "invalid_number",
    "decimal_max_places": "invalid_number",
    "decimal_whole_digits": "invalid_number",
    "greater_than_equal": "negative_value",
    "date_parsing": "invalid_date",
    "date_from_datetime_parsing": "invalid_date",
    "date_from_datetime_inexact": "invalid_date",
    "datetime_parsing": "invalid_timestamp",
    "datetime_from_date_parsing": "invalid_timestamp",
    "timezone_aware": "invalid_timestamp",
    "bool_parsing": "invalid_boolean",
}

_SALESFORCE_ID = re.compile(r"[A-Za-z0-9]{15}(?:[A-Za-z0-9]{3})?")


def _salesforce_id(value: str) -> str:
    if not _SALESFORCE_ID.fullmatch(value):
        raise PydanticCustomError("invalid_salesforce_id", ERROR_CODES["invalid_salesforce_id"])
    return value


Count = Annotated[int, Field(ge=0)]
Money = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)]
SalesforceId = Annotated[str, AfterValidator(_salesforce_id)]


def describe_errors(exc: ValidationError) -> list[dict[str, Any]]:
    """Translate a ValidationError into [{field, code, message}, ...]."""
    problems = []
    for error in exc.errors(include_url=False):
        kind = error["type"]
        code = kind if kind in ERROR_CODES else _PYDANTIC_CODES.get(kind, "invalid_value")
        field = str(error["loc"][0]) if error["loc"] else None
        problems.append({"field": field, "code": code, "message": error["msg"]})
    return problems


class SourceRow(BaseModel):
    # Extra columns are ignored here; the loader checks required columns once per file.
    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)


class MetaInsightsRow(SourceRow):
    report_date: date = Field(alias="date")
    account_id: str
    account_timezone: str
    campaign_id: str
    campaign_name: str
    spend: Money
    impressions: Count
    inline_link_clicks: Count
    leads_reported: Count
    attribution_setting: str

    @model_validator(mode="after")
    def _clicks_within_impressions(self) -> "MetaInsightsRow":
        if self.inline_link_clicks > self.impressions:
            raise PydanticCustomError(
                "clicks_exceed_impressions", ERROR_CODES["clicks_exceed_impressions"]
            )
        return self


class Ga4SessionRow(SourceRow):
    user_pseudo_id: str
    ga_session_id: Count
    session_start_utc: AwareDatetime
    source: str
    medium: str
    campaign: str | None = None
    content: str | None = None
    landing_page: str
    device_category: str
    has_gclid: bool
    has_fbclid: bool
    ev_quote_submit: Count
    ev_callback_submit: Count
    ev_phone_click: Count
    ev_chat_start: Count
    ev_booking_click: Count


class SalesforceLeadRow(SourceRow):
    id: SalesforceId = Field(alias="Id")
    created_date: AwareDatetime = Field(alias="CreatedDate")
    lead_source: str | None = Field(None, alias="LeadSource")
    status: str = Field(alias="Status")
    is_converted: bool = Field(alias="IsConverted")
    converted_date: date | None = Field(None, alias="ConvertedDate")
    converted_opportunity_id: SalesforceId | None = Field(None, alias="ConvertedOpportunityId")
    # Kept exactly as typed (spaces and all); the core step normalizes cities.
    city: str | None = Field(None, alias="City")
    # Custom fields (__c) are hypothetical (U-02), so all of them are optional.
    entry_point: str | None = Field(None, alias="Entry_Point__c")
    request_type: str | None = Field(None, alias="Request_Type__c")
    existing_customer: str | None = Field(None, alias="Existing_Customer__c")
    service_line: str | None = Field(None, alias="Service_Line__c")
    form_page_path: str | None = Field(None, alias="Form_Page_Path__c")
    utm_source: str | None = Field(None, alias="UTM_Source__c")
    utm_medium: str | None = Field(None, alias="UTM_Medium__c")
    utm_campaign: str | None = Field(None, alias="UTM_Campaign__c")
    click_id_type: str | None = Field(None, alias="Click_Id_Type__c")
    ga_client_id: str | None = Field(None, alias="GA_Client_Id__c")
    meta_campaign_id: str | None = Field(None, alias="Meta_Campaign_Id__c")
    person_key: str | None = Field(None, alias="Person_Key__c")
    qualified_date: AwareDatetime | None = Field(None, alias="Qualified_Date__c")
    is_test: bool = Field(False, alias="Is_Test__c")

    @model_validator(mode="after")
    def _conversion_consistent(self) -> "SalesforceLeadRow":
        if self.is_converted != (self.converted_opportunity_id is not None):
            raise PydanticCustomError("conversion_mismatch", ERROR_CODES["conversion_mismatch"])
        return self


class SalesforceEventRow(SourceRow):
    id: SalesforceId = Field(alias="Id")
    who_id: SalesforceId = Field(alias="WhoId")
    event_type: str = Field(alias="Type")
    appointment_status: str | None = Field(None, alias="Appointment_Status__c")
    created_date: AwareDatetime = Field(alias="CreatedDate")
    activity_date_time: AwareDatetime = Field(alias="ActivityDateTime")


class SalesforceOpportunityRow(SourceRow):
    id: SalesforceId = Field(alias="Id")
    created_date: AwareDatetime = Field(alias="CreatedDate")
    stage_name: str = Field(alias="StageName")
    close_date: date = Field(alias="CloseDate")
    is_closed: bool = Field(alias="IsClosed")
    is_won: bool = Field(alias="IsWon")
    amount: Money | None = Field(None, alias="Amount")
    amount_basis: str | None = Field(None, alias="Amount_Basis__c")
    service_line: str | None = Field(None, alias="Service_Line__c")

    @model_validator(mode="after")
    def _won_means_closed(self) -> "SalesforceOpportunityRow":
        if self.is_won and not self.is_closed:
            raise PydanticCustomError("won_but_not_closed", ERROR_CODES["won_but_not_closed"])
        return self


class CampaignMappingRow(SourceRow):
    """One row of the marketing team's campaign naming sheet."""

    platform: str
    platform_campaign_id: str | None = None
    campaign_name: str
    utm_campaign: str
    tactic: str | None = None
    service_lines: str | None = None  # pipe-separated, e.g. "water_heater|water_treatment"
    region: str | None = None


class AnnotationRow(SourceRow):
    annotation_type: str = Field(alias="type")
    start_date: date
    end_date: date
    label: str

    @model_validator(mode="after")
    def _ordered(self) -> "AnnotationRow":
        if self.end_date < self.start_date:
            raise PydanticCustomError("end_before_start", ERROR_CODES["end_before_start"])
        return self
