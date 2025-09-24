import pygame, sys, math, random, time
from math import radians, sqrt, isfinite

# ---------- Settings ----------
WIN_W, WIN_H = 1200, 720
FPS = 60

# Camera
CAM_DIST_DEFAULT = 24.0
CAM_PITCH_DEFAULT = radians(18.0)
CAM_PITCH_MIN = radians(-8.0)
CAM_PITCH_MAX = radians(58.0)
CAM_DIST_MIN = 8.0
CAM_DIST_MAX = 72.0

# Player / physics
GRAVITY = -32.0
JUMP_V = 14.0
WALK_SPEED = 10.6
SPRINT_SPEED = 22.0
PLAYER_HEIGHT = 1.9

# Player render base
PLAYER_BASE_W = 28
PLAYER_BASE_H = 56

# Sprint
SPRINT_MAX_ENERGY = 3.2
SPRINT_DRAIN_RATE = 1.0
SPRINT_REGEN_RATE = 0.45

# Mantle
MANTLE_TIME = 0.72

# Building
BUILDING_DEPTH = 14.0
EPS = 1e-5
VIS_MULT = 3.0  # visual height multiplier (visual top used for collisions/render)

# Player collision
PLAYER_RADIUS = 0.45

# Levels
NUM_LEVELS = 20

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

def max_jump_horizontal(speed, jump_v=JUMP_V, gravity=GRAVITY):
    g = abs(gravity)
    if g <= 0: return 0.0
    airtime = 2.0 * jump_v / g
    return speed * airtime * 0.92

def max_jump_up(jump_v=JUMP_V, gravity=GRAVITY):
    g = abs(gravity)
    if g <= 0: return 0.0
    return (jump_v * jump_v) / (2.0 * g)

# ---------- Projection ----------
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
    try:
        xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
    except Exception:
        return False
    for x,y in poly:
        if not isfinite(x) or not isfinite(y): return False
    if (max(xs)-min(xs)) > WIN_W*4 or (max(ys)-min(ys)) > WIN_H*4: return False
    if (max(xs)-min(xs)) < 0.15 and (max(ys)-min(ys)) < 0.15: return False
    return True

# ---------- Building ----------
class Building:
    def __init__(self, x_center, z_start, width, depth, height_physical):
        self.x = float(x_center)
        self.z = float(z_start)
        self.w = float(width)
        self.d = float(depth)
        self.h = float(height_physical)                # gameplay physical height (kept)
        self.h_visual = float(height_physical) * VIS_MULT  # visual/collision height

    def roof_center_z(self):
        return self.z + self.d * 0.5

    def contains_roof(self, x, z):
        return (x >= self.x - self.w/2 - 1e-6) and (x <= self.x + self.w/2 + 1e-6) and (z >= self.z - 1e-6) and (z <= self.z + self.d + 1e-6)

# ---------- LEVELS: programmatic ramp 1..20 ----------
LEVELS = []
for i in range(NUM_LEVELS):
    difficulty = i / (NUM_LEVELS - 1)
    num_buildings = int(5 + difficulty * 18)  # grows
    lanes_count = 1 + int(difficulty * 7)
    spread = 6 + difficulty * 36
    if lanes_count > 1:
        lanes = [(-spread/2.0) + j * (spread/(lanes_count-1)) for j in range(lanes_count)]
    else:
        lanes = [0.0]
    min_w = 5.0 + difficulty * 3.0
    max_w = 7.0 + difficulty * 6.0
    min_h = 6.0 + difficulty * 10.0
    max_h = min_h + 6.0 + difficulty * 30.0
    gap_min = 1.0 + difficulty * 2.6
    gap_max = gap_min + 1.2 + difficulty * 3.8
    LEVELS.append({'num_buildings':num_buildings, 'lanes':lanes,
                   'min_w':min_w, 'max_w':max_w, 'min_h':min_h, 'max_h':max_h,
                   'gap_min':gap_min, 'gap_max':gap_max})

