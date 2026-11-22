import math
import json
from pathlib import Path
import mechfight as mf


class Pilot:
    name = "Perimeter"

    def __init__(self, hello):
        self.reach = hello["config"]["loot"]["pickup_radius"]
        self.previous = None
        self.cover = []
        self.roofs = {}
        self.last_hit = {}
        roots = [Path(hello["map"]["dir"]), Path("/arena")]
        for root in roots:
            path = root / "v2" / "world.json"
            if not path.is_file():
                continue
            for prism in json.loads(path.read_text())["prisms"]:
                if prism["block"] < 0 or prism["top"] - prism["base"] < 8:
                    continue
                ring = prism["ring"]
                xs, ys = ring[::2], ring[1::2]
                cx, cy = (min(xs)+max(xs))/2, (min(ys)+max(ys))/2
                # Rasterize the footprint at cell centers, preserving courtyards.
                rings = [ring] + prism.get("holes", [])
                for row in range(math.floor(min(ys)/5),math.floor(max(ys)/5)+1):
                    scan = 5*row+2.5
                    cuts = []
                    for boundary in rings:
                        for i in range(0,len(boundary),2):
                            ax,ay = boundary[i-2:i] if i else boundary[-2:]
                            bx,by = boundary[i:i+2]
                            if (ay>scan) != (by>scan):
                                cuts.append(ax+(scan-ay)*(bx-ax)/(by-ay))
                    cuts.sort()
                    for left,right in zip(cuts[::2],cuts[1::2]):
                        for col in range(math.ceil(left/5-0.5),math.ceil(right/5-0.5)):
                            cell = (col,row)
                            self.roofs[cell] = max(self.roofs.get(cell,-1000),prism["top"])
                self.cover.extend([(min(xs)-5,cy,cx,cy),(max(xs)+5,cy,cx,cy),(cx,min(ys)-5,cx,cy),(cx,max(ys)+5,cx,cy)])
            break
        self.refuge = None
        self.replan = -1
        self.last_damage = -100
        self.damage_bearing = None
        self.retreating = False
        self.stalled = 0
        self.last_alive = 16
        self.solo_deaths = 0

    def clear(self, x, y, z, target):
        tx,ty,tz = target["pos"]
        steps = max(1,math.ceil(math.hypot(tx-x,ty-y)/5))
        for i in range(1,steps):
            f = i/steps
            cell = (math.floor((x+(tx-x)*f)/5),math.floor((y+(ty-y)*f)/5))
            if self.roofs.get(cell,-1000) > z+(tz+4.5-z)*f:
                return False
        return True

    def act(self, o):
        me, zone = o["self"], o["zone"]
        x, y, z = me["pos"]
        dist = lambda p: math.hypot(p[0]-x, p[1]-y)
        heading = lambda p: math.atan2(p[1]-y, p[0]-x)
        action = {"tick": o["tick"]}
        if self.previous and dist(self.previous) < 0.22:
            self.stalled += 1
        else:
            self.stalled = 0
        self.previous = (x, y)
        self.solo_deaths += max(0, self.last_alive-o["alive"]-sum(e["type"]=="kill" for e in o["events"]))
        self.last_alive = o["alive"]
        for event in o["events"]:
            if event["type"] == "hit":
                self.last_hit[event["target"]] = o["t"]
            if event["type"] == "damaged" and event.get("bearing") is not None:
                self.last_damage = o["t"]
                self.damage_bearing = event["bearing"]
        hp_fraction = me["hp"] / me["max_hp"]
        if hp_fraction > 0.86:
            self.retreating = False
        elif hp_fraction < 0.48:
            self.retreating = True
        ranks = {"laser": 5, "mortar": 3, "lightning": 2, "gun": 1}
        slots = me["weapons"]
        held = [w["kind"] if w else "" for w in slots]
        replace = min(range(len(slots)), key=lambda i: -1 if slots[i] is None else 9 if held[i] == "gun" else ranks[held[i]])
        available = [
            p for p in o["pickups"]
            if p["kind"] not in held and ranks[p["kind"]] > ranks.get(held[replace], 0)
            and abs(p["pos"][2] - z) < 5
        ]
        nearby = [p for p in available if dist(p["pos"]) <= self.reach and abs(p["pos"][2] - z) <= 4]
        if nearby:
            best = max(nearby, key=lambda p: ranks[p["kind"]])
            action["take"] = best["id"]
            if slots[replace]:
                action["drop"] = replace
        prizes = [(dist(p["pos"]) * (0.6 if p["kind"] == "laser" else 1.1), p["pos"]) for p in available]
        prizes.extend((dist(c["pos"]) * (0.46 if me["cubes"] < 10 else 0.9), c["pos"]) for c in o["cubes"] if abs(c["pos"][2] - z) < 5)
        for drop in o["drops"]:
            if drop["lands_in"] <= 6:
                prizes.append((max(0, dist(drop["pos"]) - (40 if self.retreating else 15)), drop["pos"]))
        enemies = [m for m in o["mechs"] if m["kind"]=="mech"]
        muzzle_z = z+me["stats"].get("muzzle_height",7)
        visible = [m for m in enemies if self.clear(x,y,muzzle_z,m)]
        target = min(visible or enemies, key=lambda m: dist(m["pos"])+0.32*m.get("hp",600)+250*(dist(m["pos"])>220), default=None)
        center = zone["next_center"]
        angle = heading(center)
        side = 1 if int(o["t"]/3.7+me["id"])%2 else -1
        margin = zone["radius"]-dist(zone["center"])
        urgent = margin < 12 or dist(center) > zone["next_radius"] + max(0,zone["shrink_start"]-o["t"])*6
        best_prize = min(prizes, default=(math.inf, None))
        recent_damage = o["t"] - self.last_damage < 4
        final_mode = self.solo_deaths >= 2
        threat_nearby = target and dist(target["pos"]) < 130
        stop = False
        if not urgent and best_prize[0] < (18 if threat_nearby else 60):
            angle = heading(best_prize[1])
            stop = dist(best_prize[1]) < 3
        elif target and not urgent:
            distance = dist(target["pos"])
            desired = 172 if "laser" not in held else 205
            if self.retreating or final_mode:
                desired += 70
            angle = heading(target["pos"]) + side * (math.pi/2 + math.atan((desired-distance)/30))
        elif not urgent and self.retreating and recent_damage:
            angle = self.damage_bearing + math.pi
        elif not urgent:
            angle += 1.36 if dist(center) < zone["next_radius"]*0.72 else 0.65
        if self.cover and (final_mode or self.retreating) and not urgent and best_prize[0] >= 18 and (self.retreating or threat_nearby):
            if o["t"] >= self.replan:
                self.replan = o["t"] + 1.6
                threat = target["pos"] if target else center
                def cost(site):
                    sx, sy, cx, cy = site
                    facing = ((sx-cx)*(threat[0]-cx)+(sy-cy)*(threat[1]-cy))/(max(1,math.hypot(sx-cx,sy-cy))*max(1,math.dist(threat[:2],(cx,cy))))
                    edge = math.dist(site[:2],center)-zone["next_radius"]+10
                    return dist(site)+max(0,edge)*5+40*facing
                self.refuge = min(self.cover,key=cost)
            if self.refuge:
                angle = heading(self.refuge)
                stop = dist(self.refuge) < 4 and not recent_damage
        if target and not urgent and not recent_damage and best_prize[0] > 18:
            distance = dist(target["pos"])
            proven_angle = o["t"]-self.last_hit.get(target["id"],-100) < 1.6
            if visible and proven_angle and 105 < distance < 218 and len(visible) == 1 and not o["projectiles"]:
                stop = True
            elif not visible and distance < 210:
                lateral = heading(target["pos"])+math.pi/2
                for direction in (side,-side):
                    peek = lateral if direction > 0 else lateral+math.pi
                    if self.clear(x+13*math.cos(peek),y+13*math.sin(peek),muzzle_z,target):
                        angle = peek
                        stop = False
                        break
        if self.stalled > 3 and not stop:
            angle += side*1.1
        if o["projectiles"] and not stop:
            incoming = []
            for shot in o["projectiles"]:
                px, py, pz = shot["pos"]
                vx, vy, vz = shot["vel"]
                dx, dy = px-x, py-y
                speed2 = vx*vx + vy*vy
                if speed2 < 1:
                    continue
                eta = -(dx*vx+dy*vy)/speed2
                if 0.03 < eta < 0.85 and abs(pz+vz*eta-z-5) < 16:
                    incoming.append((dx,dy,vx,vy,eta))
            if incoming:
                speed = me["stats"].get("boost_speed",19) if me["energy"] > 20 else me["stats"].get("walk_speed",12)
                def travel_cost(offset):
                    ux = speed*math.cos(angle+offset)
                    uy = speed*math.sin(angle+offset)
                    risk = 0
                    for dx,dy,vx,vy,eta in incoming:
                        rx,ry = vx-ux,vy-uy
                        t = max(0,min(0.9,-(dx*rx+dy*ry)/max(1,rx*rx+ry*ry)))
                        clearance = math.hypot(dx+rx*t,dy+ry*t)
                        risk += max(0,8-clearance)**2/(0.2+t)
                    return risk+3*abs(offset)
                angle += min((0,-0.5,0.5,-1,1,-1.57,1.57,2.5,-2.5),key=travel_cost)
        action.update(move=[0,0] if stop else [math.cos(angle),math.sin(angle)], boost=not stop and me["energy"]>18 and (urgent or recent_damage or self.stalled>3 or (target is not None and dist(target["pos"])<100)), jump=not stop and me["grounded"] and self.stalled>3)
        if not target and not self.retreating and o["crates"]:
            target = min(o["crates"],key=lambda c:dist(c["pos"]))
        if target:
            p = target["pos"]
            v = target.get("vel",(0,0,0))
            d = dist(p)
            instant = any(w and w["kind"]=="laser" and w["cooldown"]<0.15 for w in slots)
            gun = next((w for w in slots if w and w["kind"] == "gun"), None)
            mortar = next((w for w in slots if w and w["kind"] == "mortar" and w["cooldown"] <= 0.1), None)
            loft = mortar is not None and 18 < d < 145 and not instant
            speed = mortar["stats"].get("speed",72) if loft else (gun["stats"].get("speed",252) if gun else 252)
            t = 0 if instant else d/speed
            for _ in range(2):
                if not instant:
                    t = math.hypot(p[0]+v[0]*t-x,p[1]+v[1]*t-y)/speed
            muzzle = me["stats"].get("muzzle_height",7)
            dx,dy = p[0]+v[0]*t-x,p[1]+v[1]*t-y
            yaw = math.atan2(dy,dx)
            pitch = math.atan2(p[2]+(4.5 if "vel" in target else 1)+v[2]*min(t,0.45)-z-muzzle, max(1,math.hypot(dx,dy)))
            if loft:
                horizontal = math.hypot(dx,dy)
                height = p[2]-z-muzzle
                gravity = mortar["stats"].get("gravity",22)
                disc = speed**4-gravity*(gravity*horizontal**2+2*height*speed**2)
                if disc > 0:
                    pitch = math.atan2(gravity*horizontal**2+2*height*speed**2,horizontal*(speed**2+math.sqrt(disc)))
            aligned = abs(math.remainder(yaw-me["aim"][0],2*math.pi)) < 0.06+3/max(1,d)
            imminent = target.get("hp",1000) < 180 or d < 85
            fire = [bool(w and aligned and d<w["stats"].get("range",180) and (not loft or w["kind"] == "mortar")) for w in slots]
            if self.retreating and not imminent and not recent_damage and final_mode:
                fire = [False, False]
            action.update(aim=[yaw,pitch],fire=fire)
        else:
            action["aim"] = [self.damage_bearing if recent_damage else angle+0.8*math.sin(o["t"]),0]
            action["reload"] = any(w and w.get("ammo",12)<8 for w in slots)
        if o["offer"]:
            priority = ["nanites","armor","plating","gun_damage","gun_rate","servos","laser_damage","gun_mag"]
            choices = o["offer"]["choices"]
            action["pick"] = min(range(len(choices)),key=lambda i:next((j for j,s in enumerate(priority) if s in choices[i]["id"]),10))
        return action


mf.run(Pilot)
