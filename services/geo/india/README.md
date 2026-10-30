# India agents — wind & solar (Andhra Pradesh + Gujarat)

The same four-agent pipeline as the German stack (audit a parcel → find neighbours → escrow + NDA → pool architect),
rebuilt for India. It lives entirely in `india/` and **does not touch the German agents**: own packages, own `IN_*`
environment variables, own databases, own ports (9000–9003), own Masumi registry entries. The only shared things are the
Masumi payment service, the Preprod wallet and the `MASUMI_*` connection variables.

| # | Agent | Port | Package | What it does |
|---|-------|------|---------|--------------|
| 1 | Land audit | 9000 | `india/audit` | MIP-003 agent. Pays via Masumi, then scores a parcel (GO / CONDITIONAL_GO / NO_GO) for solar and wind |
| 2 | Matcher | 9001 | `india/matcher` | Registers audited parcels, finds other developers' parcels within 1.5 km, sends anonymous teasers |
| 3 | Escrow & NDA | 9002 | `india/escrow` | Consent → two Masumi deposits → English NDA (PDF) → electronic acceptance → reveal |
| 4 | Pool architect | 9003 | `india/architect` | Joint layout and economics in INR, Shapley/area/revenue shares, draft Land Pooling Agreement + Grid Connectivity Application |

Endpoints are the same as in the German stack (`/availability`, `/input_schema`, `/start_job`, `/status` for Agent 1,
`/register_parcel`, `/teasers`, `/parcels`, `/deals/...`, `/pools/...`, internal `X-API-Key` routes for agent-to-agent
calls). Documents are in English. Payment is Masumi **Preprod, Web3CardanoV2** (`paymentSourceType`,
`supportedPaymentSourceIndex`, `RequestedFunds` are sent when configured).

## Run it

```bash
# no blockchain: India Agent 1 only, payment bypassed (default)
docker compose -f docker-compose.yml -f india/docker-compose.india.yml up -d --build in-audit-worker
# all four India agents (+ the German stack and the payment service from the base file)
docker compose -f docker-compose.yml -f india/docker-compose.india.yml up -d --build
```

Without Docker: `uvicorn india.audit.main:app --port 9000`, `india.matcher.main:app --port 9001`,
`india.escrow.main:app --port 9002`, `india.architect.main:app --port 9003`. Variables: see the INDIA section of
`.env.example`. Each settings class reads only its own `IN_<AGENT>_*` names plus the shared `MASUMI_*`; a German
`.env` value such as `ESCROW_API_KEY` is not picked up by the India agents (checked).

Tests (offline, standalone scripts like the German ones; they use `_env_file=None` so a local `.env` cannot leak in):

```bash
python tests/test_india_audit.py          # geometry, scoring rules, MIP-003 flow with a stubbed GIS engine
python tests/test_india_payment_flow.py   # paid mode against a fake Masumi payment service (V2 payload, refund path)
python tests/test_india_matcher.py
python tests/test_india_escrow.py         # incl. paid mode: funds released only after both acceptances
python tests/test_india_architect.py
python test_worker_india.py               # LIVE: real OSM / PVGIS / Open-Meteo calls for 3 sites (needs internet)
```

## Registering the India agents in Masumi

The India agents are **separate Masumi agents** with their own identifiers (do not reuse the German ones). Register
Agent 1 and Agent 3 (the two that sell a service) in the payment-service admin UI and put the identifiers into
`IN_AUDIT_AGENT_IDENTIFIER` and `IN_ESCROW_AGENT_IDENTIFIER`; set `IN_AUDIT_BYPASS_PAYMENT=false` /
`IN_ESCROW_BYPASS_PAYMENT=false` to go live. Agents 2 and 4 are internal for now (called by the orchestrator with
`X-API-Key`).

## Data sources

| Check | Source | Notes |
|-------|--------|-------|
| State / district / village | OSM Nominatim reverse geocoding | 1 request/s, best effort. In Gujarat the "county" tag can be a district, so `sub_district` (taluka/mandal) is best effort |
| Substations, power lines, roads, existing turbines | OSM via Overpass | Three public mirrors, queries serialised and hedged. OSM completeness in rural India was **not measured** |
| Habitation | OSM places, residential landuse, building clusters | A habitation = cluster of ≥ 15 buildings within 100 m (MNRE 2024 definition), residential landuse or a place node |
| Protected areas, forest/wetland/water cover | OSM (`is_in` area tests + buffer search) | No authoritative open layer exists for India (WDPA withholds many Indian polygons) — see limits |
| Solar yield | EU JRC PVGIS 5.3 (`v5_3/PVcalc`, ERA5-based in India) | kWh/kWp/year at optimal tilt |
| Wind speed | Open-Meteo ERA5 archive, 100 m | Annual mean over a **fixed period** (2022-01-01 … 2024-12-31) so reports are reproducible |
| Slope | Open-Meteo elevation API (Copernicus DEM 90 m), 3×3 Horn | |
| Land record | user-supplied survey number / ULPIN | Format check only (ULPIN = 14 alphanumerics). **Never verified**: no state offers a public API |

