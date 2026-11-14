from . import constants as C
def lanes(k,r_p=0.90,r_h=0.90,sl=0.95,ret=12,sens=False):
 out={}
 for lid in C.required_lanes(k) if hasattr(C,"required_lanes") else []: pass
 return out
def full(k,rcand=0.90,sl=0.95,ret=12,sens=False,h_mem=0):
 from .oracle import required_lanes
 out={}
 for lid in required_lanes(k):
  n=int(lid.split('/')[1]); cls=lid.split('/')[2]
  camp={}
  for c in C.CAMP:
   rec={"retained_count":ret,"filter_sensitive":sens}
   for s in ("P","H"):
    r=rcand
    rec[f"R_{s}_A"]=r; rec[f"CI_{s}_A"]={"low":r-0.01,"high":r+0.01}
    rec[f"R_{s}_L"]=sl; rec[f"CI_{s}_L"]={"low":sl-0.01,"high":sl+0.01}
   camp[c]=rec
  out[lid]={"id":lid,"k":k,"campaigns":camp}
 return out
def eight_lanes(k, **kwargs):
 return full(k, **kwargs)
