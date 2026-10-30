"""TESTING stub of the audit service (German stack): returns a fixed GO report so pool tests do not depend on live geodata."""
import os
from fastapi import FastAPI, Header, HTTPException, Body

app = FastAPI()


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/internal/audit")
def audit(body: dict = Body(...), x_api_key: str = Header(default="")):
    if x_api_key != os.environ["INTERNAL_API_KEY"]:
        raise HTTPException(401)
    report = {"overall_verdict": "GO", "score": 85, "project_type": body.get("project_type", "hybrid"), "assessed_technology": body.get("project_type", "wind"),
              "warnings": [], "location_info": {"bundesland": "Sachsen-Anhalt", "municipality": "Magdeburg", "state": "Gujarat", "state_code": "IN-GJ", "district": "Kutch", "sub_district": "Bhuj", "village": "Demo", "area_hectares": 5.0, "alkis_parcel_id": None},
              "technology_assessment": {}, "data_quality": {},
              "resource_potential": {"solar_kwh_per_kwp_year": 1010.0, "wind_speed_100m_ms": 6.9, "slope_degrees": 2.5},
              "grid_access": {"nearest_substation_m": 2500.0, "substation_name": "UW Testdorf", "substation_operator": "Test Netz GmbH", "nearest_powerline_m": 400.0}}
    return {"status": "completed", "report": report}