Metric work (areas, distances, turbine layout) is done in the **local UTM zone** of each geometry — India spans zones
42–47 and single-CRS projections measured 2 % (EPSG:7755 in Gujarat) to 10 % (ESRI:102028) scale error.

## Scoring (all constants in `india/audit/scoring.py`)

* Verdict: score ≥ 65 and no condition → GO; blocker or score < 40 → NO_GO; otherwise CONDITIONAL_GO. A site-wide
  condition (no land-record reference, unsupported state, protected area within 1 km of the site, a failed core check)
  can never give an unconditional GO.
* **Veto** (NO_GO, score capped at 10): National Park, Wildlife/bird sanctuary, Tiger reserve or Reserved Forest
  inside the site. Protected Forest, conservation/community reserve, biosphere reserve, Ramsar and other protected areas
  cost 15 points and block GO instead.
* Solar: resource 30 (1300 → 1750 kWh/kWp), grid 25, terrain 15, access + cover 20, size 10. Wind: wind speed 35
  (4.5 → 7.0 m/s; below 4.5 is a blocker, below 5.5 a condition), setback 25 (habitation ≥ 500 m full, 250–500 m
  condition, < 250 m blocker — **SCREENING** values, India has no national wind setback), grid 20, terrain 10, access 7.
* Grid hint: state STU/discom (GETCO, APTRANSCO …) or central CTU/CTUIL when the nearest node looks like an ISTS
  substation (CERC GNA Regulations 2022).

## Pool model (Agent 4)

Deterministic screening model in INR (`india/architect/model.py`, every default is an overridable `Assumptions` field):
turbine layout by greedy packing at 4 rotor diameters, solar capacity from area/slope, capex/opex/tariff, **lease cost
per hectare with yearly escalation** (land is leased from farmers), discount rate 9 %, 25 years, grid connection fixed
cost by route (state or central) plus line cost. Shares: Shapley (default), area or revenue, in basis points summing to
exactly 10 000; Shapley falls back to the area key with a warning when pooling does not create value. The defaults are
placeholders for AP/Gujarat utility-scale projects — **check them against current SECI/state auction results, capex
quotes and local lease rates before showing numbers to anyone.**

## Documents (English, templates)

* **NDA-IN-1.0** — mutual NDA and non-circumvention. Non-circumvention is in-term only (a post-term restraint of trade
  is void under s.27 Indian Contract Act); the stipulated sum is limited to reasonable compensation under s.74 with an
  INR cap (`IN_ESCROW_NDA_MAX_COMPENSATION_INR`); arbitration seated in India (Arbitration and Conciliation Act, 1996);
  DPDP Act 2023 clause; stamp duty / e-stamp clause; acceptance as an electronic record (IT Act 2000), not an
  Aadhaar/DSC signature; the signed PDF carries a signature log with the SHA-256 of the presented version.
* **POOL-IN-1.0** — Land Pooling Agreement draft: SPV as a private limited company or LLP, holdings from the plan,
  leases of one year or more by registered, stamped instrument (TPA s.107, Registration Act 1908), state permissions for
  agricultural land, unanimity matters, in-term exclusivity, right of first refusal, arbitration.
* **GRID-IN-1.0** — Grid Connectivity Application draft, state (STU/discom) or central (CTUIL) variant, with plant data,
  parcels (village/district/state, survey number, ULPIN as supplied) and preliminary turbine coordinates. Fees and
  security are left as placeholders to confirm against the procedure in force.

All three are machine-generated templates. **Have an Indian advocate review them** and check the stamp duty of the state
concerned before production use.

## Known limits (read before relying on a report)

* **Title is never verified.** Revenue records (7/12, Adangal, RTC) are not conclusive proof of title; the report says so
  in `warnings` and `location_info.land_record`.
* **Protected-area and habitation screens are OpenStreetMap-based**, and OSM completeness in rural India was not measured
  (the public Overpass servers were overloaded when we tried). Failed or empty sources are reported in `data_quality` /
  `warnings`, never filled in. A missing polygon means "not found", not "not protected": verify on PARIVESH and with the
  state forest department.
* **Wind is an ERA5 reanalysis mean (~25 km grid)** and under-reads hills and coasts; it is a screening number, not a wind
  study (NIWE / on-site measurement needed).
* **The free Open-Meteo API is non-commercial.** For a commercial service set `IN_AUDIT_OPEN_METEO_API_KEY`. The public
  Nominatim and Overpass servers also have usage policies — host your own instances before production load.
* Andhra Pradesh's Mee Bhoomi-Blockchain pilot (permissioned Hyperledger Fabric, no public read access) is only flagged
  when the OSM name of the mandal/village matches a known pilot mandal; the list is from desk research and should be
  re-verified.
* Only Andhra Pradesh (IN-AP) and Gujarat (IN-GJ) carry state-specific knowledge; other states get a site-wide condition.
* Agricultural-land lease/conversion rules differ by state; the agreement only flags them, it does not resolve them.
