# apex_runner_cutscene_audio_ogg.py
# All audio is OGG-only (assets/*.ogg). If .ogg files are missing, game will be silent for those items.

import pygame, sys, math, random, time, os
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

# Levels - reduced to 10
NUM_LEVELS = 10

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

# ---------- LEVELS: programmatic ramp 1..10 with variation ----------
LEVELS = []
for i in range(NUM_LEVELS):
    d = i / max(1, NUM_LEVELS - 1)
    num_buildings = int(3 + d * 18)
    lanes_count = 1 + int(d * 4)
    spread = 3 + d * 36
    if lanes_count > 1:
        lanes = [(-spread/2.0) + j*(spread/(lanes_count-1)) for j in range(lanes_count)]
    else:
        lanes = [0.0]
    min_w = 7.0 - d * 2.0
    max_w = 8.0 + d * 6.0
    min_h = 4.0 + d * 8.0
    max_h = min_h + 6.0 + d * 24.0
    gap_min = 0.6 + d * 2.6
    gap_max = gap_min + 0.6 + d * 3.6
    LEVELS.append({'num_buildings': num_buildings, 'lanes': lanes,
                   'min_w': min_w, 'max_w': max_w, 'min_h': min_h, 'max_h': max_h,
                   'gap_min': gap_min, 'gap_max': gap_max})

if len(LEVELS) >= 10:
    L9 = LEVELS[-1]
    L9['min_w'] = max(4.5, L9['min_w'] - 1.0)
    L9['max_w'] = L9['max_w'] + 1.2
    L9['gap_min'] = L9['gap_min'] + 1.4
    L9['gap_max'] = L9['gap_max'] + 2.4
    L9['min_h'] = L9['min_h'] + 4.0
    L9['max_h'] = L9['max_h'] + 12.0
    L9['lanes'] = L9['lanes'] + [x + 2.6 for x in L9['lanes']]

# ---------- Audio helpers (OGG-only) ----------
def try_load_sound(path):
    if os.path.isfile(path):
        try:
            return pygame.mixer.Sound(path)
        except Exception:
            return None
    return None

