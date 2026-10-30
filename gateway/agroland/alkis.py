"""Deterministic corridor screening. All measurements use ETRS89 / UTM 32N."""
import hashlib,json
from functools import lru_cache
from pathlib import Path
from shapely.geometry import shape,mapping
from shapely.ops import unary_union
from shapely import transform as _transform
def transform(fn, geometry): return _transform(geometry, fn, interleaved=False)
from pyproj import Transformer
ROOT=Path(__file__).resolve().parents[2]/'data'/'de'
PROJECT=Transformer.from_crs(4326,25832,always_xy=True).transform
UNPROJECT=Transformer.from_crs(25832,4326,always_xy=True).transform
PARCELS=json.loads((ROOT/'parcels.geojson').read_text())['features']
BY_ID={f['properties']['cadastral']:f for f in PARCELS}
ROADS=json.loads((ROOT/'roads.geojson').read_text())
METADATA=json.loads((ROOT/'metadata.json').read_text())
ROAD=unary_union([transform(PROJECT,shape(f['geometry'])) for f in ROADS['features']])
BUFFERS={m:ROAD.buffer(m,quad_segs=32) for m in (200,500)}
DATA_HASH=hashlib.sha256((ROOT/'parcels.geojson').read_bytes()+(ROOT/'roads.geojson').read_bytes()).hexdigest()
RULES=[{'name':'EEG § 37(1)2c · 500 m','url':'https://www.gesetze-im-internet.de/eeg_2014/__37.html'},{'name':'BauGB § 35(1)8b · 200 m','url':'https://www.gesetze-im-internet.de/bbaug/__35.html'}]

def measure(parcel,road,buffers=None):
    if parcel.is_empty or not parcel.is_valid or parcel.geom_type not in ('Polygon','MultiPolygon') or parcel.area<=0:
        raise ValueError('Invalid parcel geometry')
    buffers=buffers or {m:road.buffer(m,quad_segs=32) for m in (200,500)}
    result={}
    for m,buffer in buffers.items():
        overlap=parcel.intersection(buffer).area
        fraction=min(1,max(0,overlap/parcel.area))
        result[str(m)]={'area_m2':round(overlap,2),'percent':round(fraction*100,2),'coverage':'full' if fraction>=1-1e-8 else 'partial' if overlap>0.01 else 'outside'}
    return {'geometry_area_m2':round(parcel.area,2),'distance_to_axis_m':round(parcel.distance(road),2),'corridors':result}

def analyze(cadastral):
    f=BY_ID[cadastral];p=f['properties'];g=transform(PROJECT,shape(f['geometry']))
    metrics=measure(g,ROAD,BUFFERS)
    coverage=metrics['corridors']['500']['coverage']
    # Green denotes geometry only. Legal suitability always remains unconfirmed.
    body={'schema_version':1,'rule_version':'de-solar-corridor-screening-2026-10-30-v1','cadastral':cadastral,'source_id':p['source_id'],'source_snapshot':METADATA['captured_at'],'data_sha256':DATA_HASH,'measurement_crs':'EPSG:25832',**metrics,'official_area_m2':p['official_area_m2'],'area_difference_m2':round(metrics['geometry_area_m2']-p['official_area_m2'],2),'geometry_signal':'green' if coverage=='full' else 'yellow' if coverage=='partial' else 'red','legal_status':'unconfirmed','reference':'OSM motorway carriageway centerline, not the legally required outer edge','sources':METADATA['sources']+RULES,'limitations':['Preliminary geometric screening along only A14 in the demonstration area.','OSM contains roadway axes. The norms count the distance from the outer edge: legal entry into the zone requires clarification.','Railways, other bases EEG, security zones, access and network connections have not been checked.','A traffic light describes an intersection of geometry, not a building permit, ownership, or guaranteed income.'],'suggestion':'It makes sense to discuss the lease for a solar project with the developer. Profitability requires a separate offer.' if coverage!='outside' else 'Area outside the verified corridor from the axis A14. Other reasons for placement and support were not assessed here.'}
    canonical=json.dumps(body,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
    return {**body,'sha256':hashlib.sha256(canonical).hexdigest(),'on_chain':False}

@lru_cache(maxsize=1)
def zone_signals():
    return {cad:analyze(cad)['geometry_signal'] for cad in BY_ID}

def corridor_geojson():
    return {'type':'FeatureCollection','features':[{'type':'Feature','properties':{'meters':m},'geometry':mapping(transform(UNPROJECT,b))} for m,b in reversed(list(BUFFERS.items()))]}

def demo_id():
    candidates=[p for p in PARCELS if analyze(p['properties']['cadastral'])['corridors']['500']['percent']>50]
    return min(candidates,key=lambda f:abs(f['properties']['area']-3))['properties']['cadastral']
