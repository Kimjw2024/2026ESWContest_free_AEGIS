from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Sequence

SPECIES_PRIORITY = {
    'raptor':1.00,'gull':0.90,'crow':0.78,'pigeon':0.78,'duck':0.72,
    'egret':0.68,'swallow':0.58,'sparrow':0.52,'UNKNOWN':0.35,
}

@dataclass
class DecisionResult:
    score:int; level:str; motion:str; altitude_zone:str; response:str; reason:str

class AegisDecisionEngine:
    def __init__(self, critical_dist_m: float = 1.5, low_altitude_m: float = 0.35):
        self.critical_dist_m=float(critical_dist_m); self.low_altitude_m=float(low_altitude_m)
    @staticmethod
    def _vec3(v: Optional[Sequence[float]]):
        if v is None or len(v) < 3: return None
        try: return float(v[0]), float(v[1]), float(v[2])
        except Exception: return None
    def decide(self, species:str, species_conf:float, pos, pred, threat:float, status:str, has_target:bool) -> DecisionResult:
        if not has_target:
            return DecisionResult(0,'--','--','--','MONITOR','No stable target')
        p=self._vec3(pos); q=self._vec3(pred)
        if p is None:
            return DecisionResult(0,'LOW','--','--','MONITOR','Waiting for stereo 3D lock')
        x,y,z=p
        altitude_zone='LOW' if abs(y) < self.low_altitude_m else 'HIGH'
        dz = 0.0 if q is None else z - q[2]
        motion='APPROACHING' if dz>0.03 else 'LEAVING' if dz<-0.03 else 'CROSSING / STABLE'
        distance_term=max(0.0,min(1.0,(self.critical_dist_m*1.6-z)/max(self.critical_dist_m*1.6,1e-6)))
        approach_term=1.0 if motion=='APPROACHING' else 0.35 if motion=='CROSSING / STABLE' else 0.0
        altitude_term=1.0 if altitude_zone=='LOW' else 0.55
        species_term=SPECIES_PRIORITY.get(species,SPECIES_PRIORITY['UNKNOWN'])
        track_term=1.0 if str(status).upper() in ('LOCKED','CRITICAL') else 0.6
        threat_term=max(0.0,min(1.0,float(threat)/3.0))
        score=int(round(30*distance_term+20*approach_term+10*altitude_term+15*species_term+10*track_term+15*threat_term))
        score=max(0,min(100,score))
        level='CRITICAL' if str(status).upper()=='CRITICAL' or score>=75 else 'HIGH' if score>=55 else 'MEDIUM' if score>=30 else 'LOW'
        if species=='UNKNOWN' or species_conf<0.70:
            response='TURRET TRACK + MONITOR' if level in ('CRITICAL','HIGH') else 'MONITOR'
        elif level in ('CRITICAL','HIGH'):
            response='TURRET + MOBILE ACOUSTIC' if altitude_zone=='LOW' else 'TURRET TRACK + ACOUSTIC'
        elif level=='MEDIUM':
            response='TURRET TRACK / ACOUSTIC READY'
        else:
            response='MONITOR'
        reason=' · '.join([
            f'{species} {species_conf:.0%}' if species!='UNKNOWN' else 'species uncertain',
            f'Z {z:.2f}m', altitude_zone.lower()+' altitude', motion.lower()
        ])
        return DecisionResult(score,level,motion,altitude_zone,response,reason)
