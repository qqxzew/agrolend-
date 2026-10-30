"""English draft documents for an Indian pool: Land Pooling Agreement (draft) and Grid Connectivity Application (PDF).

Both are TEMPLATES generated from the computed plan, drafts for review by an Indian advocate - the agreement touches
company/LLP law, land and tenancy law (leases of one year or more need a registered instrument under s.107 of the
Transfer of Property Act, 1882 and the Registration Act, 1908; agricultural land is subject to state-specific
restrictions on use, conversion and lease) and tax. Only WinAnsi characters are used, so the rupee sign is written "INR".
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from xml.sax.saxutils import escape

from reportlab.platypus import PageBreak, Paragraph, Spacer

from ..common.pdfkit import ST_BODY, ST_H, ST_ITEM, ST_PARTY, ST_SMALL, ST_SUB, ST_TITLE, build_pdf, inr, num, paras, table
from ..escrow.nda import Party

POOL_TEMPLATE = "POOL-IN-1.0"
GRID_TEMPLATE = "GRID-IN-1.0"
PLACEHOLDER = "[to be completed]"


@dataclass
class DocParams:
    pool_id: str
    match_id: str
    created_at: datetime
    platform_name: str = "India Land Pooling Platform"
    nda_sha256: str = ""
    nda_id: str = ""
    arbitration_seat: str = "New Delhi"
    exclusivity_months: int = 24
    term_years: int = 30


def _pct(bp: int) -> str:
    return f"{bp / 100:.2f} %"


def _party(p: dict[str, Any]) -> Party:
    c = p["company"]
    return Party(company_name=c["company_name"], address=c["address"], state=c["state"], pin_code=c["pin_code"],
                 representative=c["representative"], registration=c.get("registration_no", ""), gstin=c.get("gstin", ""),
                 email=c.get("email", ""))


def _tech(t: str) -> str:
    return {"wind": "Wind energy", "solar": "Solar photovoltaic"}.get(t, t)


def _loc(p: dict[str, Any]) -> str:
    return ", ".join(x for x in (p.get("village"), p.get("district"), p.get("state")) if x) or "-"


def _route_text(plan: dict[str, Any]) -> str:
    return ("the Central Transmission Utility of India Limited (CTUIL) under the CERC connectivity regulations"
            if plan["grid_route"]["route"] == "ctu" else
            "the state transmission utility or distribution licensee under the applicable State Grid Code")


# ================================================================== Land Pooling Agreement


def _pool_sections(plan: dict[str, Any], pa: Party, pb: Party, params: DocParams) -> list[tuple[str, list[str]]]:
    bp = plan["shares_bp"]
    method = {"shapley": "the Shapley value (each Party keeps the value of developing its land alone and the cooperation gain "
                         "is split equally)",
              "area": "the ratio of the contributed land areas",
              "revenue": "the ratio of the annual revenues attributable to the respective land"}[plan["method_applied"]]
    jp = plan["joint_project"]
    return [
        ("1. Subject matter and purpose", [
            "1.1 The Parties intend to jointly develop, build and operate a renewable energy project on their neighbouring "
            "land described in Annexure 1 (the \"Project\") and to pool their land rights for this purpose.",
            f"1.2 According to the preliminary design in Annexure 2, the Project comprises an installed capacity of about "
            f"{num(jp['capacity_mw'], 1)} MW. Annexure 2 is a rough pre-feasibility estimate, not a permitting or detailed design.",
            "1.3 This Agreement governs the cooperation until the Project Company is incorporated and its principal "
            "terms. Matters that need a registered or notarised instrument (including leases and the articles/LLP "
            "agreement) are carried into separate instruments.",
        ]),
        ("2. Project Company", [
            "2.1 The Parties shall incorporate a special purpose vehicle for the Project as a private limited company under "
            "the Companies Act, 2013 or as a limited liability partnership under the Limited Liability Partnership Act, 2008 "
            f"[form to be agreed] with its registered office in {PLACEHOLDER} (the \"Project Company\"). Until then the Parties "
            "co-operate on a contractual basis only; this Agreement does not create a partnership.",
            "2.2 The Parties hold the Project Company in accordance with clause 3. The holdings also determine voting rights, "
            "capital contributions, distributions and liquidation proceeds unless the constitutional documents say otherwise.",
        ]),
        ("3. Shareholding", [
            f"3.1 The holdings are: Party A {_pct(bp['A'])}, Party B {_pct(bp['B'])}.",
            f"3.2 The holdings were derived from {method} on the basis of the calculation in Annexure 2, which relies on "
            "standard assumptions and public data; it is non-binding and to be verified by the Parties.",
            "3.3 If before the award of the power purchase agreement, or before the start of construction, material "
            "circumstances change (in particular number or capacity of turbines or the solar area, turbine sites, loss or "
            "limitation of a parcel, changed connectivity costs), the Parties shall renegotiate the holdings in good faith. "
            "Failing agreement within 60 days, an independent expert nominated by the president of the Institute of "
            "Chartered Accountants of India (or the nearest regional council) decides as expert, not arbitrator, on the "
            "valuation question only.",
        ]),
        ("4. Land; securing the land rights", [
            "4.1 Each Party shall make the land described in Annexure 1 available for the Project according to the project "
            "design and shall procure that the Project Company receives the necessary rights of use - by assignment, "
            "sub-lease or a fresh lease from the owners (including leases, licences and rights of way).",
            "4.2 Each lease of one year or more is to be made by a registered instrument (section 107 of the Transfer of "
            "Property Act, 1882 and the Registration Act, 1908), duly stamped under the law of the state concerned. A "
            "sub-lease or assignment requires the lessor's written consent where the lease so provides.",
            "4.3 Agricultural land is subject to state law on its use, conversion to non-agricultural use and lease to "
            "non-agriculturists, and to permissions (for example from the revenue authorities). Each Party shall obtain, at "
            "its own cost, the permissions required for its land, and shall inform the other Party promptly of any "
            "restriction or refusal.",
            "4.4 Each Party represents that it holds a lease, option or comparable right in the land listed in Annexure 1, "
            "that it knows of no conflicting third-party right, that survey numbers and any ULPIN given are correct, and "
            "that the audit's screening result is not a verification of title. Each Party shall verify title with the "
            "land-record authority of the state concerned before signing the leases for the Project Company.",
            "4.5 The relationships with the owners of its own land remain with that Party until the Project Company has "
            "entered into the land agreements. The non-circumvention clause of the NDA remains unaffected.",
        ]),
        ("5. Costs and financing", [
            "5.1 Development costs up to financial close (surveys, resource assessment, permits, legal work, connectivity "
            "study, securing the land) are borne by the Parties in proportion to the holdings in clause 3. They were "
            f"estimated at {inr(jp['development_cost_inr'])} in Annexure 2.",
            "5.2 The Parties provide the equity of the Project Company in proportion to their holdings and aim to finance "
            "the Project with third-party project finance. Security is provided only with the consent of the Party concerned.",
            "5.3 Advances by one Party beyond its holding are to be made to the Project Company as a loan on market terms "
            "or settled otherwise.",
        ]),
        ("6. Grid connectivity and offtake", [
            f"6.1 The Parties shall apply for common grid connectivity with {_route_text(plan)}. The connectivity "
            "application (a draft is generated separately) is filed by the Project Company, or by the Parties jointly until "
            "it exists. Connectivity charges and any security are borne by the Project Company.",
            f"6.2 For the common evacuation, connection costs of about {inr(jp['grid_connection_cost_inr'])} were assumed "
            f"(including about {num(jp['internal_line_m'])} m of internal line between the parcels). This is an estimate; "
            "only the figures of the transmission utility or licensee are binding.",
            "6.3 Sale of power (a power purchase agreement with a distribution licensee or SECI-type intermediary, open access "
            "or captive/group-captive supply) is decided by unanimous vote after the connectivity result is known.",
        ]),
        ("7. Management and decisions", [
            f"7.1 The Project Company is managed by {PLACEHOLDER}. Shareholder decisions are taken by simple majority of "
            "the votes according to the holdings unless stated otherwise.",
            f"7.2 A unanimous decision is needed for: amendment of the constitutional documents, admission of new owners, "
            f"sale of the Project or substantial parts of it, capital measures, borrowing above INR {PLACEHOLDER}, related-party "
            "contracts, and changes to the number or sites of the turbines or the solar area.",
        ]),
        ("8. Revenues and distributions", [
            "Revenues from operation are distributed to the owners in proportion to their holdings after deduction of "
            "operating costs, debt service and reasonable reserves and subject to the distribution rules of the Companies "
            "Act, 2013 or the LLP Agreement. Lease rent payable to landowners is borne by the Project Company as an operating cost.",
        ]),
        ("9. Exclusivity", [
            f"9.1 For {params.exclusivity_months} months from signature, each Party shall not develop a competing project on "
            "the land in Annexure 1, nor negotiate with third parties about its use for renewable energy.",
            "9.2 If the Project ends finally (in particular permits refused without prospect of success, or final refusal "
            "of connectivity), the exclusivity ends six months afterwards.",
            "9.3 The Parties consider these restrictions, which apply only during the stated term and only to the land and "
            "Project concerned, reasonable and necessary to protect the cooperation; they are not intended to restrain any "
            "person from carrying on a lawful profession, trade or business (section 27 of the Indian Contract Act, 1872).",
        ]),
        ("10. Confidentiality", [
            "The mutual non-disclosure and non-circumvention agreement between the Parties"
            + (f" (ID {params.nda_id}, SHA-256 {params.nda_sha256})" if params.nda_sha256 else "")
            + " continues to apply to this Agreement and the Project; the content of this Agreement is Confidential Information under it.",
        ]),
        ("11. Transfer, pre-emption and exit", [
            "11.1 Shares or LLP interests may be transferred only with the other Party's consent. The other Party has a "
            "right of first refusal on the terms offered by a third party.",
            "11.2 If the Project fails, each Party bears its share of the costs under clause 5. The land rights revert "
            "unencumbered to the contributing Party.",
            "11.3 The right to terminate for material breach by 30 days' written notice remains unaffected.",
        ]),
        ("12. Term", [
            f"This Agreement runs until the Project Company has been incorporated and has entered into the land agreements, and for "
            f"no longer than {params.term_years} years from signature; the constitutional documents then take precedence.",
        ]),
        ("13. Stamp duty, general provisions, governing law and disputes", [
            "13.1 Stamp duty on this Agreement and on the leases and constitutional documents is borne by the Parties in "
            "proportion to their holdings unless the law or the instrument says otherwise. Where required, each Party shall "
            "arrange e-stamping.",
            "13.2 Amendments must be in writing signed by both Parties. The Annexures form part of this Agreement. If any "
            "provision is invalid or unenforceable, the rest remains in force and the Parties shall replace it with a valid "
            "one that comes closest to its commercial purpose.",
            "13.3 This Agreement is governed by the laws of India. Disputes are finally resolved by arbitration under the "
            "Arbitration and Conciliation Act, 1996 before a sole arbitrator appointed by agreement or, failing agreement "
            f"within 30 days, by the competent court; seat and venue: {params.arbitration_seat}; language: English. Each Party "
            "may seek interim relief from any court of competent jurisdiction.",
        ]),
    ]


def _plan_tables(plan: dict[str, Any], package: dict[str, Any]) -> list:
    jp = plan["joint_project"]
    pa, pb = plan["parties"]
    fa, fb = package["parties"][0]["parcel"], package["parties"][1]["parcel"]
    rows1 = [["", "Party A", "Party B"],
             ["Company", pa["company_name"], pb["company_name"]],
             ["Area (ha)", num(fa["area_ha"], 2), num(fb["area_ha"], 2)],
             ["Village / district / state", _loc(fa), _loc(fb)],
             ["Survey / khasra number (as given)", fa.get("survey_number") or "-", fb.get("survey_number") or "-"],
             ["ULPIN (as given)", fa.get("ulpin") or "-", fb.get("ulpin") or "-"],
             ["Technology", _tech(pa["parcel"]["technology"]), _tech(pb["parcel"]["technology"])],
             ["Audit (verdict / score)", f"{fa['verdict']} / {fa['score']}", f"{fb['verdict']} / {fb['score']}"]]
    rows2 = [["", "Party A", "Party B"],
             ["Capacity in the Project (MW)", num(pa["in_joint_project"]["capacity_mw"], 2), num(pb["in_joint_project"]["capacity_mw"], 2)],
             ["Annual energy (MWh/a)", num(pa["in_joint_project"]["energy_mwh_a"]), num(pb["in_joint_project"]["energy_mwh_a"])],
             ["Annual revenue", inr(pa["in_joint_project"]["revenue_inr_a"]), inr(pb["in_joint_project"]["revenue_inr_a"])],
             ["Lease cost, first year", inr(pa["in_joint_project"]["lease_inr_first_year"]), inr(pb["in_joint_project"]["lease_inr_first_year"])],
             ["Standalone: net present value", inr(pa["standalone"]["npv_inr"]), inr(pb["standalone"]["npv_inr"])],
             ["Value contribution (Shapley)", inr(pa["value_contribution_shapley_inr"]), inr(pb["value_contribution_shapley_inr"])],
             ["Share by area", _pct(pa["share_bp"]["area"]), _pct(pb["share_bp"]["area"])],
             ["Share by revenue", _pct(pa["share_bp"]["revenue"]), _pct(pb["share_bp"]["revenue"])],
             ["Share by Shapley value", _pct(pa["share_bp"]["shapley"]), _pct(pb["share_bp"]["shapley"])],
             ["Agreed share", _pct(pa["share_bp"]["chosen"]), _pct(pb["share_bp"]["chosen"])]]
    syn = plan["synergy"]
    rows3 = [["Joint Project", "Value"],
             ["Capacity (MW)", num(jp["capacity_mw"], 2)], ["Annual energy (MWh/a)", num(jp["energy_mwh_a"])],
             ["Annual revenue", inr(jp["revenue_inr_a"])], ["Plant investment", inr(jp["capex_inr"])],
             ["Lease cost, first year", inr(jp["lease_inr_first_year"])],
             ["Grid connection", inr(jp["grid_connection_cost_inr"])], ["Development costs", inr(jp["development_cost_inr"])],
             ["Net present value, joint", inr(jp["npv_inr"])],
             ["Cooperation gain", inr(syn["total_inr"])],
             ["  of which saved grid costs", inr(syn["grid_savings_inr"])],
             ["  of which saved development costs", inr(syn["development_savings_inr"])]]
    a = plan["assumptions"]
    return [
        Paragraph("Annexure 1 - Land", ST_H), table(rows1, [5.0, 5.8, 5.8]),
        Spacer(1, 10),
        Paragraph("Annexure 2 - Calculation of the holdings (pre-feasibility)", ST_H),
        table(rows3, [10.0, 6.6]), Spacer(1, 8), table(rows2, [6.2, 5.2, 5.2]),
        Spacer(1, 6),
        Paragraph(escape(f"Net present values: discounted over the term minus investment, grid connection and development "
                         f"costs, with lease rent escalating by {a['lease_escalation_per_year'] * 100:.1f} % a year; discount rate "
                         f"{a['discount_rate'] * 100:.1f} %, {a['lifetime_years']} years. Grid route: "
                         f"{plan['grid_route']['route'].upper()} ({plan['grid_route']['reason']}). Standard assumptions "
                         "(screening model), not a bankable financial model."), ST_SMALL),
    ]


def build_pool_agreement_pdf(plan: dict[str, Any], package: dict[str, Any], params: DocParams) -> bytes:
    pa, pb = (_party(p) for p in package["parties"])
    story: list = [
        Paragraph("Land Pooling Agreement", ST_TITLE),
        Paragraph(f"Co-operation and pooling agreement - DRAFT - template {POOL_TEMPLATE}", ST_SUB),
        Paragraph("This Agreement is made between", ST_BODY),
        Paragraph(pa.block() + "<br/>(\"<b>Party A</b>\")", ST_PARTY),
        Paragraph("and", ST_BODY),
        Paragraph(pb.block() + "<br/>(\"<b>Party B</b>\")", ST_PARTY),
        Paragraph("Party A and Party B are together the \"Parties\".", ST_BODY),
        Paragraph("Recitals", ST_H),
        Paragraph(escape(
            f"The Parties were introduced through the platform \"{params.platform_name}\" under match reference {params.match_id} "
            "and have entered into a mutual non-disclosure and non-circumvention agreement. They wish to develop their "
            "neighbouring land jointly. The operator of the Platform is not a party to this Agreement and gives no "
            "warranty for the calculations."), ST_BODY),
    ]
    story += paras(_pool_sections(plan, pa, pb, params))
    story += [Spacer(1, 16), Paragraph("Signatures", ST_H),
              table([["Party A", "Party B"],
                     [f"Place, date\n\n\n______________________________\n{pa.company_name}\n{pa.representative}",
                      f"Place, date\n\n\n______________________________\n{pb.company_name}\n{pb.representative}"]], [8.3, 8.3]),
              PageBreak()]
    story += _plan_tables(plan, package)
    story += [Spacer(1, 6), Paragraph("Annexure 3 - Grid connectivity application (separate document)", ST_H)]
    if plan["warnings"]:
        story += [Paragraph("Notes on the calculation", ST_H)] + [Paragraph(escape("- " + w), ST_ITEM) for w in plan["warnings"]]
    story.append(Paragraph(escape(
        "This document is a machine-generated draft and is no substitute for legal advice. Before signing, review by an "
        "advocate enrolled in India, and tax advice, are required; leases and constitutional documents need their own "
        "registered and stamped instruments."), ST_SMALL))
    return build_pdf(story, title="Land Pooling Agreement (draft)", author=params.platform_name,
                     subject=f"Land Pooling Agreement (match {params.match_id})", template=POOL_TEMPLATE,
                     footer=f"{POOL_TEMPLATE} - ID {params.pool_id} - draft")


# ================================================================== Grid Connectivity Application


def build_grid_application_pdf(plan: dict[str, Any], package: dict[str, Any], params: DocParams,
                               operator: Optional[str] = None, substation: Optional[str] = None) -> bytes:
    pa, pb = (_party(p) for p in package["parties"])
    jp = plan["joint_project"]
    wind = jp["wind_turbines"]
    n_turb = sum(len(v) for v in wind.values())
    fa, fb = package["parties"][0]["parcel"], package["parties"][1]["parcel"]
    techs = sorted({p["parcel"]["technology"] for p in plan["parties"]})
    kind = " and ".join(_tech(t) for t in techs)
    date = params.created_at.astimezone(timezone.utc).strftime("%d %b %Y")
    central = plan["grid_route"]["route"] == "ctu"
    dists = [p["parcel"]["distance_to_substation_m"] for p in plan["parties"] if p["parcel"]["distance_to_substation_m"] is not None]
    addressee = ("The Central Transmission Utility of India Limited (CTUIL)<br/>Connectivity and GNA Cell" if central else
                 escape(operator or f"{PLACEHOLDER} (state transmission utility / distribution licensee)") + "<br/>Grid connectivity section")
    legal = ("the Central Electricity Regulatory Commission (Connectivity and General Network Access to the inter-State "
             "Transmission System) Regulations, 2022, the Electricity Act, 2003 and the Central Electricity Authority "
             "(Technical Standards for Connectivity to the Grid) Regulations, 2007"
             if central else
             "the Electricity Act, 2003, the State Grid Code and the connectivity regulations of the State Electricity "
             "Regulatory Commission concerned, and the Central Electricity Authority (Technical Standards for Connectivity "
             "to the Grid) Regulations, 2007")

    story: list = [
        Paragraph(escape(f"{pa.company_name} - {pb.company_name}"), ST_SMALL),
        Spacer(1, 10),
        Paragraph(addressee, ST_BODY),
        Spacer(1, 8),
        Paragraph(escape(date), ST_BODY),
        Paragraph("Application for grid connectivity for a generating project", ST_TITLE),
        Paragraph(escape(f"{kind} - approx. {num(jp['capacity_mw'], 1)} MW - {_loc(fa)} - template {GRID_TEMPLATE}"), ST_SUB),
        Paragraph("Sir / Madam,", ST_BODY),
        Paragraph(escape(
            f"We plan to build and operate a generating project ({kind}) jointly and apply for connectivity to your network and "
            f"for evacuation of the power generated, in accordance with {legal}. We request that you examine the "
            "application, identify the point of connection, confirm the grid connectivity with a cost estimate, and send us "
            "a schedule for the further steps. If a prescribed online application or format applies, please let us know; "
            "the particulars below can be transferred into it. Application fees and security are to be confirmed per the "
            f"procedure in force {PLACEHOLDER}."), ST_BODY),
        Paragraph("1. Applicants", ST_H),
        Paragraph(pa.block() + "<br/>(Party A)", ST_PARTY),
        Paragraph(pb.block() + "<br/>(Party B)", ST_PARTY),
        Paragraph(escape("The applicants intend to incorporate a special purpose vehicle for the project, which will take over "
                         "this application. Contact for queries: " + (pa.email or PLACEHOLDER) + "."), ST_BODY),
        Paragraph("2. Project data (pre-feasibility)", ST_H),
        table([
            ["Type of generation", kind], ["Installed capacity", f"approx. {num(jp['capacity_mw'], 2)} MW"],
            ["Expected annual generation", f"approx. {num(jp['energy_mwh_a'])} MWh/a"],
            ["Wind turbines", f"{n_turb} units of {num(plan['assumptions']['wind_rated_mw'], 1)} MW, rotor diameter "
                              f"{num(plan['assumptions']['wind_rotor_diameter_m'])} m" if n_turb else "-"],
            ["Solar photovoltaic", "; ".join(f"Party {p['label']}: {num(p['in_joint_project']['capacity_mw'], 2)} MWp"
                                             for p in plan["parties"] if p["parcel"]["technology"] == "solar") or "-"],
            ["Connectivity route", ("Inter-State (CTU / ISTS)" if central else "Intra-State (STU / distribution licensee)")
             + f" - {plan['grid_route']['reason']}"],
            ["Voltage level requested", "To be determined by the utility's study"],
            ["Desired date of commissioning", PLACEHOLDER],
            ["Proposed point of connection (suggestion)", (substation or "nearest substation per OpenStreetMap")
             + (f", about {num(min(dists))} m away" if dists else "")],
        ], [5.5, 11.1], header=False),
        Paragraph("3. Location", ST_H),
        table([["Site", "Village / district / state", "Survey number (as given)", "ULPIN (as given)", "Area (ha)"],
               ["Party A", _loc(fa), fa.get("survey_number") or "-", fa.get("ulpin") or "-", num(fa["area_ha"], 2)],
               ["Party B", _loc(fb), fb.get("survey_number") or "-", fb.get("ulpin") or "-", num(fb["area_ha"], 2)]],
              [1.8, 5.0, 3.6, 3.6, 2.6]),
    ]
    if n_turb:
        rows = [["Turbine", "Party", "Latitude (WGS84)", "Longitude (WGS84)"]]
        i = 1
        for lab, pts in wind.items():
            for p in pts:
                rows.append([f"WTG {i}", lab, num(p["lat"], 6), num(p["lon"], 6)])
                i += 1
        story += [Spacer(1, 6), Paragraph(escape("Preliminary turbine sites (design stage, not approved):"), ST_BODY),
                  table(rows, [3.0, 2.5, 5.5, 5.6])]
    story += [
        Paragraph("4. Information requested", ST_H),
        Paragraph(escape("(a) point of connection and voltage level, (b) available evacuation capacity and required network "
                         "reinforcement, (c) estimated connectivity charges and security, (d) schedule for the system study, "
                         "the grant of connectivity and realisation, (e) your technical conditions and the documents to be "
                         "submitted, (f) rules on scheduling, forecasting and curtailment that will apply."), ST_BODY),
        Paragraph("5. Notes", ST_H),
        Paragraph(escape("The particulars come from a rough pre-feasibility; capacity, number of units and sites can change during "
                         "permitting. Land rights are being secured by the applicants; documentary proof of control of the land "
                         "will be furnished as required. Please acknowledge receipt in writing. A power of attorney or board "
                         "resolution of the signatories can be furnished on request."), ST_BODY),
        Paragraph("Yours faithfully,", ST_BODY),
        Spacer(1, 8),
        table([["Party A", "Party B"],
               [f"\n\n______________________________\n{pa.company_name}\n{pa.representative}",
                f"\n\n______________________________\n{pb.company_name}\n{pb.representative}"]], [8.3, 8.3]),
        Spacer(1, 10),
        Paragraph(escape(f"Enclosures: site plan / parcel boundaries (from the land audit, match {params.match_id}); layout plan with "
                         f"turbine or array locations {PLACEHOLDER}; land documents {PLACEHOLDER}; authority letters {PLACEHOLDER}."), ST_SMALL),
        Paragraph(escape("Machine-generated draft; check the content and complete the placeholders in square brackets before sending."), ST_SMALL),
    ]
    return build_pdf(story, title="Grid Connectivity Application (draft)", author=params.platform_name,
                     subject=f"Grid Connectivity Application (match {params.match_id})", template=GRID_TEMPLATE,
                     footer=f"{GRID_TEMPLATE} - ID {params.pool_id} - draft")
