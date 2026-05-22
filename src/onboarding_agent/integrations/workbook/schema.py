"""Workbook schemas and column aliases."""

from __future__ import annotations

TRACKER_REQUIRED_ALIASES = {
    "staff_name": {"staff name", "name", "employee name"},
    "staff_email": {"staff email", "email", "employee email"},
    "work_location": {"work location", "location"},
    "requested_start_date": {"requested start date", "start date", "startdate"},
}

TRACKER_OPTIONAL_ALIASES = {
    "submission_id": {"submission id", "submissionid", "forms submission id"},
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
    "name": {"employee name"},
    "email": {"work email"},
    "group": {"group"},
}

ROSTER_OPTIONAL_ALIASES = {
    "employee_id": {"employee id"},
    "position": {"job title"},
    "grade_level": {"grade level"},
    "subject": {"subject"},
    "notes": {"notes"},
    "supplements": {"supplements"},
    "background_eligibility": {"background eligibility"},
    "date_approved": {"date"},
    "fingerprint_expiration_date": {"fingerprint expiration date"},
    "license": {"license"},
    "personal_email": {"personal email"},
    "nine_cell": {"9-cell"},
    "location": {"location"},
    "status": {"status"},
    "salary": {"salary"},
    "start_date": {"hire date"},
    "term": {"term"},
    "rate_type": {"rate type"},
    "part_time_full_time": {"part time/full time"},
    "shared": {"shared"},
    "funding_source": {"funding source"},
    "talent": {"talent"},
    "nti_culture": {"nti culture"},
    "nti_content": {"nti content"},
    "mupd_culture": {"mupd culture"},
    "mupd_content": {"mupd content"},
    "rt_boy_pd_content": {"rt boy pd content", "rt boy pd content ", "rt boy pd content\t"},
    "cc_1": {"cc 1", "cc1"},
    "cc_2": {"cc 2", "cc2"},
    "cc_3": {"cc 3", "cc3"},
    "manager_email": {"manager email", "manageremail"},
}

CAPACITY_ALIASES = {
    "group": {"group", "job category", "category"},
    "capacity": {"capacity", "max capacity", "maxcapacity"},
    "vacancies": {"vacancies", "vacancy"},
}

SEPARATIONS_REQUIRED_ALIASES = {
    "name": {"employee name"},
    "email": {"work email"},
}

SEPARATIONS_OPTIONAL_ALIASES = {
    "employee_id": {"employee id"},
    "group": {"group"},
    "position": {"job title"},
    "grade_level": {"grade level"},
    "subject": {"subject"},
    "supplements": {"supplements"},
    "talent": {"talent"},
    "background_eligibility": {"background eligibility"},
    "date_approved": {"date"},
    "fingerprint_expiration_date": {"fingerprint expiration date"},
    "license": {"license"},
    "personal_email": {"personal email"},
    "nine_cell": {"9-cell"},
    "notes": {"notes"},
    "location": {"location"},
    "status": {"status"},
    "salary": {"salary"},
    "nti_culture": {"nti culture"},
    "nti_content": {"nti content"},
    "mupd_culture": {"mupd culture"},
    "mupd_content": {"mupd content"},
    "rt_boy_pd_content": {"rt boy pd content", "rt boy pd content ", "rt boy pd content\t"},
    "cc_1": {"cc 1", "cc1"},
    "cc_2": {"cc 2", "cc2"},
    "cc_3": {"cc 3", "cc3"},
    "start_date": {"hire date"},
    "term": {"term"},
    "rate_type": {"rate type"},
    "part_time_full_time": {"part time/full time"},
    "shared": {"shared"},
    "funding_source": {"funding source"},
    "manager_email": {"manager email", "manageremail"},
    "separation_type": {"separation type", "change type", "status change"},
    "separation_date": {"separation date", "effective date"},
    "date_processed": {"date processed", "processed date"},
}
