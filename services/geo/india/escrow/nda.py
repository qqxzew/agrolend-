"""Mutual NDA and non-circumvention agreement for India, as PDF (English).

Template NDA-IN-1.0. Structure follows common Indian B2B practice: definition and exclusions, need-to-know,
non-circumvention of landowner relationships (in-term only: a post-term restraint on trade is void under s.27 of the
Indian Contract Act, 1872), liquidated damages limited to reasonable compensation (s.74, with a cap), return/deletion,
DPDP Act 2023, term and survival, stamp duty, arbitration seated in India (Arbitration and Conciliation Act, 1996),
electronic acceptance (Information Technology Act, 2000).

The text is a TEMPLATE: have an Indian advocate approve it, and check the stamp duty of the state concerned, before
production use. Only WinAnsi characters are used, so the rupee sign is written "INR".
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, Spacer, Table, TableStyle

from ..common.pdfkit import ST_BODY, ST_H, ST_PARTY, ST_SMALL, ST_SUB, ST_TITLE, build_pdf, inr, paras, table

TEMPLATE_VERSION = "NDA-IN-1.0"
TITLE = "Mutual Non-Disclosure and Non-Circumvention Agreement"


@dataclass
class Party:
    company_name: str
    address: str  # registered office, one line
    state: str
    pin_code: str
    representative: str  # authorised signatory incl. designation
    registration: str = ""  # CIN / LLPIN / registration no.
    gstin: str = ""
    email: str = ""

    def block(self) -> str:
        lines = [f"<b>{escape(self.company_name)}</b>",
                 f"having its registered office at {escape(self.address)}, {escape(self.state)} - {escape(self.pin_code)}"]
        if self.registration:
            lines.append(f"registration no. (CIN/LLPIN): {escape(self.registration)}")
        if self.gstin:
            lines.append(f"GSTIN: {escape(self.gstin)}")
        lines.append(f"represented by its authorised signatory: {escape(self.representative)}")
        if self.email:
            lines.append(f"e-mail for notices: {escape(self.email)}")
        return "<br/>".join(lines)


@dataclass
class NdaParams:
    nda_id: str
    match_id: str
    created_at: datetime
    platform_name: str = "India Land Pooling Platform"
    term_years: int = 2
    aftereffect_years: int = 5
    non_circumvention_months: int = 24
    max_compensation_inr: int = 2_500_000
    arbitration_seat: str = "New Delhi"
    court_city: str = "New Delhi"


@dataclass
class Signature:
    party_label: str  # "A" | "B"
    signer_name: str
    signer_role: str
    signed_at: datetime
    ip: str = ""


def _sections(a: Party, b: Party, p: NdaParams) -> list[tuple[str, list[str]]]:
    """(heading, paragraphs). A paragraph starting with two spaces is rendered as an indented sub-item."""
    return [
        ("1. Confidential Information", [
            "1.1 \"Confidential Information\" means all information that one Party (the \"Disclosing Party\") makes available to "
            "the other Party (the \"Receiving Party\") in connection with the Purpose - in writing, orally, electronically, by "
            "inspection or otherwise, through the Platform or directly, before, on or after the date of this Agreement - whether "
            "or not marked confidential.",
            "1.2 Confidential Information includes in particular:",
            "  (a) the location, boundaries, area, survey / sub-division numbers, ULPIN and land-record extracts of the Disclosing "
            "Party's land, and all maps and geospatial data;",
            "  (b) the identity and contact details of landowners, lessors, farmers and other persons holding rights in the land, "
            "and existing or proposed arrangements with them (leases, licences, options, consents, memoranda of understanding, "
            "commercial terms);",
            "  (c) site, wind and solar resource studies, grid, evacuation and approval documents, and project plans;",
            "  (d) business models, prices, calculations, financing and shareholding structures;",
            "  (e) the fact, content and status of the discussions between the Parties and the content of this Agreement.",
            "1.3 To the extent Confidential Information is a trade secret, it is also protected by the general law of "
            "confidence and equity; nothing in this Agreement limits those remedies.",
        ]),
        ("2. Exclusions", [
            "2.1 Confidential Information does not include information that the Receiving Party can show",
            "  (a) is or becomes publicly available other than through a breach of this Agreement;",
            "  (b) was lawfully known to it, without a duty of confidence, before disclosure;",
            "  (c) was lawfully received from a third party without a duty of confidence; or",
            "  (d) was developed by it independently without use of the Confidential Information.",
            "2.2 Information is not public merely because parts of it are public or because it is a combination of public items.",
            "2.3 The Receiving Party may disclose Confidential Information where required by law, by a court, tribunal or "
            "regulator of competent jurisdiction, or by a lawful order of a government authority. It shall, where lawful, "
            "give the Disclosing Party prompt prior written notice, disclose only what is legally required, and seek "
            "confidential treatment.",
        ]),
        ("3. Obligations of the Receiving Party", [
            "3.1 The Receiving Party shall keep the Confidential Information secret, use it only for the Purpose, and not "
            "disclose or exploit it for any other purpose.",
            "3.2 It shall protect the Confidential Information with at least the care it applies to its own information of "
            "comparable importance and never less than reasonable care.",
            "3.3 Access is limited to directors, employees and Affiliates, and to professional advisers (advocates, chartered "
            "accountants, surveyors, lenders and technical consultants) who need it for the Purpose and are bound by "
            "professional or written confidentiality duties no less strict than this Agreement. The Receiving Party is "
            "responsible for any breach by these persons.",
            "3.4 Copies may be made only as needed for the Purpose and are Confidential Information.",
            "3.5 The Receiving Party shall notify the Disclosing Party in writing without delay of any actual or suspected "
            "breach and shall help limit the damage.",
            "3.6 No right, title, licence or option in the Confidential Information is granted by disclosure.",
        ]),
        ("4. Non-circumvention; protection of landowner relationships", [
            f"4.1 During the period of {p.non_circumvention_months} months from the Effective Date (the \"Restricted Period\"), "
            "and without the other Party's prior written consent, each Party shall not, directly or through any other person:",
            "  (a) approach landowners, lessors, farmers or other rights-holders of the other Party's land, whom it came to "
            "know through the disclosure, for the purpose of negotiating, amending, replacing or concluding any lease, "
            "licence, option, consent or comparable arrangement over that land;",
            "  (b) conclude any such arrangement over that land, or interfere with or attempt to terminate an existing "
            "arrangement of the other Party; or",
            "  (c) induce or assist any third party to do so.",
            "4.2 Clause 4.1 does not apply if the Party shows that, before disclosure, it already had a contractual "
            "relationship, or concrete documented negotiations, with the person concerned for the same land.",
            "4.3 Each Party's relationships with the landowners and rights-holders of its own land are unaffected.",
            "4.4 The restriction in clause 4.1 applies only during the Restricted Period, is limited to the land and persons "
            "disclosed under this Agreement, and the Parties consider it reasonable and necessary to protect the "
            "confidential information disclosed and not a restraint on any lawful profession, trade or business "
            "(section 27 of the Indian Contract Act, 1872).",
        ]),
        ("5. Compensation for breach", [
            "5.1 If a Party breaches clause 3 or 4, it shall pay the other Party, as compensation for the loss that the "
            "Parties agree would be likely to result and that is difficult to prove precisely, a reasonable sum "
            f"determined in accordance with section 74 of the Indian Contract Act, 1872, not exceeding {inr(p.max_compensation_inr)} "
            "per breach. The claiming Party need not prove actual loss, but shall show the breach; the sum is subject to "
            "review by the arbitral tribunal for reasonableness.",
            "5.2 A continuing breach counts as one breach until it ends.",
            "5.3 The Parties acknowledge that damages may be an inadequate remedy; each Party may seek injunctive relief "
            "(including under the Specific Relief Act, 1963) and interim measures under section 9 of the Arbitration and "
            "Conciliation Act, 1996, without proof of actual loss. Compensation paid under clause 5.1 is set off against "
            "any damages awarded for the same breach.",
        ]),
        ("6. Return and deletion", [
            "6.1 On written request of the Disclosing Party, and in any event when discussions end, the Receiving Party shall "
            "promptly return, delete or destroy all Confidential Information and copies and confirm this in writing.",
            "6.2 This does not apply to documents that must be retained by law or to automatic back-ups that cannot "
            "reasonably be deleted; the obligations of this Agreement continue to apply to them.",
        ]),
        ("7. Personal data", [
            "7.1 Where Confidential Information contains personal data (for example of landowners, farmers or contact "
            "persons), the Disclosing Party shall disclose it only where necessary for the Purpose and permitted by the "
            "Digital Personal Data Protection Act, 2023 (the \"DPDP Act\"). Each Party acts as an independent data fiduciary "
            "for the personal data it processes.",
            "7.2 The Receiving Party shall process such data only for the Purpose, apply reasonable security safeguards as "
            "required by the DPDP Act and the rules made under it, and meet its own notice and consent obligations.",
        ]),
        ("8. No obligation to contract; no warranty", [
            "8.1 This Agreement does not oblige either Party to start or continue negotiations or to enter into a land "
            "pooling, joint development or other agreement. Any such agreement requires a separate written instrument.",
            "8.2 Confidential Information is disclosed without warranty of accuracy or completeness, without prejudice to "
            "liability for fraud or wilful concealment.",
            "8.3 Results of any suitability audit carried out through the Platform are non-binding screening indications "
            "and do not replace the Parties' own due diligence, including verification of title with the competent revenue "
            "or registration authority.",
        ]),
        ("9. Term and survival", [
            f"9.1 This Agreement takes effect when both Parties have accepted it through the Platform (the \"Effective Date\") "
            f"and runs for {p.term_years} years. Either Party may terminate it earlier for a material breach by the other that "
            "remains uncured 30 days after written notice.",
            f"9.2 Clauses 3, 6 and 7 survive expiry or termination for a further {p.aftereffect_years} years and, for personal "
            "data and trade secrets, for as long as the information remains personal data or a trade secret. The "
            "Restricted Period under clause 4 is as stated there and does not extend beyond it.",
        ]),
        ("10. Stamp duty, execution and notices", [
            "10.1 The Parties shall bear any stamp duty payable on this Agreement in equal shares. Where the law of the state "
            "concerned requires it, each Party shall arrange e-stamping or franking before relying on this Agreement in "
            "evidence; the Parties agree that the instrument may be duly stamped after execution on payment of the "
            "applicable duty and any penalty.",
            "10.2 The Parties execute this Agreement electronically through the Platform: each Party's authorised signatory "
            "accepts it by an electronic record under the Information Technology Act, 2000. The signature log (Annexure 1) "
            "forms part of this Agreement. Amendments must be in writing signed by both Parties.",
            "10.3 Notices must be sent to the addresses and e-mail addresses stated above.",
            "10.4 Rights and obligations may be assigned only with the other Party's written consent. This Agreement binds "
            "successors.",
            "10.5 If any provision is invalid or unenforceable, the rest remains in force and the Parties shall replace the "
            "provision with a valid one that comes closest to its commercial purpose.",
            "10.6 The Parties receive this Agreement as a PDF file; the version stored by the Platform with the SHA-256 value "
            "stated in the signature log is authoritative.",
        ]),
        ("11. Governing law and dispute resolution", [
            "11.1 This Agreement is governed by the laws of India.",
            "11.2 Any dispute arising out of or in connection with this Agreement shall be finally resolved by arbitration "
            "under the Arbitration and Conciliation Act, 1996 before a sole arbitrator appointed by agreement of the Parties "
            f"or, failing agreement within 30 days, by the competent court. The seat and venue of arbitration is "
            f"{p.arbitration_seat}. The language is English.",
            f"11.3 Subject to clause 11.2, the courts at {p.court_city} have exclusive jurisdiction for interim relief and "
            "for the enforcement of any award; each Party may also seek interim relief from any court of competent "
            "jurisdiction.",
        ]),
    ]


def _fmt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%d %b %Y, %H:%M:%S UTC")


def _front(a: Party, b: Party, p: NdaParams) -> list:
    return [
        Paragraph(TITLE, ST_TITLE),
        Paragraph(f"Template {TEMPLATE_VERSION}", ST_SUB),
        Paragraph("This Agreement is made on the Effective Date between", ST_BODY),
        Paragraph(a.block() + "<br/>(\"<b>Party A</b>\")", ST_PARTY),
        Paragraph("and", ST_BODY),
        Paragraph(b.block() + "<br/>(\"<b>Party B</b>\")", ST_PARTY),
        Paragraph("Party A and Party B are together the \"Parties\" and each a \"Party\".", ST_BODY),
        Paragraph("Recitals", ST_H),
        Paragraph(
            "(A) Each Party plans to develop wind and/or solar energy projects on land located near the other Party's land. "
            f"The Parties were introduced through the platform \"{escape(p.platform_name)}\" under match reference "
            f"{escape(p.match_id)}. The operator of the Platform is not a party to this Agreement.", ST_BODY),
        Paragraph(
            "(B) The Parties are considering cooperation, in particular joint project development, a pooling of land and a "
            "shared grid connection (the \"Purpose\").", ST_BODY),
        Paragraph(
            "(C) To assess the cooperation the Parties must disclose confidential information to each other. "
            "The Parties therefore agree as follows:", ST_BODY),
    ]


def _signature_block(a: Party, b: Party, sigs: dict[str, Signature]) -> KeepTogether:
    def cell(label: str, party: Party) -> list:
        s = sigs.get(label)
        head = Paragraph(f"<b>Party {label}</b><br/>{escape(party.company_name)}", ST_SMALL)
        if s:
            body = Paragraph(
                f"<font color='#0a6b2a'><b>Accepted electronically</b></font><br/>{escape(s.signer_name)}"
                f"<br/>{escape(s.signer_role)}<br/>{_fmt(s.signed_at)}", ST_SMALL)
        else:
            body = Paragraph("<br/><br/>Place, date<br/><br/>______________________________<br/>"
                             f"{escape(party.representative)}", ST_SMALL)
        return [head, Spacer(1, 6), body]

    t = Table([[cell("A", a), cell("B", b)]], colWidths=[8.3 * cm, 8.3 * cm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEABOVE", (0, 0), (-1, 0), 0.6, colors.HexColor("#999999")),
                           ("TOPPADDING", (0, 0), (-1, -1), 6)]))
    return KeepTogether([Spacer(1, 14), Paragraph("Signatures / electronic acceptance", ST_H), t])


def _protocol(a: Party, b: Party, p: NdaParams, sigs: dict[str, Signature], unsigned_sha256: str) -> list:
    rows = [["Party", "Accepted by", "Designation", "Time", "IP address"]]
    for label, party in (("A", a), ("B", b)):
        s = sigs[label]
        rows.append([f"{label}: {party.company_name}", s.signer_name, s.signer_role, _fmt(s.signed_at), s.ip or "-"])
    return [
        PageBreak(),
        Paragraph("Annexure 1 - Signature log", ST_TITLE),
        Spacer(1, 8),
        Paragraph(f"<b>Agreement:</b> {TITLE} ({TEMPLATE_VERSION})", ST_BODY),
        Paragraph(f"<b>Document ID:</b> {escape(p.nda_id)}", ST_BODY),
        Paragraph(f"<b>Match reference:</b> {escape(p.match_id)}", ST_BODY),
        Paragraph(f"<b>Created:</b> {_fmt(p.created_at)}", ST_BODY),
        Paragraph(f"<b>SHA-256 of the version presented for signature:</b><br/><font face='Courier' size='8.5'>{unsigned_sha256}</font>",
                  ST_BODY),
        Spacer(1, 8),
        table(rows, [4.0, 3.4, 3.0, 3.7, 2.5]),
        Spacer(1, 10),
        Paragraph(
            "Both Parties accepted the text of the Agreement identified by the hash above through the Platform. This is a "
            "simple electronic acceptance (an electronic record attributable to the named signatory under the Information "
            "Technology Act, 2000), not an Aadhaar-based or digital signature certificate signature. Each acceptance was "
            "given by the named person on behalf of the Party shown. The Parties should have this Agreement e-stamped "
            "where required by the law of the state concerned.", ST_BODY),
    ]


def build_nda_pdf(a: Party, b: Party, p: NdaParams, signatures: Optional[dict[str, Signature]] = None,
                  unsigned_sha256: str = "") -> bytes:
    """Render the NDA. With `signatures` (keys "A","B") and the hash of the unsigned PDF, the signed version with the
    signature log is produced."""
    sigs = signatures or {}
    story = _front(a, b, p) + paras(_sections(a, b, p)) + [_signature_block(a, b, sigs)]
    if sigs:
        story += _protocol(a, b, p, sigs, unsigned_sha256)
    footer = f"{TEMPLATE_VERSION} - ID {p.nda_id}" + (" - signed" if sigs else " - draft for acceptance")
    return build_pdf(story, title=TITLE, author=p.platform_name, subject=f"NDA {p.nda_id} (match {p.match_id})",
                     template=TEMPLATE_VERSION, footer=footer)
