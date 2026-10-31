"""Offline test of the 5am.earth (Project Swaminathan) registry module. Fixtures are the real mainnet datum/transaction
shape recorded from tx 746c7d4c...cb04 (no network, no invented values).

    python tests/test_india_registry.py
"""
import asyncio
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from india.registry.swaminathan import (  # noqa: E402
    ASSET_NAME_HEX, POLICY_ID, REGISTRY_ADDRESS, SwaminathanRegistry, cid_v0_of, decode_farm_datum, in_coverage, parcel_overlap, parse_document, local_fingerprint,
    report_context,
)

DATUM = {"list": [{"bytes": "313532343531"}, {"bytes": "313038323936"}, {"bytes": "53594e47303031303033"}, {"int": 1199},
                  {"bytes": "697066733a2f2f516d5843334473327846355933447a62365731356e58397a545432334d6d584a4e4b755567724545474844566851"},
                  {"int": 75}, {"bytes": "d87980"}]}
TX = "746c7d4c018db75d8b266271291c6c26638a4466fff92bf5a1d3678f3245cb04"


def tx_info(origin=REGISTRY_ADDRESS, token=True):
    out = [{"payment_addr": {"bech32": "addr1q85m2c3neffh4d4np9hgsm622naa97ujkjem75kcu8n3c25rc9kn6q6sl4uj0ymn3xu3gxffn7gna6z32952k0axuhwsn9aj4t"},
            "asset_list": []}]
    if token:
        out.append({"payment_addr": {"bech32": "addr1w8z0xlftcx54tn7uxdvhk0qgj9u7hmlaccjthnc9kvu4pmcyemglm"}, "datum_hash": "8c97",
                    "asset_list": [{"policy_id": POLICY_ID, "asset_name": ASSET_NAME_HEX, "quantity": "1"}]})
    return [{"tx_hash": TX, "tx_timestamp": 1793411733, "metadata": None, "inputs": [{"payment_addr": {"bech32": origin}}], "outputs": out}]


def registry(**kw):
    def handler(req: httpx.Request) -> httpx.Response:
        p = req.url.path
        if p.endswith("/tx_info"):
            return httpx.Response(200, json=tx_info(**kw))
        if p.endswith("/datum_info"):
            return httpx.Response(200, json=[{"value": DATUM}])
        if p.endswith("/address_txs"):
            return httpx.Response(200, json=[{"tx_hash": TX}])
        return httpx.Response(503)  # IPFS gateways down, as seen live

    return SwaminathanRegistry(httpx.AsyncClient(transport=httpx.MockTransport(handler)), gateways=["https://gw.invalid/ipfs"])


def test_pure():
    rec = decode_farm_datum(DATUM)
    assert rec["ref_1"] == "152451" and rec["agent_code"] == "SYNG001003" and rec["value_1"] == 1199 and rec["value_2"] == 75
    assert rec["document_cid"] == "QmXC3Ds2xF5Y3Dzb6W15nX9zTT23MmXJNKuUgrEEGHDVhQ"
    assert decode_farm_datum({"list": []}) is None and decode_farm_datum(None) is None
    assert in_coverage(21.26, 77.5, "IN-MH") and in_coverage(21.26, 77.5, None)
    assert not in_coverage(21.26, 77.5, "IN-GJ") and not in_coverage(23.3, 69.5, None)  # Gujarat is outside
    assert report_context(23.3, 69.5, "IN-GJ") is None
    ctx = report_context(21.26, 77.5, "IN-MH")
    assert ctx["parcel_match"] == "not performed" and ctx["policy_id"] == POLICY_ID
    assert local_fingerprint({"b": 1, "a": 2}) == local_fingerprint({"a": 2, "b": 1}) and len(local_fingerprint("x")) == 64


