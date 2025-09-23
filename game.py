import pygame, sys, math, random, time
from math import sin, cos, radians, sqrt, isfinite

# ---------- Settings ----------
WIN_W, WIN_H = 1200, 720
FPS = 60

# Camera orbit defaults
CAM_DIST_DEFAULT = 24.0
CAM_PITCH_DEFAULT = radians(18.0)
CAM_PITCH_MIN = radians(-8.0)
CAM_PITCH_MAX = radians(58.0)
CAM_DIST_MIN = 10.0
CAM_DIST_MAX = 48.0

# Player / physics
GRAVITY = -32.0
JUMP_V = 14.0
WALK_SPEED = 5.2
SPRINT_SPEED = 10.6
PLAYER_HEIGHT = 1.9

# Simple building geometry
BUILDING_DEPTH = 14.0
EPS = 1e-5

# ---------- 5 Deterministic Levels ----------
LEVELS = []
# Levels progressively larger gaps and heights (but all solvable)
LEVELS.append({'num_buildings': 8,  'lanes': [-18, -6, 6, 18], 'min_w':6.0,  'max_w':9.0,  'min_h':12.0, 'max_h':18.0, 'gap_min':2.0, 'gap_max':4.0})
LEVELS.append({'num_buildings': 9,  'lanes': [-20, -8, 8, 20], 'min_w':6.0,  'max_w':10.0, 'min_h':14.0, 'max_h':20.0, 'gap_min':2.2, 'gap_max':4.8})
LEVELS.append({'num_buildings':10,  'lanes': [-22, -10, 4, 16, 28], 'min_w':6.0,  'max_w':11.0, 'min_h':16.0, 'max_h':26.0, 'gap_min':2.4, 'gap_max':5.6})
LEVELS.append({'num_buildings':11,  'lanes': [-24, -12, 0, 12, 24], 'min_w':6.5,  'max_w':12.0, 'min_h':18.0, 'max_h':32.0, 'gap_min':2.6, 'gap_max':6.4})
LEVELS.append({'num_buildings':12,  'lanes': [-26, -14, -2, 10, 22], 'min_w':7.0,  'max_w':12.8, 'min_h':20.0, 'max_h':38.0, 'gap_min':2.6, 'gap_max':7.0})

# ---------- Helpers ----------
def clamp(v,a,b): return max(a, min(b, v))
def lerp(a,b,t): return a + (b-a)*t

class Vec3:
    __slots__ = ('x','y','z')
    def __init__(self,x=0.,y=0.,z=0.):
        self.x=float(x); self.y=float(y); self.z=float(z)
    def __sub__(self, o): return Vec3(self.x-o.x, self.y-o.y, self.z-o.z)
    def __add__(self, o): return Vec3(self.x+o.x, self.y+o.y, self.z+o.z)

def length(v: Vec3):
    return sqrt(v.x*v.x + v.y*v.y + v.z*v.z)

def normalize(v: Vec3):
    L = length(v)
    if L <= 1e-9: return Vec3(0,0,1)
    return Vec3(v.x/L, v.y/L, v.z/L)

def cross(a: Vec3, b: Vec3):
    return Vec3(a.y*b.z - a.z*b.y, a.z*b.x - a.x*b.z, a.x*b.y - a.y*b.x)

def dot(a: Vec3, b: Vec3):
    return a.x*b.x + a.y*b.y + a.z*b.z

# Reachability math (used to ensure levels are solvable)
def max_jump_horizontal(speed, jump_v=JUMP_V, gravity=GRAVITY):
    g = abs(gravity)
    if g <= 0: return 0.0
    airtime = 2.0 * jump_v / g
    return speed * airtime * 0.92

def max_jump_up(jump_v=JUMP_V, gravity=GRAVITY):
    g = abs(gravity)
    if g <= 0: return 0.0
    return (jump_v * jump_v) / (2.0 * g)

# ---------- Projection (camera basis) ----------
def build_camera_basis(cam_pos: Vec3, target: Vec3, world_up=Vec3(0,1,0)):
    forward = normalize(Vec3(target.x - cam_pos.x, target.y - cam_pos.y, target.z - cam_pos.z))
    right = normalize(cross(forward, world_up))
    up = cross(right, forward)
    return forward, right, up

