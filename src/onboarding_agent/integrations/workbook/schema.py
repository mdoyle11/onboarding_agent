"""Workbook schemas and column aliases."""

from __future__ import annotations

TRACKER_REQUIRED_ALIASES = {
    "staff_name": {"staff name", "name", "employee name"},
    "staff_email": {"staff email", "email", "employee email"},
    "work_location": {"work location", "location"},
    "requested_start_date": {"requested start date", "start date", "startdate"},
}

TRACKER_OPTIONAL_ALIASES = {
    "requesting_manager": {"requesting manager", "manager", "manager email"},
    "status_change": {"status change", "status"},
    "staff_phone": {"staff phone #", "staff phone", "phone"},
    "job_title": {"job title", "title", "position"},
    "education_level": {"education level"},
    "supplements": {"supplements"},
    "license_number": {"license #", "license"},
    "uploaded_credentials": {"uploaded credentials", "credentials"},
    "compensation": {"compensation"},
    "employment_type": {"employment type"},
    "contract_term": {"contract term"},
}

STAGE_NAMES = [
    "Added to Tracker",
    "Added to Staff Roster",
    "Sent Offer Letter",
    "Offer Letter Signed",
    "Background Submission",
    "Background Cleared",
    "Added to ADP",
    "Employee Complete ADP Profile",
    "Complete in ADP",
    "Proration",
    "Clear to Start",
    "Drug Screening",
]

STAGE_ALIASES = {
    "Completed in ADP": "Complete in ADP",
    "Prorations Sent": "Proration",
    "Start Date": "Clear to Start",
}

ALL_STAGES = list(STAGE_NAMES)

HEADER_ROW = [
    "Requesting Manager",
    "Work Location",
    "Status Change",
    "Staff Name",
    "Staff Email",
    "Staff Phone #",
    "Job Title",
    "Requested Start Date",
    "Education Level",
    "Supplements",
    "License #",
    "Uploaded Credentials",
    "Compensation",
    "Employment Type",
    "Contract Term",
] + STAGE_NAMES

ROSTER_REQUIRED_ALIASES = {
    "name": {"employee name", "name"},
    "email": {"employee email", "email"},
    "group": {"group", "job category", "category"},
}

ROSTER_OPTIONAL_ALIASES = {
    "start_date": {"start date", "startdate"},
    "position": {"position"},
    "personal_email": {"personal email", "personalemail", "personal e-mail"},
    "manager_email": {"manager email", "manageremail"},
    "location": {"location"},
}

CAPACITY_ALIASES = {
    "group": {"group", "job category", "category"},
    "capacity": {"capacity", "max capacity", "maxcapacity"},
}