async def test_verify():
    v = await registry().verify_tx(TX)
    assert v["verified"] and v["checks"]["spent_from_registry_address"] and v["checks"]["pays_farm_token"], v
    assert v["checks"]["has_transaction_metadata"] is False and v["record"]["agent_code"] == "SYNG001003"
    v = await registry().verify_tx(TX, with_document=True)
    assert v["document"]["status"] == "unavailable"  # reported, never invented
    assert not (await registry(origin="addr1other").verify_tx(TX))["verified"]  # not issued by the registry address
    assert not (await registry(token=False).verify_tx(TX))["verified"]  # no farm token
    assert (await registry().verify_tx("zz"))["verified"] is False
    r = await registry().recent_records(5)
    assert r["status"] == "ok" and r["records"][0]["tx_hash"] == TX


def test_report_field():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from india.audit.config import AuditSettings
    from india.audit.gis_engine import GisResult, build_site
    from india.audit.models import LandCheckInput
    from india.audit.scoring import build_report

    s = AuditSettings(_env_file=None)
    for lat, lon, expect in ((21.26, 77.5, True), (23.3, 69.5, False)):
        inp = LandCheckInput(lat=lat, lon=lon)
        rep = build_report(inp, build_site(inp, s), GisResult())
        assert (rep.onchain_registry is not None) is expect, (lat, lon)


DOC = [{"farm_boundaries_id": 54312, "farm_id": 56877, "coordinate_type": "Polygon", "status": "active",
        "coordinates": {"type": "Polygon", "coordinates": [[[77.983895792, 20.799661727], [77.984439396, 20.799565146], [77.984334241, 20.799029259],
                                                            [77.983803509, 20.799172666], [77.983895792, 20.799661727]]]},
        "center_point": {"latitude": 20.799418105, "longitude": 77.984073746}}]


def test_document():
    farms = parse_document(DOC)
    assert farms[0]["farm_id"] == 56877 and parse_document({"x": 1}) == [] and parse_document([{"farm_id": 1}]) == []
    inside = {"type": "Polygon", "coordinates": [[[77.9840, 20.7994], [77.9842, 20.7994], [77.9842, 20.7996], [77.9840, 20.7996], [77.9840, 20.7994]]]}
    far = {"type": "Polygon", "coordinates": [[[70, 20], [70.1, 20], [70.1, 20.1], [70, 20.1], [70, 20]]]}
    assert parcel_overlap(inside, farms)[0]["share_of_parcel"] > 0.9 and parcel_overlap(far, farms) == []
    # the real 560-byte document seen on mainnet hashes to the CID anchored in its datum
    real = ('[{"farm_boundaries_id":54312,"farm_id":56877,"coordinate_type":"Polygon","coordinates":{"type":"Polygon","coordinates":'
            '[[[77.983895792,20.799661727],[77.984439396,20.799565146],[77.984334241,20.799029259],[77.983803509,20.799172666],'
            '[77.983895792,20.799661727]]]},"center_point":{"latitude":20.799418105,"longitude":77.984073746},"has_valid_coordinates":true,'
            '"coordinate_bounds":{"southwest":[77.983803509,20.799029259],"northeast":[77.984439396,20.799661727]},"status":"active",'
            '"created_at":"2026-09-28T01:27:32.103Z","updated_at":"2026-09-28T01:27:32.103Z"}]').encode()
    assert cid_v0_of(real) == "QmVzRp8CCSDJfVYhcgzoRpuCsVnEAXWpp2U77T22gaeZtV"


async def test_fetch_ok():
    seen = []

    def h(req):
        seen.append(req.headers.get("user-agent"))
        return httpx.Response(429) if "bad" in str(req.url) else httpx.Response(200, json=DOC)

    r = SwaminathanRegistry(httpx.AsyncClient(transport=httpx.MockTransport(h)), gateways=["https://bad.gw/ipfs", "https://ok.gw/ipfs"])
    d = await r.fetch_document("QmVzRp8CCSDJfVYhcgzoRpuCsVnEAXWpp2U77T22gaeZtV")
    assert d["status"] == "ok" and d["gateway"] == "https://ok.gw/ipfs" and d["farms"][0]["farm_id"] == 56877, d
    assert d["cid_verified"] is False  # a body that does not hash to the CID is reported, not hidden
    assert all("AgroLand" in ua for ua in seen)


test_pure()
test_document()
asyncio.run(test_fetch_ok())
asyncio.run(test_verify())
test_report_field()
print("registry OK")