def project_point(p: Vec3, cam_pos: Vec3, forward: Vec3, right: Vec3, up: Vec3, fov):
    rel = Vec3(p.x - cam_pos.x, p.y - cam_pos.y, p.z - cam_pos.z)
    cx = dot(right, rel)
    cy = dot(up, rel)
    cz = dot(forward, rel)
    if cz <= EPS: cz = EPS
    scale = fov / cz
    sx = cx * scale + WIN_W/2
    sy = -cy * scale + WIN_H/2
    return (sx, sy, scale, cz)

def safe_poly(poly):
    if not poly or len(poly) < 3: return False
    for x,y in poly:
        if not isfinite(x) or not isfinite(y): return False
    xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
    if (max(xs)-min(xs)) > WIN_W*4 or (max(ys)-min(ys)) > WIN_H*4: return False
    if (max(xs)-min(xs)) < 0.15 and (max(ys)-min(ys)) < 0.15: return False
    return True

# ---------- Building ----------
class Building:
    def __init__(self, x_center, z_start, width, depth, height):
        self.x = float(x_center)
        self.z = float(z_start)
        self.w = float(width)
        self.d = float(depth)
        self.h = float(height)
    def roof_center_z(self):
        return self.z + self.d * 0.5
    def contains_roof(self, x, z):
        if (x >= self.x - self.w/2 - 1e-6) and (x <= self.x + self.w/2 + 1e-6) and (z >= self.z - 1e-6) and (z <= self.z + self.d + 1e-6):
            return True
        return False

