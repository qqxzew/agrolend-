"""Consented land directory and fixed-membership, unanimous energy cluster proposals.

Joining the directory is separate from approving a cluster. Neither action creates
an order, accepts an NDA, transfers land rights or releases a private boundary.
The existing Pool Access engine continues to handle paid private introductions.
"""
from __future__ import annotations

import hashlib
import json

from fastapi import HTTPException
from pyproj import Transformer
from shapely import transform
from shapely.geometry import shape
from shapely.strtree import STRtree

from . import parcels
from .db import jdump, new_id, now

DISTANCE_M = 1500
TECHNOLOGIES = ("solar", "wind", "hybrid")


class LandNetwork:
    def __init__(self, db):
        self.db = db

    def _region(self, parcel):
        if parcel["source"] == "alkis-demo":
            return "Magdeburg · Sachsen-Anhalt"
        if parcel["source"] == "in-demo":
            p = parcels.in_demo().get(parcel["ref"], {}).get("properties", {})
            return " · ".join(filter(None, (p.get("district"), p.get("state")))) or "India"
        return "Germany" if parcel["country"] == "DE" else "India"

    def register(self, user, body):
        if body.get("consent") is not True:
            raise HTTPException(422, "Please agree to include this site in the land database. Cluster participation needs separate consent.")
        tech = body.get("project_type")
        if not isinstance(tech, str) or tech not in TECHNOLOGIES:
            raise HTTPException(422, "Choose solar, wind or hybrid")
        if not isinstance(body.get("parcel_id"), str):
            raise HTTPException(422, "Choose a saved parcel")
        parcel = parcels.get(self.db, user["id"], body.get("parcel_id", ""))
        if not parcel["area_ha"] or parcel["area_ha"] < .5:
            raise HTTPException(422, "A cluster site needs at least 0.5 ha")
        region = body.get("region")
        if region is not None and (not isinstance(region, str) or len(region) > 100):
            raise HTTPException(422, "Region must be at most 100 characters")
        region = (region or "").strip() or self._region(parcel)
        with self.db.tx() as c:
            c.execute("BEGIN IMMEDIATE")
            old = c.execute("SELECT * FROM land_sites WHERE parcel_id=?", (parcel["id"],)).fetchone()
            stamp = now()
            if old and old["status"] == "listed" and old["project_type"] == tech and old["region"] == region:
                sid = old["id"]
            elif old:
                self._cancel(c, old["id"], user["id"], "site_changed")
                sid = old["id"]
                c.execute("UPDATE land_sites SET project_type=?,region=?,status='listed',consent_at=?,updated_at=?,revision=revision+1 WHERE id=?", (tech, region, stamp, stamp, sid))
            else:
                sid = new_id()
                c.execute("INSERT INTO land_sites(id,parcel_id,user_id,country,project_type,region,status,consent_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (sid, parcel["id"], user["id"], user["country"], tech, region, "listed", stamp, stamp, stamp))
        self.refresh(user["country"])
        return next(s for s in self.directory(user, mine=True, include_withdrawn=True) if s["id"] == sid)

    def _site(self, row, parcel, viewer):
        own = row["user_id"] == viewer
        out = {"id": row["id"], "country": row["country"], "project_type": row["project_type"], "region": row["region"],
               "area_ha": parcel["area_ha"], "status": row["status"], "own": own,
               "label": parcel["label"] if own else row["project_type"].capitalize() + " site · " + row["id"][:6]}
        if own:
            out.update(parcel_id=row["parcel_id"], consent_at=row["consent_at"], geometry=parcel["geometry"])
        return out

    def directory(self, user, project_type=None, region="", min_area_ha=0, mine=False, include_withdrawn=False):
        with self.db.tx() as c:
            rows = c.execute("SELECT s.*,p.label,p.area_ha,p.geometry FROM land_sites s JOIN parcels p ON p.id=s.parcel_id WHERE s.country=?" +
                             (" AND s.user_id=?" if mine else "") + ("" if include_withdrawn and mine else " AND s.status='listed'") + " ORDER BY s.created_at DESC",
                             (user["country"], user["id"]) if mine else (user["country"],)).fetchall()
        out = []
        for r in rows:
            if project_type and r["project_type"] not in (project_type, "hybrid"):
                continue
            if region.casefold() not in r["region"].casefold() or (r["area_ha"] or 0) < min_area_ha:
                continue
            p = {"label": r["label"], "area_ha": r["area_ha"], "geometry": json.loads(r["geometry"])}
            out.append(self._site(dict(r), p, user["id"]))
        return out

    def _cancel(self, c, sid, uid, event):
        rows = c.execute("SELECT k.id FROM energy_clusters k JOIN energy_cluster_members m ON m.cluster_id=k.id WHERE m.site_id=? AND k.status IN ('proposed','agreed')", (sid,)).fetchall()
        for r in rows:
            c.execute("UPDATE energy_clusters SET status='cancelled',updated_at=? WHERE id=?", (now(), r["id"]))
            c.execute("INSERT INTO energy_cluster_events(cluster_id,user_id,event,at) VALUES(?,?,?,?)", (r["id"], uid, event, now()))

    def withdraw(self, user, sid):
        with self.db.tx() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT * FROM land_sites WHERE id=? AND user_id=?", (sid, user["id"])).fetchone()
            if not row:
                raise HTTPException(404, "Site not found")
            self._cancel(c, sid, user["id"], "site_withdrawn")
            c.execute("UPDATE land_sites SET status='withdrawn',updated_at=? WHERE id=?", (now(), sid))
        self.refresh(user["country"])

    @staticmethod
    def _near(a, b):
        centre = a.union(b).centroid
        project = Transformer.from_crs(4326, f"+proj=aeqd +lat_0={centre.y} +lon_0={centre.x} +datum=WGS84 +units=m", always_xy=True).transform
        return transform(a, project, interleaved=False).distance(transform(b, project, interleaved=False)) <= DISTANCE_M

    def refresh(self, country):
        """Build connected neighbouring groups. Existing agreements never gain members silently."""
        with self.db.tx() as c:
            c.execute("BEGIN IMMEDIATE")
            rows = [dict(r) for r in c.execute("SELECT s.*,p.geometry FROM land_sites s JOIN parcels p ON p.id=s.parcel_id WHERE s.country=? AND s.status='listed' ORDER BY s.id", (country,))]
            desired = set()
            for tech in ("solar", "wind"):
                sites = [r for r in rows if r["project_type"] in (tech, "hybrid")]
                if len(sites) < 2:
                    continue
                geometries = [shape(json.loads(r["geometry"])) for r in sites]
                tree, edges = STRtree(geometries), {i: set() for i in range(len(sites))}
                for i, g in enumerate(geometries):
                    # Bounding-box prefilter; exact local metric distance is checked next.
                    for index in tree.query(g.buffer(.04)):
                        j = int(index)
                        if j > i and self._near(g, geometries[j]):
                            edges[i].add(j); edges[j].add(i)
                seen = set()
                for i in edges:
                    if i in seen:
                        continue
                    component, todo = set(), [i]
                    while todo:
                        j = todo.pop()
                        if j in component:
                            continue
                        component.add(j); todo.extend(edges[j] - component)
                    seen.update(component)
                    members = [sites[j] for j in sorted(component)]
                    if len({r["user_id"] for r in members}) < 2:
                        continue
                    fingerprint = hashlib.sha256(jdump([tech, [(r["id"], r["revision"]) for r in members]]).encode()).hexdigest()
                    desired.add(fingerprint)
                    existing = c.execute("SELECT id,status FROM energy_clusters WHERE fingerprint=?", (fingerprint,)).fetchone()
                    if existing:
                        if existing["status"] in ("superseded", "cancelled"):
                            c.execute("UPDATE energy_clusters SET status='proposed',updated_at=? WHERE id=?", (now(), existing["id"]))
                            c.execute("UPDATE energy_cluster_members SET decision='pending',decided_at=NULL WHERE cluster_id=?", (existing["id"],))
                            c.execute("INSERT INTO energy_cluster_events(cluster_id,event,at) VALUES(?,'reproposed',?)", (existing["id"], now()))
                        continue
                    cid, stamp = new_id(), now()
                    c.execute("INSERT INTO energy_clusters VALUES(?,?,?,?,?,?,?)", (cid, country, tech, fingerprint, "proposed", stamp, stamp))
                    c.executemany("INSERT INTO energy_cluster_members VALUES(?,?,'pending',NULL)", [(cid, r["id"]) for r in members])
                    c.execute("INSERT INTO energy_cluster_events(cluster_id,event,at) VALUES(?,'proposed',?)", (cid, stamp))
            for r in c.execute("SELECT id,fingerprint FROM energy_clusters WHERE country=? AND status='proposed'", (country,)).fetchall():
                if r["fingerprint"] not in desired:
                    c.execute("UPDATE energy_clusters SET status='superseded',updated_at=? WHERE id=?", (now(), r["id"]))

    def clusters(self, user):
        with self.db.tx() as c:
            ids = [r[0] for r in c.execute("SELECT DISTINCT k.id FROM energy_clusters k JOIN energy_cluster_members m ON m.cluster_id=k.id JOIN land_sites s ON s.id=m.site_id WHERE s.user_id=? AND k.country=? ORDER BY k.created_at DESC", (user["id"], user["country"]))]
        return [self.cluster(user, cid) for cid in ids]

    def cluster(self, user, cid):
        with self.db.tx() as c:
            row = c.execute("SELECT * FROM energy_clusters WHERE id=? AND country=?", (cid, user["country"])).fetchone()
            members = c.execute("SELECT m.*,s.user_id,s.project_type,s.region,s.status,p.label,p.area_ha FROM energy_cluster_members m JOIN land_sites s ON s.id=m.site_id JOIN parcels p ON p.id=s.parcel_id WHERE m.cluster_id=? ORDER BY s.id", (cid,)).fetchall()
        if not row or not any(r["user_id"] == user["id"] for r in members):
            raise HTTPException(404, "Cluster not found")
        own = [r for r in members if r["user_id"] == user["id"]]
        participants = {r["user_id"] for r in members}
        accepted = {uid for uid in participants if all(r["decision"] == "accept" for r in members if r["user_id"] == uid)}
        return {"id": cid, "country": row["country"], "project_type": row["project_type"], "status": row["status"], "distance_m": DISTANCE_M,
                "site_count": len(members), "participant_count": len(participants), "accepted_count": len(accepted),
                "area_ha": round(sum(r["area_ha"] or 0 for r in members), 2), "own_decision": own[0]["decision"], "updated_at": row["updated_at"],
                "members": [{"site_id": r["site_id"], "own": r["user_id"] == user["id"], "label": r["label"] if r["user_id"] == user["id"] else "Partner site " + str(i + 1),
                             "region": r["region"], "area_ha": r["area_ha"], "decision": r["decision"], "decided_at": r["decided_at"]} for i, r in enumerate(members)]}

    def decide(self, user, cid, decision):
        if decision not in ("accept", "decline"):
            raise HTTPException(422, "Choose accept or decline")
        with self.db.tx() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT * FROM energy_clusters WHERE id=? AND country=?", (cid, user["country"])).fetchone()
            own = c.execute("SELECT m.site_id FROM energy_cluster_members m JOIN land_sites s ON s.id=m.site_id WHERE m.cluster_id=? AND s.user_id=? AND s.status='listed'", (cid, user["id"])).fetchall()
            if not row or not own:
                raise HTTPException(404, "Cluster not found")
            if row["status"] not in ("proposed", "agreed"):
                raise HTTPException(409, "This proposal has ended. Review the current cluster proposal instead.")
            stamp = now()
            c.executemany("UPDATE energy_cluster_members SET decision=?,decided_at=? WHERE cluster_id=? AND site_id=?", [(decision, stamp, cid, r["site_id"]) for r in own])
            decisions = [r[0] for r in c.execute("SELECT decision FROM energy_cluster_members WHERE cluster_id=?", (cid,))]
            status = "declined" if "decline" in decisions else "agreed" if all(d == "accept" for d in decisions) else "proposed"
            c.execute("UPDATE energy_clusters SET status=?,updated_at=? WHERE id=?", (status, stamp, cid))
            c.execute("INSERT INTO energy_cluster_events(cluster_id,user_id,event,at) VALUES(?,?,?,?)", (cid, user["id"], decision, stamp))
        return self.cluster(user, cid)