# ---------- Game ----------
class Game:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((WIN_W, WIN_H))
        pygame.display.set_caption("Apex Runner")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("consolas", 18)
        self.small_font = pygame.font.SysFont("consolas", 13)
        self.big = pygame.font.SysFont("consolas", 34, bold=True)

        # start facing buildings
        self.cam_yaw = math.pi
        self.cam_pitch = CAM_PITCH_DEFAULT
        self.cam_dist = CAM_DIST_DEFAULT
        self.yaw_sens = 0.0045
        self.pitch_sens = 0.0045

        self.level_index = 0
        self.seed_base = 12345
        self.lmb_held = False

        self.state = 'menu'
        self.menu_index = 0
        self.selected_level = 0

        self.bg_offset = 0.0
        self.prev_player_z = 0.0

        # in-memory best times
        self.best_times = {}

        self.reset_world(0)

    def level_seed(self, idx):
        return self.seed_base + idx * 7919

    def reset_world(self, level_idx=0):
        self.cam_pitch = CAM_PITCH_DEFAULT
        self.cam_dist = CAM_DIST_DEFAULT

        self.level_index = clamp(level_idx, 0, len(LEVELS)-1)
        cfg = LEVELS[self.level_index]
        rng = random.Random(self.level_seed(self.level_index))

        self.buildings = []
        z = 10.0
        prev = None

        horiz_reach = max_jump_horizontal(SPRINT_SPEED, JUMP_V, GRAVITY)
        max_up = max_jump_up(JUMP_V, GRAVITY)

        i = 0
        tries = 0
        while i < cfg['num_buildings'] and tries < 20000:
            tries += 1
            lane = rng.choice(cfg['lanes'])
            w = rng.uniform(cfg['min_w'], cfg['max_w'])
            midh = (cfg['min_h'] + cfg['max_h']) / 2.0
            h_phys = max(6.0, rng.gauss(midh, (cfg['max_h'] - cfg['min_h']) * 0.12))

            if prev:
                # restrict vertical changes in visual space
                max_visual_up = max_up * 0.98
                if (h_phys * VIS_MULT - prev.h_visual) > max_visual_up:
                    allowed_phys_delta = max_visual_up / VIS_MULT
                    h_phys = prev.h + allowed_phys_delta * rng.uniform(0.6, 1.0)
                if prev.h - h_phys > 45.0:
                    h_phys = prev.h - 45.0 * rng.uniform(0.4, 1.0)

            gap = rng.uniform(cfg['gap_min'], cfg['gap_max'])
            x = lane + rng.uniform(-1.6, 1.6)
            b = Building(x, z, w, BUILDING_DEPTH, h_phys)

            # attempt to ensure center-to-center distance feasible; iteratively nudge/shrink gap
            feasible = False
            if prev is None:
                feasible = True
            else:
                attempts_inner = 0
                while attempts_inner < 6:
                    prev_cz = prev.z + prev.d * 0.5
                    cand_cz = b.z + b.d * 0.5
                    dx = b.x - prev.x
                    dz = cand_cz - prev_cz
                    dist = math.hypot(dx, dz)
                    if dist <= horiz_reach * 0.98:
                        feasible = True
                        break
                    # try shrinking gap first
                    if gap > cfg['gap_min'] * 0.6:
                        gap = max(cfg['gap_min'], gap * 0.6)
                        b.z = z  # will be updated below to z + d + gap, but keep b.z as z now
                        # recompute cand_cz: still b.z + d*0.5 but we postpone setting final z until appended
                    else:
                        # nudge X toward prev.x
                        if abs(b.x - prev.x) > 0.2:
                            b.x = lerp(b.x, prev.x, 0.45)
                        else:
                            b.x = prev.x
                    attempts_inner += 1
                    # recompute b.z based on current z (not incremented yet)
                    b.z = z
                # final check
                prev_cz = prev.z + prev.d * 0.5
                cand_cz = b.z + b.d * 0.5
                dx = b.x - prev.x
                dz = cand_cz - prev_cz
                dist = math.hypot(dx, dz)
                feasible = dist <= horiz_reach * 1.0001

            if not feasible:
                # skip candidate and try new lane/height
                continue

            # finalize
            self.buildings.append(b)
            prev = b
            z += BUILDING_DEPTH + gap
            i += 1

        # pad if needed
        while len(self.buildings) < cfg['num_buildings']:
            x = rng.choice(cfg['lanes'])
            w = rng.uniform(cfg['min_w'], cfg['max_w'])
            h_phys = rng.uniform(cfg['min_h'], cfg['max_h'])
            b = Building(x, z, w, BUILDING_DEPTH, h_phys)
            self.buildings.append(b)
            z += BUILDING_DEPTH + cfg['gap_min']

        self.buildings.sort(key=lambda bb: bb.z)

        # spawn on visual roof of first building
        start = self.buildings[0]
        self.player_x = start.x
        self.player_z = start.z + start.d * 0.5
        self.player_y = start.h_visual + 0.08
        self.player_vy = 0.0
        self.player_on_ground = True

        self.player_walk = WALK_SPEED
        self.player_sprint = SPRINT_SPEED
        self.player_jump = JUMP_V

        self.sprint_energy = SPRINT_MAX_ENERGY
        self.sprinting = False

        self.mantling = False
        self.mantle_target = None
        self.mantle_progress = 0.0
        self.mantle_start_pos = None
        self.mantle_end_pos = None

        self.fell_off = False
        self.left_by_jump = False
        self.prev_on_ground = True

        self.time_start = time.time()
        self.particles = []

        # remove any powerups (user asked)
        self.powerups = []

        self.bg_offset = 0.0
        self.prev_player_z = self.player_z

        self.level_completed = False
        self.victory_timer = 0.0
        self.respawn_cooldown = 0.0
        self.completion_time = None

        self.level_message_timer = 2.0

        pygame.mouse.get_rel()
        self.update_camera_immediate()

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

    def begin_mantle(self, target_building):
        if target_building is None: return
        self.mantling = True
        self.mantle_target = target_building
        self.mantle_progress = 0.0
        end_x = clamp(target_building.x, target_building.x - target_building.w/2 + 0.8, target_building.x + target_building.w/2 - 0.8)
        start_x = clamp(self.player_x, target_building.x - target_building.w, target_building.x + target_building.w)
        start_z = self.player_z
        end_y = target_building.h_visual + 0.02
        self.mantle_start_pos = Vec3(start_x, self.player_y, start_z)
        self.mantle_end_pos = Vec3(end_x, end_y, start_z)
        self.player_vy = 0.0
        self.player_on_ground = False

    def cancel_mantle(self):
        self.mantling = False
        self.mantle_target = None
        self.mantle_progress = 0.0
        self.mantle_start_pos = None
        self.mantle_end_pos = None

    def attempt_mantle_start(self, inputs):
        # If there's a valid candidate (close side & vertical), optionally begin mantle
        climb_thresh = max_jump_up(self.player_jump, GRAVITY) * 1.05 + 1.6
        best = None
        side_margin = 1.6
        for b in self.buildings:
            vdelta = b.h_visual - self.player_y
            if vdelta < 0.4 or vdelta > climb_thresh:
                continue
            dx = self.player_x - b.x
            dz_forward = (b.z + b.d * 0.5) - self.player_z
            in_z_range = (self.player_z >= b.z - 1.2) and (self.player_z <= b.z + b.d + 1.2)
            side_close = (abs(dx) <= b.w/2 + side_margin) and in_z_range
            if side_close:
                score = abs(dx) + abs(dz_forward)*0.6 + abs(vdelta)*0.8
                if best is None or score < best[0]:
                    best = (score, b)
        if best:
            _, b = best
            # allow starting mantle only if E pressed
            if inputs.get('mantle', False):
                self.begin_mantle(b)
            return b
        return None

    def respawn(self):
        start = None
        for b in self.buildings:
            if b.z < 40.0:
                start = b
                break
        if start is None: start = self.buildings[0]
        self.player_x = start.x
        self.player_z = start.z + start.d * 0.5
        self.player_y = start.h_visual + 0.08
        self.player_vy = 0.0
        self.player_on_ground = True
        self.respawn_cooldown = 0.25
        self.particles = []
        self.cancel_mantle()
        self.fell_off = False
        self.left_by_jump = False
        self.prev_on_ground = True
        self.prev_player_z = self.player_z
        self.update_camera_immediate()

    def update(self, dt, inputs):
        if self.state != 'play': return

        if self.respawn_cooldown > 0:
            self.respawn_cooldown = max(0.0, self.respawn_cooldown - dt)
        if self.level_message_timer > 0:
            self.level_message_timer = max(0.0, self.level_message_timer - dt)

        self.prev_on_ground = self.player_on_ground

        # mantling
        if self.mantling:
            if self.mantle_start_pos is None or self.mantle_end_pos is None or self.mantle_target is None:
                self.cancel_mantle()
            else:
                if inputs.get('mantle', False):
                    self.mantle_progress += (dt / MANTLE_TIME)
                    if self.mantle_progress >= 1.0:
                        self.player_x = self.mantle_end_pos.x
                        self.player_z = self.mantle_end_pos.z
                        self.player_y = self.mantle_end_pos.y
                        self.player_vy = 0.0
                        self.player_on_ground = True
                        self.spawn_particles(10)
                        self.fell_off = False
                        self.left_by_jump = False
                        self.cancel_mantle()
                p = clamp(self.mantle_progress, 0.0, 1.0)
                if self.mantle_start_pos is not None and self.mantle_end_pos is not None:
                    sx, sy, sz = self.mantle_start_pos.x, self.mantle_start_pos.y, self.mantle_start_pos.z
                    ex, ey, ez = self.mantle_end_pos.x, self.mantle_end_pos.y, self.mantle_end_pos.z
                    self.player_x = lerp(sx, ex, min(p, 0.15))
                    self.player_y = lerp(sy, ey, p)
                    self.player_z = lerp(sz, ez, min(p, 0.05))
                self.player_vy = 0.0
                self.update_camera_immediate()
                return

        # movement relative to camera
        yaw = self.cam_yaw
        forward_x = -math.sin(yaw)
        forward_z = -math.cos(yaw)
        right_x = math.cos(yaw)
        right_z = -math.sin(yaw)

        in_left = inputs['left']; in_right = inputs['right']; in_up = inputs['up']; in_down = inputs['down']
        move_lr = 0.0; move_fb = 0.0
        if in_left: move_lr -= 1.0
        if in_right: move_lr += 1.0
        if in_up: move_fb += 1.0
        if in_down: move_fb -= 0.6

        vx = forward_x * move_fb + right_x * move_lr
        vz = forward_z * move_fb + right_z * move_lr
        mag = math.hypot(vx, vz)
        if mag > 0.001:
            vx /= mag; vz /= mag

        # sprint
        if inputs.get('sprint', False) and self.sprint_energy > 0.05 and (move_fb > 0.1 or move_lr != 0.0):
            speed = self.player_sprint
            self.sprinting = True
            self.sprint_energy = max(0.0, self.sprint_energy - SPRINT_DRAIN_RATE * dt)
        else:
            self.sprinting = False
            speed = self.player_walk
            self.sprint_energy = clamp(self.sprint_energy + SPRINT_REGEN_RATE * dt, 0.0, SPRINT_MAX_ENERGY)

        final_speed = speed

        prev_x = self.player_x; prev_z = self.player_z

        self.player_x += vx * final_speed * dt
        self.player_z += vz * final_speed * dt
        self.player_x = clamp(self.player_x, -240.0, 240.0)

        # horizontal collision (use visual heights)
        player_bottom = self.player_y
        collided_building = None
        for b in self.buildings:
            bx0 = b.x - b.w/2 - PLAYER_RADIUS
            bx1 = b.x + b.w/2 + PLAYER_RADIUS
            bz0 = b.z - PLAYER_RADIUS
            bz1 = b.z + b.d + PLAYER_RADIUS
            if (self.player_x >= bx0 and self.player_x <= bx1 and
                self.player_z >= bz0 and self.player_z <= bz1):
                if player_bottom < b.h_visual - 0.01:
                    collided_building = b
                    break
        if collided_building:
            self.player_x = prev_x
            self.player_z = prev_z

        # jump
        if inputs['jump'] and self.player_on_ground and self.respawn_cooldown <= 0:
            self.player_vy = self.player_jump
            self.player_on_ground = False
            self.left_by_jump = True
            self.spawn_particles(8)

        # physics
        self.player_vy += GRAVITY * dt
        self.player_y += self.player_vy * dt

        # landings (visual roofs)
        landed = None
        for b in self.buildings:
            if b.contains_roof(self.player_x, self.player_z):
                if self.player_vy <= 1.2 and self.player_y <= b.h_visual + 0.18:
                    landed = b
                    break
        if landed:
            if self.fell_off:
                landed = None
            else:
                self.player_y = landed.h_visual
                self.player_vy = 0.0
                self.player_on_ground = True
                self.fell_off = False
                self.left_by_jump = False
        else:
            if self.player_y <= -8.0:
                self.respawn()
                return
            self.player_on_ground = False

        if self.prev_on_ground and not self.player_on_ground and not self.left_by_jump:
            self.fell_off = True

        mantle_candidate = self.attempt_mantle_start(inputs)

        self.update_camera_immediate()

        # particles
        newparts = []
        for p in self.particles:
            p['life'] -= dt
            if p['life'] > 0:
                p['vy'] -= 9.8 * dt
                p['y'] += p['vy'] * dt
                p['z'] += 0.6 * dt
                newparts.append(p)
        self.particles = newparts

        # background offset
        z_delta = self.player_z - self.prev_player_z
        self.prev_player_z = self.player_z
        self.bg_offset += z_delta * 0.6

        # completion
        last = self.buildings[-1]
        if self.player_z > last.z + last.d*0.6 and not self.level_completed:
            self.level_completed = True
            self.victory_timer = 1.0
            self.completion_time = time.time() - self.time_start

        if self.level_completed:
            self.victory_timer -= dt
            if self.victory_timer <= 0:
                lvl = self.level_index
                prev_best = self.best_times.get(lvl, None)
                if self.completion_time is None:
                    self.completion_time = time.time() - self.time_start
                if prev_best is None or self.completion_time < prev_best - 1e-6:
                    self.best_times[lvl] = round(self.completion_time, 3)
                if self.level_index < len(LEVELS) - 1:
                    self.level_index += 1
                    self.reset_world(self.level_index)
                else:
                    self.state = 'victory'

    def draw_skyline_background(self):
        s = self.screen
        layers = 3
        for layer in range(layers):
            count = 28 - layer*6
            y_base = WIN_H * (0.18 + layer * 0.06)
            color_base = 18 + layer*24
            parallax_mul = 0.6 - layer*0.18
            spacing = WIN_W / max(1, count)
            base_offset = (self.bg_offset * parallax_mul) % (spacing * 2)
            for i in range(count):
                x = (i * spacing - base_offset) % (WIN_W + spacing) - spacing/2
                h = (30 + (i%7)*10 + layer*8) + math.sin(i*0.6 + layer*0.12) * 6
                rect = pygame.Rect(int(x), int(y_base - h), int(spacing * 0.9), int(h))
                c = (clamp(color_base+random.randint(-6,6),0,255), clamp(color_base+random.randint(-6,6),0,255), clamp(color_base+30+layer*6,0,255))
                pygame.draw.rect(s, c, rect)

        # small neon billboard with blue outline and scan line
        bx = int(WIN_W*0.625); by = int(WIN_H*0.13)
        bw = 220; bh = 56
        # outer neon outline
        outline = pygame.Surface((bw+20, bh+20), pygame.SRCALPHA)
        for i in range(6):
            a = int(40 - i*6)
            pygame.draw.rect(outline, (30,140,200,a), (i, i, bw+20-2*i, bh+20-2*i), border_radius=10, width=2)
        s.blit(outline, (bx-10, by-10))
        # panel
        panel = pygame.Surface((bw, bh), pygame.SRCALPHA)
        panel.fill((8,10,14,220))
        # subtle noise lines
        for row in range(3):
            yoff = 6 + row*14
            pygame.draw.line(panel, (10,14,20,70), (8, yoff), (bw-8, yoff))
        pygame.draw.rect(panel, (18,40,60), (4,4,bw-8,bh-8), border_radius=8, width=2)
        s.blit(panel, (bx, by))

        # neon text with small animated glow and a scan line
        t = time.time() - getattr(self, 'time_start', 0.0)
        title = "APEX CITY"
        glow = self.big.render(title, True, (80,200,240))
        glow.set_alpha(40 + int((math.sin(t*2.0) + 1.0) * 30))
        s.blit(glow, (bx + 12, by + 6))
        txt = self.big.render(title, True, (140,230,255))
        s.blit(txt, (bx + 10, by + 4))
        # scan line
        scan_w = 160
        scan_x = int(((t * 160) + (self.bg_offset*0.12)) % (bw + scan_w) - scan_w/2)
        scan_rect = pygame.Rect(bx + scan_x, by + int(bh*0.72), int(scan_w*0.06), 3)
        pygame.draw.rect(s, (80,200,255), scan_rect)

    def draw(self):
        s = self.screen
        s.fill((8,8,12))

        # sky gradient
        for i in range(120):
            a = i / 119.0
            color = (int(8 + a*12), int(12 + a*28), int(30 + a*60))
            pygame.draw.rect(s, color, (0, int(i * WIN_H / 240), WIN_W, int(WIN_H / 240)+1))

        # skyline
        self.draw_skyline_background()

        fov = 900.0

        # collect faces with visual heights
        face_list = []
        for idx, b in enumerate(self.buildings):
            x0 = b.x - b.w/2; x1 = b.x + b.w/2
            z0 = b.z; z1 = b.z + b.d
            y0 = 0.0; y1 = b.h_visual
            verts_world = [
                Vec3(x0,y0,z0), Vec3(x1,y0,z0), Vec3(x1,y0,z1), Vec3(x0,y0,z1),
                Vec3(x0,y1,z0), Vec3(x1,y1,z0), Vec3(x1,y1,z1), Vec3(x0,y1,z1)
            ]
            faces = [
                (0,1,2,3),  # front (near z0)
                (4,5,6,7),  # back  (near z1)
                (0,1,5,4),  # bottom
                (3,2,6,7),  # top
                (1,2,6,5),  # right
                (0,3,7,4)   # left
            ]
            base = clamp(int(60 + (b.h / 40.0) * 80), 40, 210)
            face_color = (max(10, base-8), max(12, base-6), max(24, base+6))
            side_color = (max(8, base-28), max(8, base-18), max(24, base+8))
            top_color = (min(255, base+18), min(255, base+36), min(255, base+64))

            for fi, inds in enumerate(faces):
                poly_world = [verts_world[i] for i in inds]
                proj = [project_point(v, self.cam_pos, self.forward, self.right, self.up, fov) for v in poly_world]
                poly2 = [(p[0], p[1]) for p in proj]
                czs = [p[3] for p in proj]
                avg_cz = sum(czs)/len(czs)
                if avg_cz <= 0.05: continue
                if fi == 3:
                    col = top_color
                elif fi in (2,):
                    col = (12,12,14)
                elif fi in (1,):
                    col = side_color
                else:
                    col = face_color
                face_list.append({'cz': avg_cz, 'poly': poly2, 'col': col, 'b_idx': idx, 'proj': proj,
                                  'face_idx': fi, 'poly_world': poly_world, 'building': b})

        # sort far->near
        face_list.sort(key=lambda it: it['cz'], reverse=True)

        # draw faces and embedded rectangular windows (world-space)
        t = time.time() - getattr(self, 'time_start', 0.0)
        for f in face_list:
            poly = f['poly']
            if not poly or not safe_poly(poly):
                continue
            try:
                pygame.draw.polygon(s, f['col'], poly)
                pygame.draw.polygon(s, (10,10,12), poly, 1)
                fi = f['face_idx']
                if fi in (0,1,4,5):
                    pw = f['poly_world']
                    # choose top two by y, bottom two by y
                    sorted_by_y = sorted(pw, key=lambda v: v.y, reverse=True)
                    top_pts = sorted_by_y[:2]
                    bot_pts = sorted_by_y[2:]
                    # pair left/right by camera right axis
                    pair = sorted(zip(top_pts, bot_pts), key=lambda pr: dot(pr[0], self.right))
                    if len(pair) == 2:
                        (tL, bL), (tR, bR) = (pair[0][0], pair[0][1]), (pair[1][0], pair[1][1])
                        # estimate screen height to pick rows/cols
                        mid_top = Vec3((tL.x + tR.x)/2.0, (tL.y + tR.y)/2.0, (tL.z + tR.z)/2.0)
                        mid_bot = Vec3((bL.x + bR.x)/2.0, (bL.y + bR.y)/2.0, (bL.z + bR.z)/2.0)
                        pt_top = project_point(mid_top, self.cam_pos, self.forward, self.right, self.up, fov)
                        pt_bot = project_point(mid_bot, self.cam_pos, self.forward, self.right, self.up, fov)
                        screen_h = abs(pt_bot[1] - pt_top[1]) if isfinite(pt_top[1]) and isfinite(pt_bot[1]) else 80
                        rows = 3 if screen_h < 80 else 5 if screen_h < 180 else 8
                        cols = 2 if screen_h < 80 else 4 if screen_h < 180 else 6
                        pad_u = 0.10
                        pad_v = 0.08
                        idx_counter = 0
                        for r in range(rows):
                            u0 = (r + pad_u) / rows
                            u1 = (r + 1 - pad_u) / rows
                            for c in range(cols):
                                v0 = (c + pad_v) / cols
                                v1 = (c + 1 - pad_v) / cols
                                # bilinear corners
                                bottom_v0 = Vec3(lerp(bL.x, bR.x, v0), lerp(bL.y, bR.y, v0), lerp(bL.z, bR.z, v0))
                                bottom_v1 = Vec3(lerp(bL.x, bR.x, v1), lerp(bL.y, bR.y, v1), lerp(bL.z, bR.z, v1))
                                top_v0 = Vec3(lerp(tL.x, tR.x, v0), lerp(tL.y, tR.y, v0), lerp(tL.z, tR.z, v0))
                                top_v1 = Vec3(lerp(tL.x, tR.x, v1), lerp(tL.y, tR.y, v1), lerp(tL.z, tR.z, v1))
                                p00 = Vec3(lerp(bottom_v0.x, top_v0.x, u0), lerp(bottom_v0.y, top_v0.y, u0), lerp(bottom_v0.z, top_v0.z, u0))
                                p10 = Vec3(lerp(bottom_v1.x, top_v1.x, u0), lerp(bottom_v1.y, top_v1.y, u0), lerp(bottom_v1.z, top_v1.z, u0))
                                p11 = Vec3(lerp(bottom_v1.x, top_v1.x, u1), lerp(bottom_v1.y, top_v1.y, u1), lerp(bottom_v1.z, top_v1.z, u1))
                                p01 = Vec3(lerp(bottom_v0.x, top_v0.x, u1), lerp(bottom_v0.y, top_v0.y, u1), lerp(bottom_v0.z, top_v0.z, u1))
                                quad_world = [p00, p10, p11, p01]
                                quad_proj = [project_point(q, self.cam_pos, self.forward, self.right, self.up, fov) for q in quad_world]
                                quad = [(q[0], q[1]) for q in quad_proj]
                                if safe_poly(quad):
                                    # animated subtle glow (time + index)
                                    glow = 0.6 + 0.4 * math.sin(t * 2.0 + idx_counter * 0.42)
                                    rcol = int(clamp(28 * glow, 12, 60))
                                    gcol = int(clamp(85 * glow, 40, 120))
                                    bcol = int(clamp(110 * glow, 60, 160))
                                    pygame.draw.polygon(s, (rcol, gcol, bcol), quad)
                                    pygame.draw.polygon(s, (10,10,12), quad, 1)
                                idx_counter += 1
            except Exception:
                continue

        # draw player (improved but basic stylized silhouette)
        ppos = Vec3(self.player_x, self.player_y + PLAYER_HEIGHT*0.25, self.player_z)
        psx, psy, psc, pcz = project_point(ppos, self.cam_pos, self.forward, self.right, self.up, fov)

        if isfinite(psx) and isfinite(psy) and isfinite(pcz) and pcz > 0:
            # scale by camera distance (closer => larger)
            scale = clamp((CAM_DIST_DEFAULT / max(1e-3, self.cam_dist)), 0.35, 3.6)
            pw = max(12, int(PLAYER_BASE_W * scale))
            ph = max(18, int(PLAYER_BASE_H * scale))
            # shadow
            shadow_w = pw * 1.6; shadow_h = max(4, int(pw * 0.32))
            shadow = pygame.Surface((int(shadow_w), shadow_h), pygame.SRCALPHA)
            pygame.draw.ellipse(shadow, (0,0,0,160), shadow.get_rect())
            s.blit(shadow, (int(psx - shadow.get_width()//2), int(psy - ph*0.18 + shadow.get_height()//2)))
            # torso (dark but with mild accent)
            body_rect = pygame.Rect(int(psx - pw//2), int(psy - ph), pw, ph)
            pygame.draw.rect(s, (28,28,30), body_rect, border_radius=max(6, pw//6))
            # chest panel
            chest = pygame.Rect(int(psx - pw*0.28), int(psy - int(ph * 0.78)), int(pw*0.56), int(ph*0.44))
            pygame.draw.rect(s, (46,58,68), chest, border_radius=4)
            # shoulder pads
            sp_w = int(pw*0.28); sp_h = int(ph*0.18)
            pygame.draw.rect(s, (36,36,40), (int(psx - pw//2 - 2), int(psy - ph + 4), sp_w, sp_h), border_radius=4)
            pygame.draw.rect(s, (36,36,40), (int(psx + pw//2 - sp_w + 2), int(psy - ph + 4), sp_w, sp_h), border_radius=4)
            # head (helmet)
            head_w = int(pw*0.64); head_h = int(ph*0.28)
            pygame.draw.ellipse(s, (38,38,40), (int(psx - head_w//2), int(psy - ph - head_h//2), head_w, head_h))
            # visor subtle
            visor = pygame.Surface((int(head_w*0.6), int(head_h*0.36)), pygame.SRCALPHA)
            pygame.draw.ellipse(visor, (80,120,140,140), visor.get_rect())
            s.blit(visor, (int(psx - (head_w*0.6)/2), int(psy - ph - head_h*0.5)))

        # particles
        for p in self.particles:
            ppx, ppy, pps, pcz = project_point(Vec3(p['x'], p['y'], p['z']), self.cam_pos, self.forward, self.right, self.up, fov)
            if isfinite(ppx) and isfinite(ppy) and isfinite(pps) and pps > 0:
                r = int(clamp(2.0*pps, 1, 6))
                pygame.draw.circle(s, (200,200,220), (int(ppx), int(ppy)), r)

        # mantle/jump hints
        candidate = None; best = None
        for b in self.buildings:
            rz = b.z + b.d*0.5
            dx = b.x - self.player_x; dz = rz - self.player_z
            score = dx*dx + dz*dz
            if best is None or score < best:
                best = score; candidate = b

        mantle_available = False
        if candidate:
            vdelta = candidate.h_visual - self.player_y
            side_margin = 1.6
            in_z_range = (self.player_z >= candidate.z - 1.2) and (self.player_z <= candidate.z + candidate.d + 1.2)
            side_close = (abs(self.player_x - candidate.x) <= candidate.w/2 + side_margin) and in_z_range
            climb_thresh = max_jump_up(self.player_jump, GRAVITY) * 1.05 + 1.6
            # show hint if fallen OR if player is slightly below roof (makes hint more reliable)
            show_hint_condition = (self.fell_off or (self.player_y < candidate.h_visual - 0.6))
            if show_hint_condition and side_close and 0.4 <= vdelta <= climb_thresh:
                mantle_available = True
                x0 = candidate.x - candidate.w/2; x1 = candidate.x + candidate.w/2
                z0 = candidate.z; z1 = candidate.z + candidate.d
                y1 = candidate.h_visual
                top_world = [Vec3(x0,y1,z0), Vec3(x1,y1,z0), Vec3(x1,y1,z1), Vec3(x0,y1,z1)]
                top_proj = [project_point(v, self.cam_pos, self.forward, self.right, self.up, fov) for v in top_world]
                poly_top = [(p[0], p[1]) for p in top_proj]
                if safe_poly(poly_top):
                    pygame.draw.polygon(s, (255, 100, 100), poly_top, 3)
                    txt = self.big.render("HOLD E TO MANTLE", True, (255,200,200))
                    s.blit(txt, (WIN_W//2 - txt.get_width()//2, WIN_H - 120))
            else:
                horiz = math.hypot(abs(candidate.x - self.player_x), abs((candidate.z + candidate.d*0.5) - self.player_z))
                can_horiz = horiz <= max_jump_horizontal(self.player_sprint, self.player_jump, GRAVITY) * 1.02
                jump_up = max_jump_up(self.player_jump, GRAVITY)
                if vdelta <= jump_up + 0.6 and can_horiz:
                    x0 = candidate.x - candidate.w/2; x1 = candidate.x + candidate.w/2
                    z0 = candidate.z; z1 = candidate.z + candidate.d
                    y1 = candidate.h_visual
                    top_world = [Vec3(x0,y1,z0), Vec3(x1,y1,z0), Vec3(x1,y1,z1), Vec3(x0,y1,z1)]
                    top_proj = [project_point(v, self.cam_pos, self.forward, self.right, self.up, fov) for v in top_world]
                    poly_top = [(p[0], p[1]) for p in top_proj]
                    if safe_poly(poly_top):
                        pygame.draw.lines(s, (120,200,160), True, poly_top, 3)

        # goal marker
        final_b = self.buildings[-1]
        top_world = [Vec3(final_b.x - final_b.w/4, final_b.h_visual + 1.2, final_b.z + final_b.d*0.5),
                     Vec3(final_b.x + final_b.w/4, final_b.h_visual + 1.2, final_b.z + final_b.d*0.5)]
        p1 = project_point(top_world[0], self.cam_pos, self.forward, self.right, self.up, fov)
        p2 = project_point(top_world[1], self.cam_pos, self.forward, self.right, self.up, fov)
        if all(isfinite(v) for v in (p1[0], p1[1], p2[0], p2[1])):
            rx = int((p1[0] + p2[0]) / 2 - 28)
            ry = int(min(p1[1], p2[1]) - 28)
            pygame.draw.rect(s, (220,200,60), (rx, ry, 56, 22), border_radius=4)
            lbl = self.font.render("GOAL", True, (40,24,8))
            s.blit(lbl, (rx + 10, ry + 2))

        # HUD
        self.draw_ui(mantle_available)

        # level start overlay
        if self.level_message_timer > 0:
            overlay = pygame.Surface((WIN_W, 120), pygame.SRCALPHA)
            overlay.fill((6,6,10,180))
            s.blit(overlay, (0, WIN_H//2 - 60))
            txt = self.big.render(f"LEVEL {self.level_index + 1}", True, (220, 240, 255))
            s.blit(txt, (WIN_W//2 - txt.get_width()//2, WIN_H//2 - txt.get_height()//2 - 8))

        # victory overlay
        if self.level_completed:
            overlay = pygame.Surface((WIN_W, WIN_H), pygame.SRCALPHA); overlay.fill((0,0,0,120)); s.blit(overlay,(0,0))
            txt = self.big.render("LEVEL COMPLETE", True, (200,230,255)); s.blit(txt, (WIN_W//2 - txt.get_width()//2, WIN_H//2 - 40))
            comp = self.completion_time if self.completion_time is not None else (time.time() - self.time_start)
            best = self.best_times.get(self.level_index, None)
            info = f"Time: {comp:.3f}s"
            txt2 = self.font.render(info, True, (220,230,255)); s.blit(txt2, (WIN_W//2 - txt2.get_width()//2, WIN_H//2 + 12))
            if best is not None:
                best_txt = f"Best: {best:.3f}s"
                txt3 = self.font.render(best_txt, True, (200,200,200)); s.blit(txt3, (WIN_W//2 - txt3.get_width()//2, WIN_H//2 + 36))

    def draw_ui(self, mantle_available=False):
        hud_x, hud_y = 12, 12
        lvl = self.level_index + 1
        elapsed = time.time() - self.time_start
        txt = f"Level {lvl}   Time {elapsed:.3f}s"
        surf = self.font.render(txt, True, (200, 220, 255))
        self.screen.blit(surf, (hud_x, hud_y))

        best = self.best_times.get(self.level_index, None)
        if best is not None:
            under = elapsed < best
            color = (120, 230, 140) if under else (200,200,200)
            status = "UNDER BEST" if under else ""
            bt_surf = self.font.render(f"Best: {best:.3f}s  {status}", True, color)
            self.screen.blit(bt_surf, (hud_x, hud_y + 22))
        else:
            info = self.font.render("Best: ---", True, (160,180,200))
            self.screen.blit(info, (hud_x, hud_y + 22))

        controls = "WASD/Arrow Keys (move), Space (jump), E (mantle), R (reset)"
        surf2 = self.font.render(controls, True, (170,190,210))
        self.screen.blit(surf2, (12, WIN_H - 26))

        if self.sprint_energy < SPRINT_MAX_ENERGY - 1e-3 or self.sprinting:
            bar_w = 220; bar_h = 12
            x = WIN_W - bar_w - 18; y = 18
            pygame.draw.rect(self.screen, (28,28,32), (x, y, bar_w, bar_h), border_radius=4)
            fill = int((self.sprint_energy / SPRINT_MAX_ENERGY) * (bar_w - 2))
            charge_color = (100,200,100) if self.sprint_energy > 0.3 else (200,100,100)
            pygame.draw.rect(self.screen, charge_color, (x+1, y+1, fill, bar_h-2), border_radius=3)
            lbl = self.font.render("Sprint (G)", True, (200, 220, 240))
            self.screen.blit(lbl, (x, y - 18))

        if self.mantling:
            bar_w = 260; bar_h = 14
            x = WIN_W//2 - bar_w//2; y = WIN_H - 86
            pygame.draw.rect(self.screen, (18,18,22), (x, y, bar_w, bar_h), border_radius=6)
            fill = int(clamp(self.mantle_progress, 0.0, 1.0) * (bar_w - 2))
            pygame.draw.rect(self.screen, (255, 140, 120), (x+1, y+1, fill, bar_h-2), border_radius=5)
            lbl = self.font.render("Mantling...", True, (230, 210, 200))
            self.screen.blit(lbl, (x + bar_w//2 - lbl.get_width()//2, y - 20))

    # ---------------- Menu / level select ----------------
    def menu_draw(self):
        s = self.screen
        s.fill((8,8,12))
        title = self.big.render("APEX RUNNER", True, (255,200,220)); s.blit(title, (WIN_W//2 - title.get_width()//2, 80))
        lines = ["Start", "Level Select", "Quit"]
        for i, l in enumerate(lines):
            color = (255,220,160) if i == self.menu_index else (180,200,230)
            txt = self.font.render(l, True, color); s.blit(txt, (WIN_W//2 - txt.get_width()//2, 250 + i*44))
        hint = self.font.render("Use Up/Down and Enter. Esc to quit.", True, (160,180,200)); s.blit(hint, (WIN_W//2 - hint.get_width()//2, WIN_H - 60))

    def level_select_draw(self):
        s = self.screen
        s.fill((8,8,16))
        title = self.big.render("Select Level (Arrows/Enter).", True, (220,200,255)); s.blit(title, (WIN_W//2 - title.get_width()//2, 40))
        per_row = 10
        start_x = 40
        y_top = 110
        spacing_x = (WIN_W - 2 * start_x) / per_row
        for row in range(2):
            for i in range(per_row):
                idx = row * per_row + i
                if idx >= len(LEVELS): continue
                x = int(start_x + i * spacing_x); y = int(y_top + row * 120)
                w = 96; h = 84
                rect = pygame.Rect(x,y,w,h)
                color = (58,48,78) if idx != self.selected_level else (100,70,140)
                pygame.draw.rect(s, color, rect, border_radius=8)
                txt = self.font.render(f"Level {idx+1}", True, (230,230,255)); s.blit(txt, (x+8, y+8))
                bt = self.best_times.get(idx, None)
                if bt is not None:
                    bt_txt_surf = self.small_font.render(f"Best {bt:.3f}s", True, (120,230,140))
                else:
                    bt_txt_surf = self.small_font.render("Best ---", True, (140,140,160))
                s.blit(bt_txt_surf, (x+6, y + 46))

    # ---------------- Main loop ----------------
    def run(self):
        running = True
        inputs = {'left':False,'right':False,'up':False,'down':False,'jump':False,'mantle':False,'sprint':False}
        pygame.mouse.get_rel()
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
                        if ev.key == pygame.K_e: inputs['mantle'] = True
                        if ev.key == pygame.K_g: inputs['sprint'] = True
                        if ev.key == pygame.K_r:
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
                        if ev.key == pygame.K_e: inputs['mantle'] = False
                        if ev.key == pygame.K_g: inputs['sprint'] = False
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
                        per_row = 10
                        if ev.key == pygame.K_LEFT:
                            self.selected_level = max(0, self.selected_level - 1)
                        if ev.key == pygame.K_RIGHT:
                            self.selected_level = min(len(LEVELS)-1, self.selected_level + 1)
                        if ev.key == pygame.K_UP:
                            self.selected_level = max(0, self.selected_level - per_row)
                        if ev.key == pygame.K_DOWN:
                            self.selected_level = min(len(LEVELS)-1, self.selected_level + per_row)
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

            # mouse rotation while LMB held
            if self.state == 'play' and self.lmb_held:
                mx, my = pygame.mouse.get_rel()
                self.cam_yaw += -mx * self.yaw_sens
                self.cam_pitch += -my * self.pitch_sens
                self.cam_pitch = clamp(self.cam_pitch, CAM_PITCH_MIN, CAM_PITCH_MAX)
            else:
                pygame.mouse.get_rel()

            # update & draw
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

if __name__ == "__main__":
    Game().run()
