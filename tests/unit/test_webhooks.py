"""Tests for webhook parsing helpers."""

from onboarding_agent.runtime.webhooks import parse_docusign_payload


def test_parse_docusign_json_payload_extracts_custom_field() -> None:
    body = b'{"envelopeId":"env-123","status":"completed","customFields":{"textCustomFields":[{"name":"employee_email","value":"alice@example.com"}]}}'

    parsed = parse_docusign_payload(body, "application/json")

    assert parsed == {
        "envelope_id": "env-123",
        "status": "completed",
        "employee_email": "alice@example.com",
    }


def test_parse_docusign_xml_payload_extracts_custom_field() -> None:
    body = b"""
<DocuSignEnvelopeInformation xmlns="http://www.docusign.net/API/3.0">
  <EnvelopeStatus>
    <EnvelopeID>env-456</EnvelopeID>
    <Status>sent</Status>
    <CustomFields>
      <CustomField>
        <Name>employee_email</Name>
        <Value>bob@example.com</Value>
      </CustomField>
    </CustomFields>
  </EnvelopeStatus>
</DocuSignEnvelopeInformation>
"""

    parsed = parse_docusign_payload(body, "application/xml")

    assert parsed == {
        "envelope_id": "env-456",
        "status": "sent",
        "employee_email": "bob@example.com",
    }
