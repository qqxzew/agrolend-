# Devfolio description — DRAFT (replace PENDING items with real evidence before submitting)

**Project:** AgroLand — pay-per-result land intelligence on Cardano (Germany and India)

## Problem
Land decisions are made on thin information. A landowner does not know whether a parcel suits wind or solar and what to disclose; a tenant farm pays rent it cannot easily check against contracts, the official record and what it actually farms; an energy developer cannot safely find and approach a neighbouring project. Ownership data is closed in many places, so a tool cannot "look up owners" — it must work with the customer's own documents and the other side's consent, and it must be honest about what it did not check.

## What we built
One product with three equal, fully working entry points:
* **Landowner:** audit a parcel (verdict, geometric signal and data quality shown separately), attach private documents, publish only when you decide, disclose the exact boundary only to developers you accept.
* **Tenant farm:** a *Lease Check* that compares leases, the official parcel record and farmed fields, separates *identified* discrepancies from *negotiable* opportunities and *savings actually achieved*, and produces deadline reminders. Every finding is recomputed from the source rows before delivery.
* **Energy developer:** audit sites for wind/solar/hybrid, get anonymous neighbour teasers, and — after **both** sides consent, **both** payments are locked and **both** sign the NDA — receive the counterpart's details, a preliminary joint calculation (shares in basis points, layout, NPV) and draft agreement/grid-application PDFs.
Germany and India are supported in all three (units, currency, rules, documents, labelled demo datasets).

## How it works and where Cardano fits
Three paid services are separate **Masumi agents** (Land Audit, Lease Check, Pool Access) behind a **MIP-003** API, priced in tUSDM on **Cardano preprod**. Our website, Masumi buyers and a **Sokosumi Coworker** (a language-model concierge with real tools that turns free text into a validated, priced order) all create the *same* order in one engine — no diverging versions. Payment is a Masumi escrow: funds are locked on-chain, the report is delivered, **its hash is written on-chain**, and the seller is paid after the dispute window; if we cannot deliver, no hash is submitted and the buyer uses the protocol refund. We show four separate facts — report ready, funds locked, result hash confirmed, seller paid — and never collapse them. Blockfrost verifies transactions independently.

## Cardano tools
Masumi payment service (Web3CardanoV2 contracts), Masumi registry (agent NFTs), MIP-003/MIP-004, Sokosumi Core payment events, Blockfrost preprod, tUSDM.

## How it works in reality
* Real calculations and services: live BKG/OSM/BfN/PVGIS/Open-Meteo audits, ALKIS geometry, deterministic lease rules, a real matcher/escrow/NDA/architect pipeline run by two test identities. Demonstration parcels, owners and contracts are labelled fictional/illustrative.
* Honest limits: no ownership or planning-permission or grid-availability verification; OSM-based screens in India are of unmeasured completeness; contracts and NDAs are drafts for lawyer review.
* **Evidence:** completed paid job — Sokosumi Task `01a19166-d167-745b-beaa-b58383cedb5d`, order `4f650b39…`, locked `6087b1ff78b9fda9b8bab5da84fde83d5194acf96a1ff6f2de9548865c0aa10d`, result hash `60ce47ffaa92116a1d45cc6d5ec0109c659cc045cde28aa1971d90851920988c`, settlement `607ee2d0f82628ad2162b1b514ab0fb47ceef4eb300905e257b7cb0ce394acc4` (details: docs/EVIDENCE.md).

## Customer and payment model
Customers: a tenant farm paying 2.00 tUSDM to check 22 leases; a developer paying 3.00 tUSDM to open a neighbour introduction; an owner paying 1.00 tUSDM for a parcel audit. Payment is tied to a specific delivered result.

## Links
Repository: https://github.com/qqxzew/agrolend- · Live demo: https://audit.mrrobot.hackclub.app · Demo video (≤ 2.5 min): PENDING