# ---------- Game ----------
class Game:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((WIN_W, WIN_H))
        pygame.display.set_caption("Rooftop — restored")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("consolas", 18)
        self.big = pygame.font.SysFont("consolas", 34, bold=True)

        # camera orbit params
        self.cam_yaw = 0.0
        self.cam_pitch = CAM_PITCH_DEFAULT
        self.cam_dist = CAM_DIST_DEFAULT
        self.yaw_sens = 0.0045
        self.pitch_sens = 0.0045

        self.level_index = 0
        self.seed_base = 12345  # deterministic seed base
        self.lmb_held = False

        self.state = 'menu'
        self.menu_index = 0
        self.selected_level = 0

        # create first world
        self.reset_world(0)

    def level_seed(self, idx):
        return self.seed_base + idx * 7919

    def reset_world(self, level_idx=0):
        # reset camera and regenerate deterministic level
        self.cam_yaw = 0.0
        self.cam_pitch = CAM_PITCH_DEFAULT
        self.cam_dist = CAM_DIST_DEFAULT

        self.level_index = clamp(level_idx, 0, len(LEVELS)-1)
        cfg = LEVELS[self.level_index]
        rng = random.Random(self.level_seed(self.level_index))

        # Generate buildings deterministically and ensure reachability
        self.buildings = []
        z = 10.0
        prev = None
        horiz_reach = max_jump_horizontal(cfg['player_sprint'] if 'player_sprint' in cfg else SPRINT_SPEED, JUMP_V, GRAVITY)
        max_up = max_jump_up(JUMP_V, GRAVITY) * 0.98 + 1.6

        i = 0
        tries = 0
        while i < cfg['num_buildings'] and tries < 8000:
            tries += 1
            lane = rng.choice(cfg['lanes'])
            w = rng.uniform(cfg['min_w'], cfg['max_w'])
            h = max(8.0, rng.gauss((cfg['min_h']+cfg['max_h'])/2.0, (cfg['max_h']-cfg['min_h'])*0.12))
            if prev:
                # clamp vertical step to reasonable values so most jumps are possible
                if h - prev.h > max_up:
                    h = prev.h + max_up * rng.uniform(0.6, 1.0)
                if prev.h - h > 45.0:
                    h = prev.h - 45.0 * rng.uniform(0.4, 1.0)
            gap = rng.uniform(cfg['gap_min'], cfg['gap_max'])
            x = lane + rng.uniform(-1.6, 1.6)
            b = Building(x, z, w, BUILDING_DEPTH, h)

            # quick reachability check: center-to-center horizontal distance
            if prev:
                prev_cz = prev.z + prev.d * 0.5
                cand_cz = b.z + b.d * 0.5
                dx = b.x - prev.x
                dz = cand_cz - prev_cz
                if math.hypot(dx, dz) > horiz_reach * 0.98:
                    # try to reduce gap and nudge lane once to attempt feasibility
                    gap = max(cfg['gap_min'], gap * 0.5)
                    b.z = z  # keep b.z same (we haven't incremented z yet)
            self.buildings.append(b)
            prev = b
            z += BUILDING_DEPTH + gap
            i += 1

        if len(self.buildings) < cfg['num_buildings']:
            # fill remainder simply
            while len(self.buildings) < cfg['num_buildings']:
                x = rng.choice(cfg['lanes'])
                w = rng.uniform(cfg['min_w'], cfg['max_w'])
                h = rng.uniform(cfg['min_h'], cfg['max_h'])
                b = Building(x, z, w, BUILDING_DEPTH, h)
                self.buildings.append(b)
                z += BUILDING_DEPTH + cfg['gap_min']

        self.buildings.sort(key=lambda bb: bb.z)

        # choose deterministic start: tallest among first 4
        start = max(self.buildings[:4], key=lambda b: b.h)
        self.player_x = start.x
        self.player_z = start.z + start.d * 0.5
        self.player_y = start.h
        self.player_vy = 0.0
        self.player_on_ground = True
        self.player_walk = WALK_SPEED
        self.player_sprint = SPRINT_SPEED
        self.player_jump = JUMP_V

        self.time_start = time.time()
        self.score_dist = 0.0
        self.particles = []

        # set camera around player now
        self.update_camera_immediate()

        self.level_completed = False
        self.victory_timer = 0.0
        self.respawn_cooldown = 0.0

        # flush mouse rel to avoid sudden jumps
        pygame.mouse.get_rel()

    def update_camera_immediate(self):
        px = self.player_x
        py = self.player_y + PLAYER_HEIGHT*0.6
        pz = self.player_z
        pitch = clamp(self.cam_pitch, CAM_PITCH_MIN, CAM_PITCH_MAX)
        dist = clamp(self.cam_dist, CAM_DIST_MIN, CAM_DIST_MAX)
        cos_p = math.cos(pitch)
        cx = px + dist * math.sin(self.cam_yaw) * cos_p
        cy = py + dist * math.sin(pitch)
        cz = pz + dist * math.cos(self.cam_yaw) * cos_p
        self.cam_pos = Vec3(cx, cy, cz)
        self.cam_target = Vec3(px, py, pz)
        self.forward, self.right, self.up = build_camera_basis(self.cam_pos, self.cam_target)

    def spawn_particles(self, n=6):
        for _ in range(n):
            self.particles.append({'x': self.player_x + random.uniform(-0.6,0.6),
                                   'y': self.player_y,
                                   'z': self.player_z - random.uniform(0.1,1.6),
                                   'vy': random.uniform(2.0,4.0),
                                   'life': random.uniform(0.18,0.45)})

    def attempt_climb(self):
        # mantle/climb E: find suitable front building that is slightly above player's jump capacity
        climb_thresh = max_jump_up(self.player_jump, GRAVITY) * 1.05 + 1.6
        horiz = max_jump_horizontal(self.player_sprint, self.player_jump, GRAVITY) * 0.6 + 1.6
        best = None
        for b in self.buildings:
            rz = b.z + b.d * 0.5
            if rz <= self.player_z - 0.8: continue
            dx = abs(b.x - self.player_x)
            dz = rz - self.player_z
            if dx <= b.w*0.75 + horiz and dz <= 10.0:
                vdelta = b.h - self.player_y
                if 0.6 <= vdelta <= climb_thresh:
                    score = dz + dx*0.6
                    if best is None or score < best[0]:
                        best = (score, b)
        if best:
            _, b = best
            self.player_x = clamp(b.x, b.x - b.w/2 + 0.8, b.x + b.w/2 - 0.8)
            self.player_z = b.z + b.d * 0.5
            self.player_y = b.h
            self.player_vy = 0.0
            self.player_on_ground = True
            self.spawn_particles(8)
            return True
        return False

    def respawn(self):
        # deterministic respawn to first early building
        start = None
        for b in self.buildings:
            if b.z < 40.0:
                start = b
                break
        if start is None:
            start = self.buildings[0]
        self.player_x = start.x
        self.player_z = start.z + start.d * 0.5
        self.player_y = start.h
        self.player_vy = 0.0
        self.player_on_ground = True
        self.respawn_cooldown = 0.25
        self.particles = []

    def update(self, dt, inputs):
        if self.state != 'play':
            return

        if self.respawn_cooldown > 0:
            self.respawn_cooldown = max(0.0, self.respawn_cooldown - dt)

        # movement relative to camera yaw: FORWARD points where the camera faces (towards player),
        # but we want pressing W to move toward camera-forward direction on-screen.
        yaw = self.cam_yaw
        # fix orientation so pressing W moves the expected direction (previous flipped behavior corrected)
        forward_x = -math.sin(yaw)
        forward_z = -math.cos(yaw)
        right_x = math.cos(yaw)
        right_z = -math.sin(yaw)

        in_left = inputs['left']
        in_right = inputs['right']
        in_up = inputs['up']
        in_down = inputs['down']

        move_lr = 0.0
        move_fb = 0.0
        if in_left: move_lr -= 1.0
        if in_right: move_lr += 1.0
        if in_up: move_fb += 1.0
        if in_down: move_fb -= 0.6

        # combine
        vx = forward_x * move_fb + right_x * move_lr
        vz = forward_z * move_fb + right_z * move_lr
        mag = math.hypot(vx, vz)
        if mag > 0.001:
            vx /= mag; vz /= mag
        speed = self.player_sprint if move_fb > 0.1 else self.player_walk
        self.player_x += vx * speed * dt
        self.player_z += vz * speed * dt
        self.player_x = clamp(self.player_x, -240.0, 240.0)

        # jump input
        if inputs['jump'] and self.player_on_ground and self.respawn_cooldown <= 0:
            self.player_vy = self.player_jump
            self.player_on_ground = False
            self.spawn_particles(8)

        # physics
        self.player_vy += GRAVITY * dt
        self.player_y += self.player_vy * dt

        # check roof landings
        landed = None
        for b in self.buildings:
            if b.contains_roof(self.player_x, self.player_z):
                if self.player_vy <= 1.2 and self.player_y <= b.h + 0.18:
                    landed = b
                    break
        if landed:
            self.player_y = landed.h
            self.player_vy = 0.0
            self.player_on_ground = True
        else:
            if self.player_y <= -6.0:
                self.respawn()
                return

        # camera rotation only while LMB held: mouse relative movement handled in run()
        # update camera to follow player
        self.update_camera_immediate()

        # update particles cheaply
        newparts = []
        for p in self.particles:
            p['life'] -= dt
            if p['life'] > 0:
                p['vy'] -= 9.8 * dt
                p['y'] += p['vy'] * dt
                p['z'] += 0.6 * dt
                newparts.append(p)
        self.particles = newparts

        # level completion
        last = self.buildings[-1]
        if self.player_z > last.z + last.d*0.6 and not self.level_completed:
            self.level_completed = True
            self.victory_timer = 1.0

        if self.level_completed:
            self.victory_timer -= dt
            if self.victory_timer <= 0:
                # proceed to next level if exists
                if self.level_index < len(LEVELS) - 1:
                    self.level_index += 1
                    self.reset_world(self.level_index)
                else:
                    self.state = 'victory'

    def draw(self):
        s = self.screen
        s.fill((10,10,18))

        # sky gradient
        for i in range(120):
            a = i / 119.0
            color = (int(8 + a*12), int(12 + a*28), int(30 + a*60))
            pygame.draw.rect(s, color, (0, int(i * WIN_H / 240), WIN_W, int(WIN_H / 240)+1))

        fov = 900.0

        # collect face polygons for all building faces, compute average camera depth (cz)
        face_list = []
        for b in self.buildings:
            x0 = b.x - b.w/2; x1 = b.x + b.w/2
            z0 = b.z; z1 = b.z + b.d
            y0 = 0.0; y1 = b.h
            verts = [
                Vec3(x0,y0,z0), Vec3(x1,y0,z0), Vec3(x1,y0,z1), Vec3(x0,y0,z1),
                Vec3(x0,y1,z0), Vec3(x1,y1,z0), Vec3(x1,y1,z1), Vec3(x0,y1,z1)
            ]
            # faces defined by 4 indices (consistent winding doesn't matter here)
            faces = [
                (0,1,2,3),  # front (near z0)
                (4,5,6,7),  # back  (near z1)
                (0,1,5,4),  # bottom
                (3,2,6,7),  # top
                (1,2,6,5),  # right
                (0,3,7,4)   # left
            ]
            # colors based on height for variety
            base = clamp(int(70 + (b.h / 26.0) * 60), 40, 220)
            face_color = (base-8, base-4, base//2)
            side_color = (max(0, base-22), max(0, base-18), max(0, base//3))
            top_color = (min(255, base+12), min(255, base+28), min(255, base+40))

            for fi, inds in enumerate(faces):
                poly_world = [verts[i] for i in inds]
                proj = [project_point(v, self.cam_pos, self.forward, self.right, self.up, fov) for v in poly_world]
                poly2 = [(p[0], p[1]) for p in proj]
                czs = [p[3] for p in proj]
                avg_cz = sum(czs)/len(czs)
                if avg_cz <= 0.05: 
                    continue
                # choose color per face
                if fi == 3:
                    col = top_color
                elif fi in (2,):
                    col = (28,28,30)
                elif fi in (1,):
                    col = side_color
                else:
                    col = face_color
                face_list.append({'cz': avg_cz, 'poly': poly2, 'col': col})

        # sort faces far->near so nearer faces draw last (occlude behind ones)
        face_list.sort(key=lambda it: it['cz'], reverse=True)

        # draw faces
        for f in face_list:
            poly = f['poly']
            if safe_poly(poly):
                try:
                    pygame.draw.polygon(s, f['col'], poly)
                    pygame.draw.polygon(s, (12,12,14), poly, 1)
                except Exception:
                    pass

        # draw player as simple capsule on top
        ppos = Vec3(self.player_x, self.player_y + PLAYER_HEIGHT*0.25, self.player_z)
        psx, psy, psc, pcz = project_point(ppos, self.cam_pos, self.forward, self.right, self.up, fov)
        if isfinite(psx) and isfinite(psy) and isfinite(psc) and psc > 0:
            sc = clamp(psc, 0.02, 6.5)
            pw = int(clamp(22*sc, 10, 64))
            ph = int(clamp(40*sc, 14, 140))
            shadow = pygame.Surface((pw*2, max(4,int(pw*0.5))), pygame.SRCALPHA)
            pygame.draw.ellipse(shadow, (0,0,0,150), shadow.get_rect())
            s.blit(shadow, (int(psx - shadow.get_width()//2), int(psy - ph*0.18 + shadow.get_height()//2)))
            body = pygame.Rect(int(psx - pw//2), int(psy - ph), pw, ph)
            pygame.draw.rect(s, (34,34,38), body, border_radius=max(5, pw//4))
            rim = (220, 190, 140)
            pygame.draw.rect(s, rim, body, width=max(1, pw//12), border_radius=max(4,pw//4))
            head_w = int(pw*0.6); head_h = int(ph*0.26)
            pygame.draw.ellipse(s, rim, (int(psx - head_w//2), int(psy - ph - head_h//2), head_w, head_h))

        # particles
        for p in self.particles:
            ppx, ppy, pps, pcz = project_point(Vec3(p['x'], p['y'], p['z']), self.cam_pos, self.forward, self.right, self.up, fov)
            if isfinite(ppx) and isfinite(ppy) and isfinite(pps) and pps > 0:
                r = int(clamp(2.0*pps, 1, 6))
                pygame.draw.circle(s, (200,200,220), (int(ppx), int(ppy)), r)

        # nearest candidate (ahead) for hint whether E is required
        candidate = None; best = None
        for b in self.buildings:
            rz = b.z + b.d*0.5
            if rz <= self.player_z - 0.8: continue
            dx = b.x - self.player_x; dz = rz - self.player_z
            score = dx*dx + dz*dz
            if best is None or score < best:
                best = score; candidate = b

        if candidate:
            rz = candidate.z + candidate.d*0.5
            dx = abs(candidate.x - self.player_x); dz = rz - self.player_z
            horiz = math.hypot(dx, dz)
            can_horiz = horiz <= max_jump_horizontal(self.player_sprint, self.player_jump, GRAVITY) * 1.02
            jump_up = max_jump_up(self.player_jump, GRAVITY)
            climb_thresh = jump_up * 1.05 + 1.6
            # project rooftop for outline
            x0 = candidate.x - candidate.w/2; x1 = candidate.x + candidate.w/2
            z0 = candidate.z; z1 = candidate.z + candidate.d
            y1 = candidate.h
            top_world = [Vec3(x0,y1,z0), Vec3(x1,y1,z0), Vec3(x1,y1,z1), Vec3(x0,y1,z1)]
            top_proj = [project_point(v, self.cam_pos, self.forward, self.right, self.up, fov) for v in top_world]
            poly_top = [(p[0], p[1]) for p in top_proj]
            vdelta = candidate.h - self.player_y
            if vdelta > jump_up + 0.6 and vdelta <= climb_thresh and can_horiz:
                if safe_poly(poly_top):
                    pygame.draw.polygon(s, (255, 60, 60, 80), poly_top, 3)
                    txt = self.big.render("E REQUIRED", True, (255,200,200))
                    s.blit(txt, (WIN_W//2 - txt.get_width()//2, WIN_H - 120))
            elif vdelta <= jump_up + 0.6 and can_horiz:
                if safe_poly(poly_top):
                    pygame.draw.lines(s, (140,255,170), True, poly_top, 3)
                    hint = self.font.render("Jumpable", True, (180,255,180))
                    s.blit(hint, (WIN_W//2 - hint.get_width()//2, WIN_H - 120))

        # HUD
        self.draw_ui()

        # victory overlay
        if self.level_completed:
            overlay = pygame.Surface((WIN_W, WIN_H), pygame.SRCALPHA); overlay.fill((0,0,0,120)); s.blit(overlay,(0,0))
            txt = self.big.render("LEVEL COMPLETE", True, (200,230,255)); s.blit(txt, (WIN_W//2 - txt.get_width()//2, WIN_H//2 - 40))

    def draw_ui(self):
        hud_x, hud_y = 12, 12
        lvl = self.level_index + 1
        elapsed = int(time.time() - self.time_start)
        txt = f"Level {lvl}   Time {elapsed}s"
        surf = self.font.render(txt, True, (200, 220, 255))
        self.screen.blit(surf, (hud_x, hud_y))
        controls = "WASD/Arrows move (relative to camera), Space jump, E mantle, R reset level+camera, LMB hold rotate, Wheel zoom"
        surf2 = self.font.render(controls, True, (170,190,210))
        self.screen.blit(surf2, (12, WIN_H - 26))

    # ---------------- Menu / level select small UI ----------------
    def menu_draw(self):
        s = self.screen
        s.fill((8,8,12))
        title = self.big.render("ROOFTOP PARKOUR (restored)", True, (255,200,220)); s.blit(title, (WIN_W//2 - title.get_width()//2, 80))
        lines = ["Start", "Level Select", "Quit"]
        for i, l in enumerate(lines):
            color = (255,220,160) if i == self.menu_index else (180,200,230)
            txt = self.font.render(l, True, color); s.blit(txt, (WIN_W//2 - txt.get_width()//2, 250 + i*44))
        hint = self.font.render("Use Up/Down and Enter. Esc to quit.", True, (160,180,200)); s.blit(hint, (WIN_W//2 - hint.get_width()//2, WIN_H - 60))

    def level_select_draw(self):
        s = self.screen
        s.fill((8,8,16))
        title = self.big.render("Select Level (1-5) with Left/Right. Enter to play.", True, (220,200,255)); s.blit(title, (WIN_W//2 - title.get_width()//2, 60))
        for i in range(len(LEVELS)):
            x = 160 + i*190; y = 180; w = 160; h = 90
            rect = pygame.Rect(x,y,w,h)
            color = (58,48,78) if i != self.selected_level else (120,80,140)
            pygame.draw.rect(s, color, rect, border_radius=8)
            txt = self.font.render(f"Level {i+1}", True, (230,230,255)); s.blit(txt, (x+12, y+12))

    # ---------------- Main loop ----------------
    def run(self):
        running = True
        inputs = {'left':False,'right':False,'up':False,'down':False,'jump':False}
        pygame.mouse.get_rel()  # flush
        while running:
            dt = self.clock.tick(FPS) / 1000.0
            events = pygame.event.get()
            for ev in events:
                if ev.type == pygame.QUIT:
                    running = False
                if self.state == 'play':
                    if ev.type == pygame.MOUSEBUTTONDOWN:
                        if ev.button == 1:
                            self.lmb_held = True
                            pygame.mouse.get_rel()
                        elif ev.button == 4:
                            self.cam_dist = clamp(self.cam_dist * 0.92, CAM_DIST_MIN, CAM_DIST_MAX)
                        elif ev.button == 5:
                            self.cam_dist = clamp(self.cam_dist / 0.92, CAM_DIST_MIN, CAM_DIST_MAX)
                    elif ev.type == pygame.MOUSEBUTTONUP:
                        if ev.button == 1:
                            self.lmb_held = False
                            pygame.mouse.get_rel()
                    elif ev.type == pygame.KEYDOWN:
                        if ev.key in (pygame.K_a, pygame.K_LEFT): inputs['left'] = True
                        if ev.key in (pygame.K_d, pygame.K_RIGHT): inputs['right'] = True
                        if ev.key in (pygame.K_w, pygame.K_UP): inputs['up'] = True
                        if ev.key in (pygame.K_s, pygame.K_DOWN): inputs['down'] = True
                        if ev.key == pygame.K_SPACE: inputs['jump'] = True
                        if ev.key == pygame.K_e: self.attempt_climb()
                        if ev.key == pygame.K_r:
                            # reset level AND camera angle (deterministic)
                            self.reset_world(self.level_index)
                        if ev.key == pygame.K_p:
                            self.state = 'paused' if self.state == 'play' else 'play'
                        if ev.key == pygame.K_ESCAPE:
                            self.state = 'menu'
                    elif ev.type == pygame.KEYUP:
                        if ev.key in (pygame.K_a, pygame.K_LEFT): inputs['left'] = False
                        if ev.key in (pygame.K_d, pygame.K_RIGHT): inputs['right'] = False
                        if ev.key in (pygame.K_w, pygame.K_UP): inputs['up'] = False
                        if ev.key in (pygame.K_s, pygame.K_DOWN): inputs['down'] = False
                        if ev.key == pygame.K_SPACE: inputs['jump'] = False
                elif self.state == 'menu':
                    if ev.type == pygame.KEYDOWN:
                        if ev.key == pygame.K_UP: self.menu_index = max(0, self.menu_index - 1)
                        if ev.key == pygame.K_DOWN: self.menu_index = min(2, self.menu_index + 1)
                        if ev.key == pygame.K_RETURN:
                            if self.menu_index == 0:
                                self.reset_world(self.selected_level); self.state = 'play'
                            elif self.menu_index == 1:
                                self.state = 'level_select'
                            else:
                                running = False
                        if ev.key == pygame.K_ESCAPE:
                            running = False
                elif self.state == 'level_select':
                    if ev.type == pygame.KEYDOWN:
                        if ev.key == pygame.K_LEFT:
                            self.selected_level = max(0, self.selected_level - 1)
                        if ev.key == pygame.K_RIGHT:
                            self.selected_level = min(len(LEVELS)-1, self.selected_level + 1)
                        if ev.key == pygame.K_RETURN:
                            self.reset_world(self.selected_level); self.state = 'play'
                        if ev.key == pygame.K_ESCAPE:
                            self.state = 'menu'
                elif self.state == 'paused':
                    if ev.type == pygame.KEYDOWN and ev.key == pygame.K_p:
                        self.state = 'play'
                elif self.state == 'victory':
                    if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                        self.state = 'menu'

            # handle mouse rotation only while LMB held
            if self.state == 'play' and self.lmb_held:
                mx, my = pygame.mouse.get_rel()
                self.cam_yaw += -mx * self.yaw_sens
                self.cam_pitch += -my * self.pitch_sens
                self.cam_pitch = clamp(self.cam_pitch, CAM_PITCH_MIN, CAM_PITCH_MAX)
            else:
                # flush movement if not rotating
                pygame.mouse.get_rel()

            # update world
            if self.state == 'play':
                self.update(dt, inputs)
                self.draw()
            elif self.state == 'menu':
                self.menu_draw()
            elif self.state == 'level_select':
                self.level_select_draw()
            elif self.state == 'paused':
                self.draw()
                overlay = pygame.Surface((WIN_W,WIN_H), pygame.SRCALPHA); overlay.fill((0,0,0,160)); self.screen.blit(overlay,(0,0))
                txt = self.big.render("PAUSED", True, (220,220,255)); self.screen.blit(txt, (WIN_W//2 - txt.get_width()//2, WIN_H//2 - 20))
            elif self.state == 'victory':
                self.draw()

            pygame.display.flip()

        pygame.quit()
        sys.exit()

# ---------- Run ----------
if __name__ == "__main__":
    Game().run()
