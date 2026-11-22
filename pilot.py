import math
import mechfight as mf


class Pilot:
    name = "Perimeter"

    def __init__(self, hello):
        self.reach = hello["config"]["loot"]["pickup_radius"]
        self.previous = None
        self.stalled = 0
        self.last_alive = 16
        self.solo_deaths = 0

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
        ranks = {"laser": 4, "lightning": 3, "mortar": 2, "gun": 1}
        slots = me["weapons"]
        held = [w["kind"] if w else "" for w in slots]
        replace = min(range(len(slots)), key=lambda i: ranks.get(held[i], 0))
        prizes = []
        for p in o["pickups"]:
            gain = ranks[p["kind"]]-ranks.get(held[replace], 0)
            if gain <= 0 or p["kind"] in held:
                continue
            d = dist(p["pos"])
            prizes.append((d/(2*gain), p["pos"]))
            if d < self.reach and abs(p["pos"][2]-z) < 4:
                action["take"] = p["id"]
                if slots[replace]:
                    action["drop"] = replace
        prizes.extend((dist(c["pos"])*0.65,c["pos"]) for c in o["cubes"])
        enemies = [m for m in o["mechs"] if m["kind"]=="mech"]
        target = min(enemies, key=lambda m: dist(m["pos"])+0.12*m.get("hp",600), default=None)
        center = zone["next_center"]
        angle = heading(center)
        side = 1 if int(o["t"]/3.7+me["id"])%2 else -1
        margin = zone["radius"]-dist(zone["center"])
        urgent = margin < 12 or dist(center) > zone["next_radius"] + max(0,zone["shrink_start"]-o["t"])*6
        if target and not urgent:
            d = dist(target["pos"])
            desired = 145 if self.solo_deaths < 2 else 195
            angle = heading(target["pos"])+side*(math.pi/2+math.atan((desired-d)/40))
        elif not urgent and prizes and min(prizes)[0]<50:
            angle = heading(min(prizes)[1])
        elif not urgent:
            angle += 1.4 if dist(center)<zone["next_radius"]*0.7 else 0.7
        if self.stalled > 3:
            angle += side*1.1
        action.update(move=[math.cos(angle),math.sin(angle)], boost=me["energy"]>25 and (urgent or bool(enemies) or self.stalled>3), jump=me["grounded"] and self.stalled>3)
        if not target and o["crates"]:
            target = min(o["crates"],key=lambda c:dist(c["pos"]))
        if target:
            p = target["pos"]
            v = target.get("vel",(0,0,0))
            d = dist(p)
            instant = any(w and w["kind"]=="laser" and w["cooldown"]<0.15 for w in slots)
            t = 0 if instant else d/252
            dx,dy = p[0]+v[0]*t-x,p[1]+v[1]*t-y
            yaw = math.atan2(dy,dx)
            pitch = math.atan2(p[2]+(4.5 if "vel" in target else 1)-z-7, max(1,math.hypot(dx,dy)))
            aligned = abs(math.remainder(yaw-me["aim"][0],2*math.pi)) < 0.06+3/max(1,d)
            action.update(aim=[yaw,pitch],fire=[bool(w and aligned and d<w["stats"].get("range",180)) for w in slots])
        else:
            action["aim"] = [angle+0.8*math.sin(o["t"]),0]
            action["reload"] = any(w and w.get("ammo",12)<8 for w in slots)
        if o["offer"]:
            priority = ["plating","regen","damage","speed","reload"]
            choices = o["offer"]["choices"]
            action["pick"] = min(range(len(choices)),key=lambda i:next((j for j,s in enumerate(priority) if s in choices[i]["id"]),10))
        return action


mf.run(Pilot)