# ---------- Game ----------
class Game:
    def __init__(self):
        pygame.init()
        try:
            pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=4096)
        except Exception:
            pass

        self.screen = pygame.display.set_mode((WIN_W, WIN_H))
        pygame.display.set_caption("Apex Runner")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("consolas", 18)
        self.small_font = pygame.font.SysFont("consolas", 13)
        self.big = pygame.font.SysFont("consolas", 34, bold=True)

        # camera defaults
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

        # audio - OGG files only
        self.audio = {}
        assets_dir = "assets"
        if not os.path.isdir(assets_dir):
            os.makedirs(assets_dir, exist_ok=True)
        music_path = os.path.join(assets_dir, "music.ogg")
        if os.path.isfile(music_path):
            try:
                pygame.mixer.music.load(music_path)
                self.audio['music_loaded'] = True
            except Exception:
                self.audio['music_loaded'] = False
        else:
            self.audio['music_loaded'] = False

        # core sfx (OGG)
        self.audio['jump'] = try_load_sound(os.path.join(assets_dir, "sfx_jump.ogg"))
        self.audio['mantle'] = try_load_sound(os.path.join(assets_dir, "sfx_mantle.ogg"))
        self.audio['goal'] = try_load_sound(os.path.join(assets_dir, "sfx_goal.ogg"))
        self.audio['pickup'] = try_load_sound(os.path.join(assets_dir, "sfx_pickup.ogg"))
        self.audio['whoosh'] = try_load_sound(os.path.join(assets_dir, "sfx_whoosh.ogg"))
        self.audio['level_end'] = try_load_sound(os.path.join(assets_dir, "sfx_level_end.ogg"))
        self.audio['car_loop'] = try_load_sound(os.path.join(assets_dir, "sfx_car_loop.ogg"))
        # menu move/confirm (same SFX used for menu and level select)
        self.audio['menu_move'] = try_load_sound(os.path.join(assets_dir, "sfx_menu_move.ogg"))
        self.audio['menu_confirm'] = try_load_sound(os.path.join(assets_dir, "sfx_menu_confirm.ogg"))

        # cutscene / camera freeze state
        self.cutscene_active = False
        self.cutscene_t = 0.0
        self.cutscene_phase = 0
        self.vehicle_pos = None
        self.vehicle_dir = None
        self.fade_alpha = 0.0
        self.cutscene_cam_orig = None
        self.cutscene_cam_target_orient = None
        self.cutscene_bg_scale = 1.0
        self.cutscene_city_target = None
        self.cutscene_initial_dist = None
        self.cutscene_car_channel = None
        self.cutscene_stars = self._generate_stars(140)

        self.reset_world(0)

    def _generate_stars(self, n):
        rng = random.Random(999)
        stars = []
        for _ in range(n):
            x = rng.uniform(0, WIN_W)
            y = rng.uniform(0, WIN_H*0.6)
            size = rng.choice([1,1,1,2])
            tw = rng.uniform(0.8, 1.2)
            stars.append((x,y,size,tw))
        return stars

    def play_music(self):
        try:
            if self.audio.get('music_loaded', False):
                pygame.mixer.music.play(-1)
        except Exception:
            pass

    def stop_music(self):
        try:
            pygame.mixer.music.stop()
        except Exception:
            pass

    def play_sfx(self, name, loops=0):
        s = self.audio.get(name, None)
        if s:
            try:
                ch = s.play(loops=loops)
                return ch
            except Exception:
                pass
        return None

    def level_seed(self, idx):
        return self.seed_base + idx * 7919

    def reset_world(self, level_idx=0):
        # reset camera defaults (so cutscene pan doesn't leak)
        self.cam_yaw = math.pi
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
            h_phys = max(4.0, rng.gauss(midh, (cfg['max_h'] - cfg['min_h']) * 0.12))
            h_phys = clamp(h_phys, cfg['min_h'], cfg['max_h'])

            if prev:
                max_visual_up = max_up * 0.95
                new_visual = h_phys * VIS_MULT
                prev_visual = prev.h_visual
                if new_visual - prev_visual > max_visual_up:
                    allowed_phys_delta = max_visual_up / VIS_MULT
                    h_phys = prev.h + allowed_phys_delta * rng.uniform(0.55, 0.95)
                    h_phys = clamp(h_phys, cfg['min_h'], cfg['max_h'])
                max_visual_down = max_visual_up * 3.0
                if prev_visual - new_visual > max_visual_down:
                    new_visual = prev_visual - max_visual_down * rng.uniform(0.6, 1.0)
                    h_phys = new_visual / VIS_MULT
                    h_phys = clamp(h_phys, cfg['min_h'], cfg['max_h'])

            gap = rng.uniform(cfg['gap_min'], cfg['gap_max'])
            x = lane + rng.uniform(-1.6, 1.6)
            b = Building(x, z, w, BUILDING_DEPTH, h_phys)

            feasible = False
            if prev is None:
                feasible = True
            else:
                attempts_inner = 0
                local_gap = gap
                while attempts_inner < 8:
                    prev_cz = prev.z + prev.d * 0.5
                    cand_cz = b.z + b.d * 0.5
                    dx = b.x - prev.x
                    dz = cand_cz - prev_cz
                    dist = math.hypot(dx, dz)
                    if dist <= horiz_reach * 0.99:
                        feasible = True
                        gap = local_gap
                        break
                    if local_gap > cfg['gap_min'] * 0.6:
                        local_gap = max(cfg['gap_min'], local_gap * 0.6)
                        b.z = z
                    else:
                        if abs(b.x - prev.x) > 0.2:
                            b.x = lerp(b.x, prev.x, 0.45)
                        else:
                            b.x = prev.x
                    attempts_inner += 1
                prev_cz = prev.z + prev.d * 0.5
                cand_cz = b.z + b.d * 0.5
                dx = b.x - prev.x
                dz = cand_cz - prev_cz
                dist = math.hypot(dx, dz)
                feasible = dist <= horiz_reach * 1.0001

            if not feasible:
                continue

            self.buildings.append(b)
            prev = b
            z += BUILDING_DEPTH + gap
            i += 1

        while len(self.buildings) < cfg['num_buildings']:
            x = rng.choice(cfg['lanes'])
            w = rng.uniform(cfg['min_w'], cfg['max_w'])
            h_phys = rng.uniform(cfg['min_h'], cfg['max_h'])
            b = Building(x, z, w, BUILDING_DEPTH, h_phys)
            self.buildings.append(b)
            z += BUILDING_DEPTH + cfg['gap_min']

        self.buildings.sort(key=lambda bb: bb.z)

        # reachability passes
        horiz_reach_target = max_jump_horizontal(SPRINT_SPEED, JUMP_V, GRAVITY) * 0.98
        max_visual_up = max_up * 0.98
        max_visual_down = max_visual_up * 3.0
        for _pass in range(4):
            for idx in range(1, len(self.buildings)):
                prev = self.buildings[idx-1]
                b = self.buildings[idx]
                prev_cz = prev.z + prev.d * 0.5
                cand_cz = b.z + b.d * 0.5
                dx = b.x - prev.x
                dz = cand_cz - prev_cz
                dist = math.hypot(dx, dz)
                if dist > horiz_reach_target:
                    dx_abs = abs(dx)
                    allowed_sq = max(horiz_reach_target*horiz_reach_target - dx_abs*dx_abs, 0.0)
                    desired_dz = math.sqrt(allowed_sq)
                    new_cz = prev_cz + desired_dz * (1.0 if dz >= 0 else -1.0)
                    b.z = new_cz - b.d * 0.5
                    dist = math.hypot(b.x - prev.x, (b.z + b.d*0.5) - prev_cz)
                if dist > horiz_reach_target and abs(dx) > 0.2:
                    b.x = lerp(b.x, prev.x, 0.45)
                new_visual = b.h * VIS_MULT
                prev_visual = prev.h * VIS_MULT
                if new_visual - prev_visual > max_visual_up:
                    allowed_phys_delta = max_visual_up / VIS_MULT
                    b.h = prev.h + allowed_phys_delta * 0.9
                    b.h_visual = b.h * VIS_MULT
                if prev_visual - new_visual > max_visual_down:
                    new_visual = prev_visual - max_visual_down * 0.9
                    b.h = clamp(new_visual / VIS_MULT, cfg['min_h'], cfg['max_h'])
                    b.h_visual = b.h * VIS_MULT

        # spawn on first building roof
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
        self.mantle_orig_horiz = None

        self.fell_off = False
        self.left_by_jump = False
        self.prev_on_ground = True

        self.time_start = time.time()
        self.particles = []

        self.powerups = []

        self.bg_offset = 0.0
        self.prev_player_z = self.player_z

        self.level_completed = False
        self.victory_timer = 0.0
        self.respawn_cooldown = 0.0
        self.completion_time = None

        self.level_message_timer = 2.0

        # reset cutscene-related fields so pan/scale don't persist
        self.cutscene_active = False
        self.cutscene_t = 0.0
        self.cutscene_phase = 0
        self.vehicle_pos = None
        self.vehicle_dir = None
        self.fade_alpha = 0.0
        self.cutscene_cam_orig = None
        self.cutscene_cam_target_orient = None
        self.cutscene_bg_scale = 1.0
        self.cutscene_city_target = None
        self.cutscene_initial_dist = None
        self.cutscene_car_channel = None

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
        self.mantle_orig_horiz = (self.player_x, self.player_z)
        start_x = clamp(self.player_x, target_building.x - target_building.w, target_building.x + target_building.w)
        start_z = self.player_z
        end_z = target_building.z + target_building.d * 0.5
        end_y = target_building.h_visual + 0.02
        end_x = clamp(target_building.x, target_building.x - target_building.w/2 + 0.9, target_building.x + target_building.w/2 - 0.9)
        self.mantle_start_pos = Vec3(start_x, self.player_y, start_z)
        self.mantle_end_pos = Vec3(end_x, end_y, end_z)
        self.player_vy = 0.0
        self.player_on_ground = False

    def cancel_mantle(self):
        self.mantling = False
        self.mantle_target = None
        self.mantle_progress = 0.0
        self.mantle_start_pos = None
        self.mantle_end_pos = None
        self.mantle_orig_horiz = None

    def attempt_mantle_start(self, inputs):
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
            if inputs.get('mantle', False):
                self.begin_mantle(b)
            return b
        return None

    def start_end_cutscene(self):
        if self.cutscene_active: return
        self.cutscene_active = True
        self.cutscene_t = 0.0
        self.cutscene_phase = 0

        final_b = self.buildings[-1]
        # city target far ahead of final building
        city_target = Vec3(final_b.x, final_b.h_visual + 8.0, final_b.z + final_b.d * 6.0)
        self.cutscene_city_target = city_target

        # compute direction from player to city (if degenerate, default forward)
        player_pos = Vec3(self.player_x, self.player_y, self.player_z)
        dir_to_city = normalize(Vec3(city_target.x - player_pos.x, city_target.y - player_pos.y, city_target.z - player_pos.z))

        # place camera **behind the player** (parkour area) looking toward the city ahead;
        # that way buildings you just jumped on (behind the player) will be out of view.
        cam_offset_back = 6.0
        cam_height = 4.0
        cam_forward_far = 60.0
        self.cam_pos = Vec3(player_pos.x - dir_to_city.x * cam_offset_back,
                             player_pos.y + cam_height,
                             player_pos.z - dir_to_city.z * cam_offset_back)
        self.cam_target = Vec3(player_pos.x + dir_to_city.x * cam_forward_far,
                               player_pos.y + 2.0,
                               player_pos.z + dir_to_city.z * cam_forward_far)
        self.forward, self.right, self.up = build_camera_basis(self.cam_pos, self.cam_target)
        # store yaw/pitch so later normal gameplay resets work correctly
        # compute yaw from forward vector (rough estimate)
        yaw = math.atan2(self.cam_pos.x - self.cam_target.x, self.cam_pos.z - self.cam_target.z)
        self.cutscene_cam_orig = (self.cam_yaw, self.cam_pitch)
        self.cam_yaw = yaw
        self.cam_pitch = radians(6.0)
        self.cutscene_cam_target_orient = (self.cam_yaw, self.cam_pitch)

        # vehicle starts just in front of player and moves toward the city target (away from camera)
        self.vehicle_pos = Vec3(player_pos.x + dir_to_city.x * 1.6,
                                player_pos.y + 2.0,
                                player_pos.z + dir_to_city.z * 1.6)
        self.vehicle_dir = dir_to_city
        self.cutscene_initial_dist = length(Vec3(city_target.x - self.vehicle_pos.x,
                                                 city_target.y - self.vehicle_pos.y,
                                                 city_target.z - self.vehicle_pos.z))
        self.cutscene_bg_scale = 1.0

        # put player in vehicle visually
        self.player_x = self.vehicle_pos.x
        self.player_y = self.vehicle_pos.y - 1.4
        self.player_z = self.vehicle_pos.z

        # play car loop if available (looping)
        if self.audio.get('car_loop'):
            try:
                self.cutscene_car_channel = self.audio['car_loop'].play(loops=-1)
            except Exception:
                self.cutscene_car_channel = None
        self.play_sfx('pickup')
        self.play_sfx('whoosh')
        self.fade_alpha = 0.0

    def _save_best_time_for_level(self, lvl, comp_time):
        prev_best = self.best_times.get(lvl, None)
        if prev_best is None or comp_time < prev_best - 1e-6:
            self.best_times[lvl] = round(comp_time, 3)

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
        # handle cutscene movement (camera is fixed at parkour area; vehicle moves away from camera -> gets smaller)
        if self.cutscene_active:
            self.cutscene_t += dt
            lead_time = 0.8
            approach_time = 4.0
            accel_time = 3.6
            fade_time = 2.6

            # small lead movement
            if self.cutscene_t <= lead_time:
                speed = 8.0 * dt
                self.vehicle_pos.x += self.vehicle_dir.x * speed
                self.vehicle_pos.y += self.vehicle_dir.y * speed
                self.vehicle_pos.z += self.vehicle_dir.z * speed
                self.player_x = self.vehicle_pos.x
                self.player_y = self.vehicle_pos.y - 1.4
                self.player_z = self.vehicle_pos.z
                self._update_cutscene_bg_scale()
                return

            t_since_lead = self.cutscene_t - lead_time
            if t_since_lead < approach_time:
                t = min(1.0, t_since_lead / approach_time)
                speed = 10.0 + 48.0 * t
                self.vehicle_pos.x += self.vehicle_dir.x * speed * dt
                self.vehicle_pos.y += self.vehicle_dir.y * speed * dt
                self.vehicle_pos.z += self.vehicle_dir.z * speed * dt
                self.player_x = self.vehicle_pos.x
                self.player_y = self.vehicle_pos.y - 1.4
                self.player_z = self.vehicle_pos.z
                self._update_cutscene_bg_scale()
                return

            t2 = t_since_lead - approach_time
            if t2 < accel_time:
                t = min(1.0, t2 / accel_time)
                acc_speed = 60.0 + 200.0 * t
                self.vehicle_pos.x += self.vehicle_dir.x * acc_speed * dt
                self.vehicle_pos.y += self.vehicle_dir.y * acc_speed * dt
                self.vehicle_pos.z += self.vehicle_dir.z * acc_speed * dt
                self.player_x = self.vehicle_pos.x
                self.player_y = self.vehicle_pos.y - 1.4
                self.player_z = self.vehicle_pos.z
                self._update_cutscene_bg_scale()
                return

            # fade to black phase
            t3 = t2 - accel_time
            self.fade_alpha = clamp(t3 / fade_time, 0.0, 1.0)
            self._update_cutscene_bg_scale()
            if t3 >= fade_time:
                self.cutscene_active = False
                try:
                    if self.cutscene_car_channel:
                        self.cutscene_car_channel.stop()
                except Exception:
                    pass
                try:
                    if self.audio.get('car_loop', None):
                        self.audio['car_loop'].stop()
                except Exception:
                    pass
                # go to YOU WIN screen
                self.state = 'gameover'
                self.selected_level = 0
            return

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
                        orig_x, orig_z = (0.0, 0.0)
                        if self.mantle_orig_horiz:
                            orig_x, orig_z = self.mantle_orig_horiz
                        b = self.mantle_target
                        final_x_candidate = clamp(orig_x, b.x - b.w/2 + 0.9, b.x + b.w/2 - 0.9)
                        dx = abs(final_x_candidate - orig_x)
                        final_z_candidate = b.z + b.d * 0.5
                        dz = abs(final_z_candidate - orig_z)
                        # choose to place the player on the ledge but keep closeness to original horiz position
                        if dx <= dz:
                            final_x = final_x_candidate
                            final_z = final_z_candidate
                        else:
                            final_x = final_x_candidate
                            final_z = final_z_candidate
                            if orig_z < b.z:
                                final_z = b.z + 0.04
                            elif orig_z > b.z + b.d:
                                final_z = b.z + b.d - 0.04
                        self.player_x = final_x
                        self.player_z = final_z
                        self.player_y = self.mantle_end_pos.y
                        self.player_vy = 0.0
                        self.player_on_ground = True
                        self.spawn_particles(10)
                        self.fell_off = False
                        self.left_by_jump = False
                        self.play_sfx('mantle')
                        self.cancel_mantle()
                p = clamp(self.mantle_progress, 0.0, 1.0)
                if self.mantle_start_pos is not None and self.mantle_end_pos is not None:
                    sx, sy, sz = self.mantle_start_pos.x, self.mantle_start_pos.y, self.mantle_start_pos.z
                    ex, ey, ez = self.mantle_end_pos.x, self.mantle_end_pos.y, self.mantle_end_pos.z
                    self.player_x = lerp(sx, ex, min(p, 0.18))
                    self.player_y = lerp(sy, ey, p)
                    self.player_z = lerp(sz, ez, min(p, 0.06))
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
            self.play_sfx('jump')

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

        # update camera normally while playing
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

        # completion - save best immediately to avoid being lost to cutscene
        last = self.buildings[-1]
        if self.player_z > last.z + last.d*0.6 and not self.level_completed:
            self.level_completed = True
            self.victory_timer = 1.0
            self.completion_time = time.time() - self.time_start
            self._save_best_time_for_level(self.level_index, self.completion_time)
            self.play_sfx('level_end')
            self.play_sfx('goal')
            return

    def _update_cutscene_bg_scale(self):
        if self.cutscene_city_target is None or self.vehicle_pos is None:
            return
        if self.cutscene_initial_dist is None or self.cutscene_initial_dist <= 0:
            self.cutscene_bg_scale = 1.0
            return
        cur_dist = length(Vec3(self.cutscene_city_target.x - self.vehicle_pos.x,
                               self.cutscene_city_target.y - self.vehicle_pos.y,
                               self.cutscene_city_target.z - self.vehicle_pos.z))
        frac = clamp(1.0 - (cur_dist / max(1e-6, self.cutscene_initial_dist)), 0.0, 1.0)
        self.cutscene_bg_scale = 1.0 + (1.2 * (frac * frac * (3 - 2*frac)))
        self.cutscene_bg_scale = clamp(self.cutscene_bg_scale, 1.0, 2.5)

    def draw_skyline_background(self):
        s = self.screen
        layers = 3
        scale = 1.0
        if self.cutscene_active:
            scale = self.cutscene_bg_scale
        for layer in range(layers):
            count = int((28 - layer*6) * (0.9 + (scale-1.0)*0.06))
            y_base = WIN_H * (0.18 + layer * 0.06) - int((scale-1.0)*18 * layer)
            color_base = int(18 + layer*24)
            parallax_mul = 0.6 - layer*0.18
            spacing = WIN_W / max(1, count)
            base_offset = (self.bg_offset * parallax_mul) % (spacing * 2)
            for i in range(max(1, count)):
                x = (i * spacing - base_offset) % (WIN_W + spacing) - spacing/2
                h = int(((30 + (i%7)*10 + layer*8) + math.sin(i*0.6 + layer*0.12) * 6) * scale)
                rect = pygame.Rect(int(x), int(y_base - h), int(spacing * 0.9), int(h))
                c = (clamp(color_base+random.randint(-6,6),0,255), clamp(color_base+random.randint(-6,6),0,255), clamp(color_base+30+layer*6,0,255))
                pygame.draw.rect(s, c, rect)

        # billboard scaled by cutscene_bg_scale
        bx = int(WIN_W*0.625); by = int(WIN_H*0.13)
        bw = int(220 * scale); bh = int(56 * scale)
        outline = pygame.Surface((bw+20, bh+20), pygame.SRCALPHA)
        for i in range(6):
            a = int(40 - i*6)
            pygame.draw.rect(outline, (30,140,200,a), (i, i, bw+20-2*i, bh+20-2*i), border_radius=10, width=2)
        s.blit(outline, (bx-10, by-10))
        panel = pygame.Surface((bw, bh), pygame.SRCALPHA)
        panel.fill((8,10,14,220))
        for row in range(3):
            yoff = int(6*scale + row*(14*scale))
            pygame.draw.line(panel, (10,14,20,70), (8, yoff), (bw-8, yoff))
        pygame.draw.rect(panel, (18,40,60), (4,4,bw-8,bh-8), border_radius=8, width=2)
        s.blit(panel, (bx, by))
        t = time.time() - getattr(self, 'time_start', 0.0)
        title = "APEX CITY"
        glow = self.big.render(title, True, (80,200,240))
        glow.set_alpha(40 + int((math.sin(t*2.0) + 1.0) * 30))
        s.blit(glow, (bx + 12, by + 6))
        txt = self.big.render(title, True, (140,230,255))
        s.blit(txt, (bx + 10, by + 4))
        scan_w = int(160 * scale)
        scan_x = int(((t * 160) + (self.bg_offset*0.12)) % (bw + scan_w) - scan_w/2)
        scan_rect = pygame.Rect(bx + scan_x, by + int(bh*0.72), max(3,int(scan_w*0.06)), max(1,int(3*scale)))
        pygame.draw.rect(s, (80,200,255), scan_rect)

    def draw(self):
        s = self.screen
        s.fill((8,8,12))

        # sky gradient
        for i in range(120):
            a = i / 119.0
            color = (int(8 + a*12), int(12 + a*28), int(30 + a*60))
            pygame.draw.rect(s, color, (0, int(i * WIN_H / 240), WIN_W, int(WIN_H / 240)+1))

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
                depth_factor = clamp(1.0 - (avg_cz - 10.0)/120.0, 0.55, 1.0)
                if fi == 3:
                    col = tuple(int(c * depth_factor) for c in top_color)
                elif fi in (2,):
                    col = (int(12*depth_factor), int(12*depth_factor), int(14*depth_factor))
                elif fi in (1,):
                    col = tuple(int(c * depth_factor) for c in side_color)
                else:
                    col = tuple(int(c * depth_factor) for c in face_color)
                face_list.append({'cz': avg_cz, 'poly': poly2, 'col': col, 'b_idx': idx, 'proj': proj,
                                  'face_idx': fi, 'poly_world': poly_world, 'building': b})

        # sort far->near
        face_list.sort(key=lambda it: it['cz'], reverse=True)

        t = time.time() - getattr(self, 'time_start', 0.0)

        # draw faces and embedded horizontal rectangular window rows (identical width)
        for f in face_list:
            poly = f['poly']
            if not poly or not safe_poly(poly):
                continue
            try:
                pygame.draw.polygon(s, f['col'], poly)
                pygame.draw.polygon(s, (10,10,12), poly, 1)
                fi = f['face_idx']
                # only draw windows on left/right faces (sides) so they are horizontal rows
                if fi in (4,5):
                    pw = f['poly_world']
                    sorted_by_y = sorted(pw, key=lambda v: v.y, reverse=True)
                    top_pts = sorted_by_y[:2]
                    bot_pts = sorted_by_y[2:]
                    pair = sorted(zip(top_pts, bot_pts), key=lambda pr: dot(pr[0], self.right))
                    if len(pair) == 2:
                        (tL, bL), (tR, bR) = (pair[0][0], pair[0][1]), (pair[1][0], pair[1][1])
                        # compute a consistent left-right parameterization v0..v1 where windows use identical width
                        # We'll create N rows (based on face height) with identical horizontal extent (same v span)
                        mid_top = Vec3((tL.x + tR.x)/2.0, (tL.y + tR.y)/2.0, (tL.z + tR.z)/2.0)
                        mid_bot = Vec3((bL.x + bR.x)/2.0, (bL.y + bR.y)/2.0, (bL.z + bR.z)/2.0)
                        pt_top = project_point(mid_top, self.cam_pos, self.forward, self.right, self.up, fov)
                        pt_bot = project_point(mid_bot, self.cam_pos, self.forward, self.right, self.up, fov)
                        screen_h = abs(pt_bot[1] - pt_top[1]) if isfinite(pt_top[1]) and isfinite(pt_bot[1]) else 80
                        # decide rows: 1-3 rows depending on visual height
                        num_rows = 1 if screen_h < 90 else 2 if screen_h < 200 else 3
                        # fixed horizontal window fraction v_start..v_end to make identical width across rows
                        v_pad = 0.12
                        v0 = v_pad
                        v1 = 1.0 - v_pad
                        thickness = 0.12
                        idx_counter = 0
                        for r in range(num_rows):
                            # vertical u region evenly spaced
                            u_center = (r + 1) / (num_rows + 1)
                            u0 = clamp(u_center - thickness*0.5, 0.0, 1.0)
                            u1 = clamp(u_center + thickness*0.5, 0.0, 1.0)
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
                                brightness = int(clamp(140 + 40 * math.sin(t * 2.0 + idx_counter * 0.6), 110, 220))
                                cx = sum(pt[0] for pt in quad)/4.0
                                cy = sum(pt[1] for pt in quad)/4.0
                                shrink_inner = 0.94
                                inner_shrunk = [((pt[0]-cx)*shrink_inner + cx, (pt[1]-cy)*shrink_inner + cy) for pt in quad]
                                # base glass panel
                                pygame.draw.polygon(s, (12,14,16), inner_shrunk)
                                # emissive-like glow (subtle, not heavy)
                                pygame.draw.polygon(s, (brightness-24, brightness+8, min(255, brightness+28)), inner_shrunk)
                                pygame.draw.polygon(s, (8,8,10), inner_shrunk, 1)
                            idx_counter += 1
            except Exception:
                continue

        # draw player silhouette (player may ride in vehicle during cutscene; camera is fixed)
        ppos = Vec3(self.player_x, self.player_y + PLAYER_HEIGHT*0.25, self.player_z)
        psx, psy, psc, pcz = project_point(ppos, self.cam_pos, self.forward, self.right, self.up, fov)

        if isfinite(psx) and isfinite(psy) and isfinite(pcz) and pcz > 0:
            scale = clamp((CAM_DIST_DEFAULT / max(1e-3, self.cam_dist)), 0.35, 3.6)
            pw = max(12, int(PLAYER_BASE_W * scale))
            ph = max(18, int(PLAYER_BASE_H * scale))
            shadow_w = pw * 1.6; shadow_h = max(4, int(pw * 0.32))
            shadow = pygame.Surface((int(shadow_w), shadow_h), pygame.SRCALPHA)
            pygame.draw.ellipse(shadow, (0,0,0,160), shadow.get_rect())
            s.blit(shadow, (int(psx - shadow.get_width()//2), int(psy - ph*0.18 + shadow.get_height()//2)))
            body_rect = pygame.Rect(int(psx - pw//2), int(psy - ph), pw, ph)
            pygame.draw.rect(s, (28,28,30), body_rect, border_radius=max(6, pw//6))
            chest = pygame.Rect(int(psx - pw*0.28), int(psy - int(ph * 0.78)), int(pw*0.56), int(ph*0.44))
            pygame.draw.rect(s, (46,58,68), chest, border_radius=4)
            sp_w = int(pw*0.28); sp_h = int(ph*0.18)
            pygame.draw.rect(s, (36,36,40), (int(psx - pw//2 - 2), int(psy - ph + 4), sp_w, sp_h), border_radius=4)
            pygame.draw.rect(s, (36,36,40), (int(psx + pw//2 - sp_w + 2), int(psy - ph + 4), sp_w, sp_h), border_radius=4)
            head_w = int(pw*0.64); head_h = int(ph*0.28)
            pygame.draw.ellipse(s, (38,38,40), (int(psx - head_w//2), int(psy - ph - head_h//2), head_w, head_h))
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

        # LEVEL COMPLETE overlay (restored) + press N prompt (now simple "Press N to continue")
        if self.level_completed:
            overlay = pygame.Surface((WIN_W, WIN_H), pygame.SRCALPHA)
            overlay.fill((0,0,0,160))
            s.blit(overlay,(0,0))
            txt = self.big.render("LEVEL COMPLETE", True, (200,230,255))
            s.blit(txt, (WIN_W//2 - txt.get_width()//2, WIN_H//2 - 64))
            comp = self.completion_time if self.completion_time is not None else (time.time() - self.time_start)
            best = self.best_times.get(self.level_index, None)
            info = f"Time: {comp:.3f}s"
            txt2 = self.font.render(info, True, (220,230,255)); s.blit(txt2, (WIN_W//2 - txt2.get_width()//2, WIN_H//2 + 4))
            if best is not None:
                best_txt = f"Best: {best:.3f}s"
                txt3 = self.font.render(best_txt, True, (200,200,200)); s.blit(txt3, (WIN_W//2 - txt3.get_width()//2, WIN_H//2 + 32))
            # Press N prompt (simplified)
            hint_surf = self.font.render("Press N to continue", True, (240,240,200))
            s.blit(hint_surf, (WIN_W//2 - hint_surf.get_width()//2, WIN_H//2 + 64))
        
        # cutscene overlays (vehicle + stars + lighter vignette + fade)
        if self.cutscene_active:
            if self.vehicle_pos is not None:
                v = self.vehicle_pos
                vpx, vpy, vps, vcz = project_point(Vec3(v.x, v.y, v.z), self.cam_pos, self.forward, self.right, self.up, fov)
                if isfinite(vpx) and isfinite(vpy) and isfinite(vps) and vps > 0:
                    # scale the drawable according to projection so it shrinks as it moves away
                    screen_scale = clamp(1.0 / max(1e-4, vps*0.06), 0.25, 2.2)
                    wv = int(160 * screen_scale)
                    hv = int(46 * screen_scale)
                    cx = int(vpx); cy = int(vpy)
                    body_rect = pygame.Rect(cx - wv//2, cy - hv//2, wv, hv)
                    # sleek dark car silhouette
                    pygame.draw.ellipse(s, (12,16,20), body_rect)
                    gloss = pygame.Surface((wv, int(hv*0.5)), pygame.SRCALPHA)
                    pygame.draw.ellipse(gloss, (36,46,56,40), gloss.get_rect())
                    s.blit(gloss, (body_rect.x, body_rect.y + int(hv*0.06)))
                    # cockpit window
                    cock = pygame.Rect(body_rect.x + int(wv*0.18), body_rect.y + int(hv*0.2), int(wv*0.64), int(hv*0.38))
                    pygame.draw.rect(s, (26,34,40), cock, border_radius=int(hv*0.2))
                    pygame.draw.rect(s, (70,90,100), cock, 2, border_radius=int(hv*0.2))
                    # wings
                    wing_w = int(wv*0.26); wing_h = int(hv*0.34)
                    left_wing = [(cx - wv//2 + 6, cy), (cx - wv//2 - wing_w, cy - wing_h), (cx - wv//2 - wing_w, cy + wing_h)]
                    right_wing = [(cx + wv//2 - 6, cy), (cx + wv//2 + wing_w, cy - wing_h), (cx + wv//2 + wing_w, cy + wing_h)]
                    pygame.draw.polygon(s, (14,18,22), left_wing)
                    pygame.draw.polygon(s, (14,18,22), right_wing)
                    pygame.draw.polygon(s, (36,44,52), left_wing, 2)
                    pygame.draw.polygon(s, (36,44,52), right_wing, 2)
                    # subtle engine glow (back)
                    thr_w = int(wv*0.22); thr_h = int(hv*0.28)
                    thr_surf = pygame.Surface((thr_w, thr_h), pygame.SRCALPHA)
                    pygame.draw.ellipse(thr_surf, (70,120,200,60), (0,0,thr_w,thr_h))
                    s.blit(thr_surf, (body_rect.right - int(thr_w*0.6), body_rect.y + hv//2 - thr_h//2))
            # stars vignette (brighter than before)
            for (sx, sy, sz, tw) in self.cutscene_stars:
                br = 200 + 40 * math.sin(time.time()*tw*1.6 + sx*0.001)
                pygame.draw.circle(s, (int(br), int(br), int(br)), (int(sx), int(sy)), sz)
            # lighter vignette: still soft edges but not overwhelming
            vign = pygame.Surface((WIN_W, WIN_H), pygame.SRCALPHA)
            # compute dynamic vignette alpha that reduces with city approach
            approach_frac = clamp((self.cutscene_bg_scale - 1.0) / 1.6, 0.0, 1.0)
            vign_alpha = int(80 * (1.0 - approach_frac))  # less dark as approach progresses
            for i in range(6):
                a = int(max(0, vign_alpha - i*8))
                pygame.draw.rect(vign, (0,0,0,a), (i*-8, i*-8, WIN_W + i*16, WIN_H + i*16), border_radius=WIN_W//6)
            s.blit(vign, (0,0))
            # fade to black overlay uses fade_alpha
            fade = pygame.Surface((WIN_W, WIN_H))
            fade.fill((0,0,0))
            fade.set_alpha(int(clamp(self.fade_alpha, 0.0, 1.0) * 255))
            s.blit(fade, (0,0))

        # victory/gameover themed screens
        if self.state == 'victory':
            overlay = pygame.Surface((WIN_W, WIN_H), pygame.SRCALPHA); overlay.fill((0,0,0,160)); s.blit(overlay,(0,0))
            txt = self.big.render("LEVEL COMPLETE", True, (200,230,255)); s.blit(txt, (WIN_W//2 - txt.get_width()//2, WIN_H//2 - 40))
            comp = self.completion_time if self.completion_time is not None else (time.time() - self.time_start)
            best = self.best_times.get(self.level_index, None)
            info = f"Time: {comp:.3f}s"
            txt2 = self.font.render(info, True, (220,230,255)); s.blit(txt2, (WIN_W//2 - txt2.get_width()//2, WIN_H//2 + 12))
            if best is not None:
                best_txt = f"Best: {best:.3f}s"
                txt3 = self.font.render(best_txt, True, (200,200,200)); s.blit(txt3, (WIN_W//2 - txt3.get_width()//2, WIN_H//2 + 36))

        if self.state == 'gameover':
            for y in range(WIN_H):
                a = y / (WIN_H-1)
                col = (int(2 + a*18), int(6 + a*38), int(14 + a*60))
                pygame.draw.line(s, col, (0,y), (WIN_W,y))
            for (sx, sy, sz, tw) in self.cutscene_stars:
                br = 120 + 80 * math.sin(time.time()*tw*0.7 + sx*0.0007)
                pygame.draw.circle(s, (int(br), int(br), int(br)), (int(sx), int(sy+80)), sz)
            title = "YOU WIN"
            glow = self.big.render(title, True, (70,200,140))
            glow.set_alpha(80)
            s.blit(glow, (WIN_W//2 - glow.get_width()//2, WIN_H//2 - 84))
            text = self.big.render(title, True, (160,255,200))
            s.blit(text, (WIN_W//2 - text.get_width()//2, WIN_H//2 - 88))
            sub = self.font.render("Evacuated to Apex City — mission accomplished.", True, (200,230,220))
            s.blit(sub, (WIN_W//2 - sub.get_width()//2, WIN_H//2 - 24))
            hint = self.font.render("Press Esc to return to the main menu.", True, (160,180,200))
            s.blit(hint, (WIN_W//2 - hint.get_width()//2, WIN_H//2 + 18))

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
        per_row = 5
        start_x = 60
        y_top = 120
        spacing_x = (WIN_W - 2 * start_x) / per_row
        for row in range(2):
            for i in range(per_row):
                idx = row * per_row + i
                if idx >= len(LEVELS): continue
                x = int(start_x + i * spacing_x); y = int(y_top + row * 140)
                w = 120; h = 96
                rect = pygame.Rect(x,y,w,h)
                color = (58,48,78) if idx != self.selected_level else (100,70,140)
                pygame.draw.rect(s, color, rect, border_radius=8)
                txt = self.font.render(f"Level {idx+1}", True, (230,230,255)); s.blit(txt, (x+8, y+8))
                bt = self.best_times.get(idx, None)
                if bt is not None:
                    bt_txt_surf = self.small_font.render(f"Best {bt:.3f}s", True, (120,230,140))
                else:
                    bt_txt_surf = self.small_font.render("Best ---", True, (140,140,160))
                s.blit(bt_txt_surf, (x+6, y + 60))

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

                # ESC while cutscene -> back to menu
                if self.cutscene_active:
                    if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                        self.cutscene_active = False
                        try:
                            if self.cutscene_car_channel:
                                self.cutscene_car_channel.stop()
                        except Exception:
                            pass
                        try:
                            if self.audio.get('car_loop', None):
                                self.audio['car_loop'].stop()
                        except Exception:
                            pass
                        self.state = 'menu'
                        self.selected_level = 0
                    # ignore other inputs while cutscene active
                    continue

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
                            self.play_music()
                        if ev.key == pygame.K_p:
                            self.state = 'paused' if self.state == 'play' else 'play'
                        if ev.key == pygame.K_ESCAPE:
                            self.state = 'menu'
                        if ev.key == pygame.K_n and self.level_completed and not self.cutscene_active:
                            # N pressed to continue
                            self.play_sfx('menu_confirm')
                            if self.level_index < len(LEVELS) - 1:
                                # go to next level
                                self.level_index += 1
                                self.reset_world(self.level_index)
                                self.play_music()
                            else:
                                # final level -> start cutscene
                                self.start_end_cutscene()
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
                        if ev.key == pygame.K_UP:
                            self.menu_index = max(0, self.menu_index - 1)
                            self.play_sfx('menu_move')
                        if ev.key == pygame.K_DOWN:
                            self.menu_index = min(2, self.menu_index + 1)
                            self.play_sfx('menu_move')
                        if ev.key == pygame.K_RETURN:
                            self.play_sfx('menu_confirm')
                            if self.menu_index == 0:
                                self.reset_world(self.selected_level); self.state = 'play'; self.play_music()
                            elif self.menu_index == 1:
                                self.state = 'level_select'
                            else:
                                running = False
                        if ev.key == pygame.K_ESCAPE:
                            running = False

                elif self.state == 'level_select':
                    if ev.type == pygame.KEYDOWN:
                        per_row = 5
                        if ev.key == pygame.K_LEFT:
                            self.selected_level = max(0, self.selected_level - 1)
                            self.play_sfx('menu_move')
                        if ev.key == pygame.K_RIGHT:
                            self.selected_level = min(len(LEVELS)-1, self.selected_level + 1)
                            self.play_sfx('menu_move')
                        if ev.key == pygame.K_UP:
                            self.selected_level = max(0, self.selected_level - per_row)
                            self.play_sfx('menu_move')
                        if ev.key == pygame.K_DOWN:
                            self.selected_level = min(len(LEVELS)-1, self.selected_level + per_row)
                            self.play_sfx('menu_move')
                        if ev.key == pygame.K_RETURN:
                            self.play_sfx('menu_confirm')
                            self.reset_world(self.selected_level); self.state = 'play'; self.play_music()
                        if ev.key == pygame.K_ESCAPE:
                            self.state = 'menu'

                elif self.state == 'paused':
                    if ev.type == pygame.KEYDOWN and ev.key == pygame.K_p:
                        self.state = 'play'

                elif self.state == 'victory':
                    if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                        self.state = 'menu'

                elif self.state == 'gameover':
                    if ev.type == pygame.KEYDOWN:
                        if ev.key == pygame.K_ESCAPE:
                            self.state = 'menu'
                            self.selected_level = 0
                        elif ev.key == pygame.K_RETURN:
                            # pressing start on the final YOU WIN screen should go to level 1
                            self.selected_level = 0
                            self.reset_world(0)
                            self.state = 'play'
                            self.play_music()

            # mouse rotation while LMB held
            if self.state == 'play' and self.lmb_held and not self.cutscene_active:
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
            elif self.state == 'gameover':
                self.draw()

            pygame.display.flip()

        try:
            pygame.mixer.quit()
        except Exception:
            pass
        pygame.quit()
        sys.exit()

if __name__ == "__main__":
    Game().run()
