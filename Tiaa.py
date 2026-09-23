"""
Wove mock backend — replaces the Postman mock with real, request-driven logic.

It parses the incoming <SalesforceToWoveData> XML, extracts caseId, SSN and
Custodian from the actual request, and builds the response (and account number)
from those values.

Endpoints (all POST):
    /tiaa-account        -> returns AccountNumber TIAA-<last4>-<timestamp>
    /pershing-account    -> returns AccountNumber PERSH-<last4>-<timestamp>
    /sfdc-writeback      -> returns 200 with empty body (no data), like the real system

Run:
    pip install flask
    python wove_mock_server.py
    # serves on http://localhost:5000
"""

from datetime import datetime, timezone
from xml.etree import ElementTree as ET

from flask import Flask, request, Response

app = Flask(__name__)


def parse_request(raw_xml: str):
    """Pull the fields we care about out of the incoming request XML.

    Returns a dict with caseId, custodian and last4 (last 4 digits of the SSN).
    Missing fields come back as empty strings rather than blowing up, so a
    partial request still gets a sensible response.
    """
    root = ET.fromstring(raw_xml)

    def text(path):
        node = root.find(path)
        return node.text.strip() if node is not None and node.text else ""

    case_id = text("case/caseId")
    custodian = text("ProposalDetails/Custodian")
    ssn = text("Demographics/SSN")

    # last 4 digits of the SSN, stripping any non-digit characters first
    digits = "".join(ch for ch in ssn if ch.isdigit())
    last4 = digits[-4:] if digits else ""

    return {"caseId": case_id, "custodian": custodian, "last4": last4}


def build_account_response(prefix: str) -> Response:
    """Shared logic for the two account-creation endpoints.

    prefix is the account-number prefix ("TIAA" or "PERSH").
    """
    try:
        data = parse_request(request.data.decode("utf-8"))
    except ET.ParseError:
        return Response("<Error>Invalid or unparseable XML</Error>",
                        status=400, mimetype="application/xml")

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    account_number = f"{prefix}-{data['last4']}-{timestamp}"

    response_xml = f"""<?xml version="1.0"?>
<SalesforceToWoveDataResponse>
  <case>
    <caseId>{data['caseId']}</caseId>
  </case>
  <ProposalDetails>
    <Custodian>{data['custodian']}</Custodian>
  </ProposalDetails>
  <AccountDetails>
    <AccountNumber>{account_number}</AccountNumber>
  </AccountDetails>
</SalesforceToWoveDataResponse>"""

    return Response(response_xml, status=200, mimetype="application/xml")


@app.route("/tiaa-account", methods=["POST"])
def tiaa_account():
    return build_account_response("TIAA")


@app.route("/pershing-account", methods=["POST"])
def pershing_account():
    return build_account_response("PERSH")


@app.route("/sfdc-writeback", methods=["POST"])
def sfdc_writeback():
    # Real system acknowledges with success and no body.
    # Optionally validate the incoming XML and 400 on failure.
    try:
        ET.fromstring(request.data.decode("utf-8"))
    except ET.ParseError:
        return Response("<Error>Invalid or unmatched request</Error>",
                        status=400, mimetype="application/xml")
    return Response("", status=200)


if __name__ == "__main__":
    # host=0.0.0.0 so a tunnel (ngrok/cloudflared) can reach it
    app.run(host="0.0.0.0", port=5000)