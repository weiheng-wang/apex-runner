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
SPRINT_MAX_ENERGY = 3.5
SPRINT_DRAIN_RATE = 0.5
SPRINT_REGEN_RATE = 0.45

# Mantle
MANTLE_TIME = 0.7

# Building
BUILDING_DEPTH = 14.0
EPS = 1e-5
VIS_MULT = 5.0  # visual height multiplier (visual top used for collisions/render)

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

# helper: check building overlap in world-space AABB (x vs z)
def buildings_overlap(a: Building, b: Building, margin=0.08):
    ax0 = a.x - (a.w*0.5 + margin); ax1 = a.x + (a.w*0.5 + margin)
    az0 = a.z - margin; az1 = a.z + a.d + margin
    bx0 = b.x - (b.w*0.5 + margin); bx1 = b.x + (b.w*0.5 + margin)
    bz0 = b.z - margin; bz1 = b.z + b.d + margin
    overlap_x = not (ax1 <= bx0 or bx1 <= ax0)
    overlap_z = not (az1 <= bz0 or bz1 <= az0)
    return overlap_x and overlap_z

# ---------- LEVELS: programmatic ramp 1..10 with variation ----------
LEVELS = []
for i in range(NUM_LEVELS):
    d = i / max(1, NUM_LEVELS - 1)
    num_buildings = int(4 + d * 20)
    lanes_count = 1 + int(d * 5)
    spread = 4 + d * 48
    if lanes_count > 1:
        lanes = [(-spread/2.0) + j*(spread/(lanes_count-1)) for j in range(lanes_count)]
    else:
        lanes = [0.0]
    # allow later levels to include skinnier buildings for challenge
    min_w = max(1.6, 6.0 - d * 4.0)
    max_w = 7.0 + d * 10.0
    min_h = 4.0 + d * 8.0
    max_h = min_h + 6.0 + d * 28.0
    gap_min = 0.6 + d * 3.0
    gap_max = gap_min + 0.6 + d * 4.2
    LEVELS.append({'num_buildings': num_buildings, 'lanes': lanes,
                   'min_w': min_w, 'max_w': max_w, 'min_h': min_h, 'max_h': max_h,
                   'gap_min': gap_min, 'gap_max': gap_max})

# make last level extra challenging
if len(LEVELS) >= 10:
    L9 = LEVELS[-1]
    L9['min_w'] = max(1.4, L9['min_w'] - 1.0)
    L9['max_w'] = L9['max_w'] + 2.6
    L9['gap_min'] = L9['gap_min'] + 2.0
    L9['gap_max'] = L9['gap_max'] + 3.0
    L9['min_h'] = L9['min_h'] + 6.0
    L9['max_h'] = L9['max_h'] + 18.0
    # increase lane spread to force left/right movement
    L9['lanes'] = L9['lanes'] + [x + 3.4 for x in L9['lanes']]

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
                pygame.mixer.music.set_volume(0.3)
                self.audio['music_loaded'] = True
            except Exception:
                self.audio['music_loaded'] = False
        else:
            self.audio['music_loaded'] = False

        # core sfx (OGG)
        self.audio['jump'] = try_load_sound(os.path.join(assets_dir, "jump.ogg"))
        self.audio['mantle'] = try_load_sound(os.path.join(assets_dir, "mantle.ogg"))
        self.audio['pickup'] = try_load_sound(os.path.join(assets_dir, "pickup.ogg"))
        self.audio['level_end'] = try_load_sound(os.path.join(assets_dir, "level_end.ogg"))
        self.audio['car_loop'] = try_load_sound(os.path.join(assets_dir, "car_loop.ogg"))
        # menu move/confirm (same SFX used for menu and level select)
        self.audio['menu_move'] = try_load_sound(os.path.join(assets_dir, "menu_move.ogg"))
        self.audio['menu_confirm'] = try_load_sound(os.path.join(assets_dir, "menu_confirm.ogg"))
        # optional death sound and cutscene music
        self.audio['death'] = try_load_sound(os.path.join(assets_dir, "death.ogg"))
        cut_path = os.path.join(assets_dir, "cutscene_music.ogg")
        if os.path.isfile(cut_path):
            self.audio['cutscene_music_path'] = cut_path
            self.audio['cutscene_music_loaded'] = True
        else:
            self.audio['cutscene_music_loaded'] = False

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
        self.cutscene_player_start = None
        self.cutscene_player_hidden = False
        self.cutscene_door_progress = 0.0

        # music state tracking (so we only restart when explicitly requested)
        self._music_started = False

        # camera pan state after level complete (smooth shift)
        self.cam_pan_active = False
        self.cam_pan_t = 0.0
        self.cam_pan_dur = 1.0
        self.cam_pan_start_pos = None
        self.cam_pan_start_target = None
        self.cam_pan_end_pos = None
        self.cam_pan_end_target = None

        # new flags:
        # when True, after the camera pan completes we'll start the cutscene
        self._start_cutscene_after_pan = False
        # lock controls after completing final level (until exit/reset)
        self.controls_locked = False

        # skyline per-level scale (level 1 far away, later levels closer)
        self.skyline_scale = 1.0

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

    def play_music(self, force=False):
        try:
            if not self.audio.get('music_loaded', False):
                return
            if force:
                try:
                    pygame.mixer.music.stop()
                except Exception:
                    pass
                try:
                    pygame.mixer.music.play(-1)
                    self._music_started = True
                except Exception:
                    pass
            else:
                # only start if not already playing
                try:
                    if not pygame.mixer.music.get_busy():
                        pygame.mixer.music.play(-1)
                        self._music_started = True
                except Exception:
                    pass
        except Exception:
            pass

    def stop_music(self):
        try:
            pygame.mixer.music.stop()
            self._music_started = False
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

    def goto_menu(self):
        # stop any music and return to main menu
        try:
            if self.cutscene_car_channel:
                try:
                    self.cutscene_car_channel.stop()
                except Exception:
                    pass
            self.stop_music()
        except Exception:
            pass
        self.state = 'menu'
        self.selected_level = 0
        # clear any locks when returning to menu
        self.controls_locked = False
        self._start_cutscene_after_pan = False
        self.cutscene_player_hidden = False

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
        while i < cfg['num_buildings'] and tries < 40000:
            tries += 1
            lane = rng.choice(cfg['lanes'])
            w = rng.uniform(cfg['min_w'], cfg['max_w'])
            midh = (cfg['min_h'] + cfg['max_h']) / 2.0
            h_phys = max(4.0, rng.gauss(midh, (cfg['max_h'] - cfg['min_h']) * 0.14))
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
            x = lane + rng.uniform(-2.2, 2.2)  # allow more lateral variety
            b = Building(x, z, w, BUILDING_DEPTH, h_phys)

            feasible = False
            if prev is None:
                feasible = True
            else:
                attempts_inner = 0
                local_gap = gap
                while attempts_inner < 12:
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

            # try to resolve overlaps by nudging horizontally before giving up
            clash = True
            shift_attempt = 0
            while clash and shift_attempt < 8:
                clash = False
                for bb in self.buildings:
                    if buildings_overlap(b, bb, margin=0.08):
                        clash = True
                        # push b away along x depending on relative positions
                        if b.x <= bb.x:
                            b.x = bb.x - (bb.w*0.5 + b.w*0.5) - 0.15
                        else:
                            b.x = bb.x + (bb.w*0.5 + b.w*0.5) + 0.15
                shift_attempt += 1

            # final check: if still overlapping, skip candidate
            bad = False
            for bb in self.buildings:
                if buildings_overlap(b, bb, margin=0.08):
                    bad = True
                    break
            if bad:
                continue

            self.buildings.append(b)
            prev = b
            z += BUILDING_DEPTH + gap
            i += 1

        # fill remaining with safe-placement attempts
        while len(self.buildings) < cfg['num_buildings']:
            attempt = 0
            placed = False
            while attempt < 30 and not placed:
                x = rng.choice(cfg['lanes']) + rng.uniform(-3.0, 3.0)
                w = rng.uniform(cfg['min_w'], cfg['max_w'])
                h_phys = rng.uniform(cfg['min_h'], cfg['max_h'])
                b = Building(x, z + attempt * 0.5, w, BUILDING_DEPTH, h_phys)
                clash = False
                for bb in self.buildings:
                    if buildings_overlap(b, bb, margin=0.08):
                        clash = True
                        break
                if not clash:
                    self.buildings.append(b)
                    placed = True
                else:
                    attempt += 1
            if not placed:
                b = Building(rng.choice(cfg['lanes']), z, rng.uniform(cfg['min_w'], cfg['max_w']), BUILDING_DEPTH, rng.uniform(cfg['min_h'], cfg['max_h']))
                self.buildings.append(b)
            z += BUILDING_DEPTH + cfg['gap_min']

        self.buildings.sort(key=lambda bb: bb.z)

        # reachability passes
        horiz_reach_target = max_jump_horizontal(SPRINT_SPEED, JUMP_V, GRAVITY) * 0.98
        max_visual_up = max_up * 0.98
        max_visual_down = max_visual_up * 3.0
        for _pass in range(6):
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
        self.cutscene_player_start = None
        self.cutscene_player_hidden = False
        self.cutscene_door_progress = 0.0

        # reset camera pan
        self.cam_pan_active = False
        self.cam_pan_t = 0.0
        self.cam_pan_start_pos = None
        self.cam_pan_start_target = None
        self.cam_pan_end_pos = None
        self.cam_pan_end_target = None

        # reset new flags
        self._start_cutscene_after_pan = False
        self.controls_locked = False

        # skyline scale: small on early levels (far away), larger on later levels (closer)
        lvl_frac = (self.level_index / max(1, len(LEVELS)-1))
        # range from 0.78 (far) to 1.15 (close)
        self.skyline_scale = lerp(0.78, 1.15, lvl_frac)

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

    def start_end_cutscene(self, preserve_camera=False):
        # preserve_camera: when True, do not jump the camera position/orientation
        if self.cutscene_active: return
        self.cutscene_active = True
        self.cutscene_t = 0.0
        self.cutscene_phase = 0

        # hide level complete overlay while cutscene plays
        self.level_completed = False

        final_b = self.buildings[-1]
        # city target far ahead of final building (placed at skyline depth)
        city_target = Vec3(final_b.x, final_b.h_visual + 8.0, final_b.z + final_b.d * 8.0)
        self.cutscene_city_target = city_target

        # compute direction from player to city (if degenerate, default forward)
        player_pos = Vec3(self.player_x, self.player_y, self.player_z)
        dir_to_city = normalize(Vec3(city_target.x - player_pos.x, city_target.y - player_pos.y, city_target.z - player_pos.z))

        # If preserve_camera is False, reposition the camera to a cinematic offset.
        if not preserve_camera:
            world_up = Vec3(0,1,0)
            right_vec = normalize(cross(dir_to_city, world_up))
            cam_offset_right = 12.0  # moved further to the right
            cam_height = 8.0         # higher so you see more of the skyline
            cam_back = 36.0          # further back to see more buildings
            # camera placed relative to the player/car initial position and left fixed
            # move the camera out to the right and back along -center_dir
            # we want the camera to face ~45 degrees left from the center line: compute yaw from center_dir and add +45 deg
            self.cam_pos = Vec3(player_pos.x + right_vec.x * cam_offset_right - dir_to_city.x * cam_back,
                                 player_pos.y + cam_height,
                                 player_pos.z + right_vec.z * cam_offset_right - dir_to_city.z * cam_back)
            # look toward a point ahead along center_dir but rotated left by 45 deg
            first_b = self.buildings[0] if len(self.buildings) > 0 else None
            center_dir = dir_to_city
            if first_b:
                center_dir = normalize(Vec3(final_b.x - first_b.x, 0.0, final_b.z - first_b.z))
            yaw_center = math.atan2(center_dir.x, center_dir.z)
            yaw_left45 = yaw_center + math.radians(45.0)
            look_dir = Vec3(math.sin(yaw_left45), 0.0, math.cos(yaw_left45))
            target_dist = 28.0
            self.cam_target = Vec3(player_pos.x + look_dir.x * target_dist, player_pos.y + 2.0 + 0.0, player_pos.z + look_dir.z * target_dist)
            self.forward, self.right, self.up = build_camera_basis(self.cam_pos, self.cam_target)
            yaw = math.atan2(self.cam_pos.x - self.cam_target.x, self.cam_pos.z - self.cam_target.z)
            self.cutscene_cam_orig = (self.cam_yaw, self.cam_pitch)
            self.cam_yaw = yaw
            self.cam_pitch = radians(8.0)
            self.cutscene_cam_target_orient = (self.cam_yaw, self.cam_pitch)
        else:
            # preserve current camera orientation/pos but remember it for restoring later if needed
            self.cutscene_cam_orig = (self.cam_yaw, self.cam_pitch)
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

        # put player in vehicle visually (but we'll animate him entering)
        # store start position for interpolation
        self.cutscene_player_start = Vec3(self.player_x, self.player_y, self.player_z)

        # stop background music and start the cutscene soundtrack (keeps playing until returning to menu)
        try:
            self.stop_music()
        except Exception:
            pass
        if self.audio.get('cutscene_music_loaded', False):
            try:
                pygame.mixer.music.load(self.audio['cutscene_music_path'])
                pygame.mixer.music.play(-1)
            except Exception:
                pass

        # play car loop if available (looping)
        if self.audio.get('car_loop'):
            try:
                self.cutscene_car_channel = self.audio['car_loop'].play(loops=-1)
            except Exception:
                self.cutscene_car_channel = None
        self.play_sfx('pickup')
        self.fade_alpha = 0.0

        # lock controls during cutscene
        self.controls_locked = True
        self.cutscene_player_hidden = False
        self.cutscene_door_progress = 0.0
        self.cutscene_phase = 0
        self.cutscene_t = 0.0

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
        # handle cutscene movement (multi-phase)
        if self.cutscene_active:
            self.cutscene_t += dt

            # phases:
            # 0 = player walks into car (interpolate)
            # 0.5 = door/entry animation (player silhouette fades/hidden)
            # 1 = short pause
            # 2 = accelerate phase (vehicle moves and shrinks)
            # 3 = fade to black -> gameover

            # timings (configurable)
            walk_time = 0.9
            door_time = 0.7
            pause_time = 0.45
            # movement phases start after these
            move_lead = 0.0  # we re-use earlier approach/accel timings for the flight
            approach_time = 4.0
            accel_time = 3.6
            fade_time = 2.6

            # PHASE 0: player walks into car
            if self.cutscene_phase == 0:
                if self.cutscene_t <= walk_time:
                    t = self.cutscene_t / max(1e-6, walk_time)
                    # interpolate player from roof to just beside/inside vehicle
                    sx, sy, sz = self.cutscene_player_start.x, self.cutscene_player_start.y, self.cutscene_player_start.z
                    vx, vy, vz = self.vehicle_pos.x, self.vehicle_pos.y - 0.9, self.vehicle_pos.z  # goal slightly lower inside car
                    self.player_x = lerp(sx, vx, t)
                    self.player_y = lerp(sy, vy, t)
                    self.player_z = lerp(sz, vz, t)
                    # keep camera fixed (it was panned)
                    return
                else:
                    # move to door animation phase
                    self.cutscene_phase = 0.5
                    self.cutscene_t = 0.0
                    self.cutscene_door_progress = 0.0
                    return

            # PHASE 0.5: door/entry animation (canopy closes, player fades)
            if self.cutscene_phase == 0.5:
                self.cutscene_door_progress += dt / max(1e-6, door_time)
                self.cutscene_door_progress = clamp(self.cutscene_door_progress, 0.0, 1.0)
                # keep player positioned near vehicle (slightly inside)
                self.player_x = self.vehicle_pos.x
                self.player_y = self.vehicle_pos.y - 0.9
                self.player_z = self.vehicle_pos.z
                # at end of door animation, hide player
                if self.cutscene_door_progress >= 1.0:
                    self.cutscene_phase = 1
                    self.cutscene_t = 0.0
                    self.cutscene_player_hidden = True
                return

            # PHASE 1: short pause
            if self.cutscene_phase == 1:
                if self.cutscene_t >= pause_time:
                    # begin movement / flight phase
                    self.cutscene_phase = 2
                    self.cutscene_t = 0.0
                    # re-init vehicle_pos to ensure consistent movement start
                    # vehicle_dir already set
                else:
                    return

            # PHASE 2: flight movement
            if self.cutscene_phase == 2:
                # reuse earlier timing for gradual acceleration then sustained speed
                t_since_start = self.cutscene_t
                lead_time = move_lead
                # small lead (we keep vehicle stationary for now because door animation handled separately)
                if t_since_start <= lead_time + 0.0001:
                    # no movement
                    return
                # then approach & accel
                t_since_lead = t_since_start - lead_time
                if t_since_lead < approach_time:
                    t = min(1.0, t_since_lead / approach_time)
                    speed = 8.0 + 42.0 * t
                    self.vehicle_pos.x += self.vehicle_dir.x * speed * dt
                    self.vehicle_pos.y += self.vehicle_dir.y * speed * dt
                    self.vehicle_pos.z += self.vehicle_dir.z * speed * dt
                else:
                    t2 = t_since_lead - approach_time
                    if t2 < accel_time:
                        t = min(1.0, t2 / accel_time)
                        acc_speed = 60.0 + 200.0 * t
                        self.vehicle_pos.x += self.vehicle_dir.x * acc_speed * dt
                        self.vehicle_pos.y += self.vehicle_dir.y * acc_speed * dt
                        self.vehicle_pos.z += self.vehicle_dir.z * acc_speed * dt
                    else:
                        # move into fade phase
                        self.cutscene_phase = 3
                        self.cutscene_t = 0.0
                        return
                # update player (hidden) position to vehicle position for any later uses
                self.player_x = self.vehicle_pos.x
                self.player_y = self.vehicle_pos.y - 1.4
                self.player_z = self.vehicle_pos.z
                # update fade_alpha in later phase; for realism we may slightly increase sky scale or do nothing
                return

            # PHASE 3: fade to black
            if self.cutscene_phase == 3:
                # reuse fade_time
                self.cutscene_t += dt
                self.fade_alpha = clamp(self.cutscene_t / max(1e-6, fade_time), 0.0, 1.0)
                if self.cutscene_t >= fade_time:
                    # finish cutscene
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
                    # unlock controls only when player returns to menu or restarts
                    self.controls_locked = False
                    self.cutscene_player_hidden = False
                return

        # camera pan handling after level complete
        if self.cam_pan_active:
            self.cam_pan_t = min(self.cam_pan_dur, self.cam_pan_t + dt)
            t = self.cam_pan_t / max(1e-6, self.cam_pan_dur)
            # smooth interpolation (ease in/out)
            t_s = t * t * (3 - 2*t)
            sp = Vec3(lerp(self.cam_pan_start_pos.x, self.cam_pan_end_pos.x, t_s),
                      lerp(self.cam_pan_start_pos.y, self.cam_pan_end_pos.y, t_s),
                      lerp(self.cam_pan_start_pos.z, self.cam_pan_end_pos.z, t_s))
            st = Vec3(lerp(self.cam_pan_start_target.x, self.cam_pan_end_target.x, t_s),
                      lerp(self.cam_pan_start_target.y, self.cam_pan_end_target.y, t_s),
                      lerp(self.cam_pan_start_target.z, self.cam_pan_end_target.z, t_s))
            self.cam_pos = sp
            self.cam_target = st
            self.forward, self.right, self.up = build_camera_basis(self.cam_pos, self.cam_target)
            if self.cam_pan_t >= self.cam_pan_dur:
                self.cam_pan_active = False
                # if we were asked to start the cutscene after pan, do it now, preserving the camera
                if self._start_cutscene_after_pan:
                    self._start_cutscene_after_pan = False
                    # start cutscene but preserve the panned camera (so cutscene camera stays where pan left it)
                    self.start_end_cutscene(preserve_camera=True)
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
                # if we hit the roof with large downward speed, play death sfx (heavy landing)
                if hasattr(self, 'player_vy') and self.player_vy < -12.0:
                    self.play_sfx('death')
                self.player_y = landed.h_visual
                self.player_vy = 0.0
                self.player_on_ground = True
                self.fell_off = False
                self.left_by_jump = False
        else:
            if self.player_y <= -8.0:
                # death sound on falling below kill-plane
                self.play_sfx('death')
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

            # compute cinematic pan end using center-line and offsets:
            first_b = self.buildings[0] if len(self.buildings) > 0 else None
            center_dir = Vec3(0.0, 0.0, 1.0)
            if first_b:
                center_dir = normalize(Vec3(last.x - first_b.x, 0.0, last.z - first_b.z))
            world_up = Vec3(0,1,0)
            right_vec = normalize(cross(center_dir, world_up))

            # start pan from current camera
            self.cam_pan_t = 0.0
            # slightly longer pan for cinematic feeling
            self.cam_pan_dur = 1.4

            self.cam_pan_start_pos = Vec3(self.cam_pos.x, self.cam_pos.y, self.cam_pos.z)
            self.cam_pan_start_target = Vec3(self.cam_target.x, self.cam_target.y, self.cam_target.z)

            # Place cam further back and to the right so you can see more buildings
            pan_right = 12.0
            pan_height = 8.0
            pan_back = 36.0
            end_pos = Vec3(self.player_x + right_vec.x * pan_right - center_dir.x * pan_back,
                           self.player_y + pan_height,
                           self.player_z + right_vec.z * pan_right - center_dir.z * pan_back)
            # camera should look 45 degrees left from the center direction
            yaw_center = math.atan2(center_dir.x, center_dir.z)
            yaw_left45 = yaw_center + math.radians(45.0)
            look_dir = Vec3(math.sin(yaw_left45), 0.0, math.cos(yaw_left45))
            end_target = Vec3(self.player_x + look_dir.x * 22.0, self.player_y + 2.5, self.player_z + look_dir.z * 22.0)

            self.cam_pan_end_pos = end_pos
            self.cam_pan_end_target = end_target

            # If this is the final level, lock controls now (will be fully enforced in the event loop).
            if self.level_index >= len(LEVELS) - 1:
                self.controls_locked = True
            return

        # nothing else in update

    def draw_skyline_background(self):
        s = self.screen
        layers = 3
        scale = self.skyline_scale
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

        # billboard (fixed scale)
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

        # if cutscene is active, draw twinkling stars in the sky
        if self.cutscene_active:
            now = time.time()
            for (sx, sy, sz, tw) in self.cutscene_stars:
                br = 120 + 80 * math.sin(now*tw*0.8 + sx*0.0009)
                # slightly dimmer than the gameover stars so the skyline still reads
                pygame.draw.circle(s, (int(br*0.9), int(br*0.9), int(br*0.95)), (int(sx), int(sy+40)), sz)

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

        # Add player and vehicle as drawable entries so they receive depth sorting and can be partially occluded
        ppos = Vec3(self.player_x, self.player_y + PLAYER_HEIGHT*0.25, self.player_z)
        psx, psy, psc, pcz = project_point(ppos, self.cam_pos, self.forward, self.right, self.up, fov)
        player_proj = None
        # hide player during cutscene when inside car
        if not (self.cutscene_active and self.cutscene_player_hidden):
            if isfinite(psx) and isfinite(psy) and isfinite(pcz) and pcz > 0:
                player_proj = (psx, psy, psc, pcz)

        vehicle_proj = None
        if self.cutscene_active and self.vehicle_pos is not None:
            vpx, vpy, vps, vcz = project_point(self.vehicle_pos, self.cam_pos, self.forward, self.right, self.up, fov)
            if isfinite(vpx) and isfinite(vpy) and isfinite(vps) and vcz > 0:
                vehicle_proj = (vpx, vpy, vps, vcz)

        # Group faces by building
        from collections import defaultdict
        groups = defaultdict(list)
        for f in face_list:
            groups[f['b_idx']].append(f)

        entries = []
        # building entries
        for bidx, faces in groups.items():
            b = faces[0].get('building')
            center_world = Vec3(b.x, b.h_visual * 0.5, b.z + b.d * 0.5)
            pc = project_point(center_world, self.cam_pos, self.forward, self.right, self.up, fov)
            center_cz = pc[3] if (pc and isfinite(pc[3])) else (sum(f['cz'] for f in faces) / len(faces))
            entries.append((center_cz, 'building', bidx, faces))
        # player entry
        if player_proj is not None:
            entries.append((player_proj[3], 'player', None, player_proj))
        # vehicle entry (if cutscene active)
        if vehicle_proj is not None:
            entries.append((vehicle_proj[3], 'vehicle', None, vehicle_proj))

        # sort far -> near
        entries.sort(key=lambda e: e[0], reverse=True)

        t = time.time() - getattr(self, 'time_start', 0.0)

        # helper: compute face normal and whether it faces camera
        def face_normal(poly_world):
            try:
                a = poly_world[0]; b = poly_world[1]; c = poly_world[2]
                e1 = Vec3(b.x - a.x, b.y - a.y, b.z - a.z)
                e2 = Vec3(c.x - a.x, c.y - a.y, c.z - a.z)
                n = cross(e1, e2)
                return n
            except Exception:
                return Vec3(0,1,0)

        # draw grouped entries
        for ent in entries:
            typ = ent[1]
            if typ == 'player':
                try:
                    psx, psy, psc, pcz = ent[3]
                    if not (isfinite(psx) and isfinite(psy) and isfinite(pcz) and pcz > 0):
                        continue
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
                except Exception:
                    pass
                continue

            if typ == 'vehicle':
                try:
                    vpx, vpy, vps, vcz = ent[3]
                    if not (isfinite(vpx) and isfinite(vpy) and isfinite(vcz) and vcz > 0):
                        continue

                    # FIXED: use projection scale (vps) * factor so object becomes SMALLER when CZ INCREASES (further away)
                    # earlier code inverted this; now scale is proportional to vps.
                    screen_scale = clamp(vps * 0.06, 0.02, 3.2)

                    wv = int(320 * screen_scale)   # slightly larger base so the craft looks sleeker
                    hv = int(88 * screen_scale)
                    cx = int(vpx); cy = int(vpy)

                    # Futuristic flying vehicle silhouette
                    # Main hull (sleek, low, elongated)
                    hull = [
                        (cx - int(wv*0.52), cy),
                        (cx - int(wv*0.22), cy - int(hv*0.42)),
                        (cx - int(wv*0.00), cy - int(hv*0.5)),
                        (cx + int(wv*0.28), cy - int(hv*0.42)),
                        (cx + int(wv*0.52), cy),
                        (cx + int(wv*0.28), cy + int(hv*0.22)),
                        (cx - int(wv*0.12), cy + int(hv*0.26)),
                    ]
                    pygame.draw.polygon(s, (18,20,24), hull)
                    # canopy/glass
                    canopy = [
                        (cx - int(wv*0.18), cy - int(hv*0.36)),
                        (cx + int(wv*0.18), cy - int(hv*0.36)),
                        (cx + int(wv*0.12), cy - int(hv*0.06)),
                        (cx - int(wv*0.06), cy - int(hv*0.06)),
                    ]
                    pygame.draw.polygon(s, (36,48,62), canopy)
                    pygame.draw.polygon(s, (90,150,200), canopy, 2)
                    # rear engine glows
                    for i in range(2):
                        thr_w = int(wv*0.18)
                        thr_h = int(hv*0.28)
                        thr_surf = pygame.Surface((thr_w, thr_h), pygame.SRCALPHA)
                        # pulsate slightly using time so it's alive
                        pulse = int(80 + 60 * math.sin(time.time()*6.0 + i*1.2))
                        pygame.draw.ellipse(thr_surf, (60, 140, 240, pulse), (0,0,thr_w,thr_h))
                        s.blit(thr_surf, (cx + int(wv*0.26) + i*int(wv*0.03), cy - thr_h//2))
                    # front lights
                    left_light = (cx - int(wv*0.42), cy - int(hv*0.05))
                    right_light = (cx + int(wv*0.42) - 4, cy - int(hv*0.05))
                    pygame.draw.circle(s, (160,220,255), left_light, max(1, int(6*screen_scale)))
                    pygame.draw.circle(s, (160,220,255), right_light, max(1, int(6*screen_scale)))
                    # subtle underside glow
                    ugw = int(wv*0.7); ugh = int(hv*0.24)
                    ug = pygame.Surface((ugw, ugh), pygame.SRCALPHA)
                    pygame.draw.ellipse(ug, (40,90,160,90), (0,0,ugw,ugh))
                    s.blit(ug, (cx - ugw//2, cy + int(hv*0.18)))

                    # if in door animation (cutscene_phase == 0.5), draw canopy closing visual using door progress
                    if self.cutscene_active and self.cutscene_phase == 0.5:
                        # draw a canopy overlay that grows down to cover cockpit
                        prog = clamp(self.cutscene_door_progress, 0.0, 1.0)
                        cover_h = int(hv * 0.44 * prog)
                        cover_surf = pygame.Surface((int(wv*0.36), cover_h), pygame.SRCALPHA)
                        alpha = int(200 * prog)
                        cover_surf.fill((10,14,18, alpha))
                        s.blit(cover_surf, (cx - int(wv*0.18), cy - int(hv*0.36)))
                        # silhouette: a small dark oval that fades as prog approaches 1.0
                        silpha = int(200 * (1.0 - prog))
                        if silpha > 4:
                            sil_surf = pygame.Surface((int(wv*0.12), int(hv*0.18)), pygame.SRCALPHA)
                            pygame.draw.ellipse(sil_surf, (6,6,8, silpha), sil_surf.get_rect())
                            s.blit(sil_surf, (cx - int(wv*0.06), cy - int(hv*0.22)))
                except Exception:
                    pass
                continue

            # building entry
            faces = ent[3]
            # draw building's faces far -> near (so nearer faces draw over farther faces of same building)
            faces_sorted = sorted(faces, key=lambda x: x['cz'], reverse=True)
            for f in faces_sorted:
                poly = f.get('poly')
                if not poly or not safe_poly(poly):
                    continue
                try:
                    pygame.draw.polygon(s, f['col'], poly)
                    pygame.draw.polygon(s, (10,10,12), poly, 1)
                    fi = f['face_idx']

                    # only draw windows on side faces and only if the face outward normal points toward the camera
                    if fi in (4,5):
                        pw = f['poly_world']
                        # compute face normal and view direction
                        n = face_normal(pw)
                        # view direction from face toward camera
                        face_center = Vec3(sum(v.x for v in pw)/4.0, sum(v.y for v in pw)/4.0, sum(v.z for v in pw)/4.0)
                        view_dir = Vec3(self.cam_pos.x - face_center.x, self.cam_pos.y - face_center.y, self.cam_pos.z - face_center.z)
                        # if normal dot view_dir <= 0, the face is facing away or inverted; skip window drawing
                        if dot(n, view_dir) <= 0:
                            continue

                        sorted_by_y = sorted(pw, key=lambda v: v.y, reverse=True)
                        top_pts = sorted_by_y[:2]
                        bot_pts = sorted_by_y[2:]
                        pair = sorted(zip(top_pts, bot_pts), key=lambda pr: dot(pr[0], self.right))
                        if len(pair) == 2:
                            (tL, bL), (tR, bR) = (pair[0][0], pair[0][1]), (pair[1][0], pair[1][1])

                            # world-space midpoints for top and bottom
                            mid_top = Vec3((tL.x + tR.x)/2.0, (tL.y + tR.y)/2.0, (tL.z + tR.z)/2.0)
                            mid_bot = Vec3((bL.x + bR.x)/2.0, (bL.y + bR.y)/2.0, (bL.z + bR.z)/2.0)

                            # inset fraction, thickness (world-space fractions)
                            v_pad = 0.03
                            v0 = v_pad
                            v1 = 1.0 - v_pad
                            thickness = 0.04

                            # local Vec3 helpers
                            def v_sub(a, b): return Vec3(a.x - b.x, a.y - b.y, a.z - b.z)
                            def v_add(a, b): return Vec3(a.x + b.x, a.y + b.y, a.z + b.z)
                            def v_mul(a, s): return Vec3(a.x * s, a.y * s, a.z * s)
                            def v_len(a): return math.sqrt(a.x*a.x + a.y*a.y + a.z*a.z)
                            def v_norm(a):
                                L = v_len(a)
                                if L <= 1e-9: return Vec3(0.0,0.0,0.0)
                                return Vec3(a.x/L, a.y/L, a.z/L)
                            def v_cross(a,b): return Vec3(a.y*b.z - a.z*b.y, a.z*b.x - a.x*b.z, a.x*b.y - a.y*b.x)
                            def dot3(a,b): return a.x*b.x + a.y*b.y + a.z*b.z

                            # inset edge points (world)
                            top_v0 = Vec3(lerp(tL.x, tR.x, v0), lerp(tL.y, tR.y, v0), lerp(tL.z, tR.z, v0))
                            bot_v0 = Vec3(lerp(bL.x, bR.x, v0), lerp(bL.y, bR.y, v0), lerp(bL.z, bR.z, v0))
                            top_v1 = Vec3(lerp(tL.x, tR.x, v1), lerp(tL.y, tR.y, v1), lerp(tL.z, tR.z, v1))
                            bot_v1 = Vec3(lerp(bL.x, bR.x, v1), lerp(bL.y, bR.y, v1), lerp(bL.z, bR.z, v1))

                            # face axes in world-space (guarantees parallel edges)
                            u_world_raw = v_sub(top_v1, top_v0)
                            v_left_raw  = v_sub(bot_v0, top_v0)
                            v_right_raw = v_sub(bot_v1, top_v1)

                            top_len_world = v_len(u_world_raw)
                            if top_len_world <= 1e-6:
                                continue

                            u_world = v_norm(u_world_raw)
                            nv_left = v_norm(v_left_raw)
                            nv_right = v_norm(v_right_raw)
                            avg_v = v_add(nv_left, nv_right)
                            if v_len(avg_v) <= 1e-6:
                                cu = u_world
                                up = self.up
                                avg_v = v_cross(cu, up)
                                if v_len(avg_v) <= 1e-6:
                                    avg_v = Vec3(0.0, 1.0, 0.0)
                            v_world = v_norm(avg_v)

                            full_top_len_world = top_len_world
                            width_world = max(1e-3, full_top_len_world * 0.92)
                            half_w_world = width_world * 0.5
                            avg_vert_len_world = 0.5 * (v_len(v_left_raw) + v_len(v_right_raw))
                            if avg_vert_len_world <= 1e-6:
                                continue
                            height_world = max(1e-3, avg_vert_len_world * thickness)
                            half_h_world = min(height_world * 0.5, (avg_vert_len_world * 0.5) * 0.98)

                            proj_mid_top = project_point(mid_top, self.cam_pos, self.forward, self.right, self.up, fov)
                            proj_mid_bot = project_point(mid_bot, self.cam_pos, self.forward, self.right, self.up, fov)
                            def proj_ok(p):
                                try:
                                    return isfinite(p[0]) and isfinite(p[1]) and isfinite(p[3]) and (p[3] > 0.05)
                                except Exception:
                                    return False
                            if not (proj_ok(proj_mid_top) and proj_ok(proj_mid_bot)):
                                continue

                            screen_h = abs(proj_mid_bot[1] - proj_mid_top[1])
                            screen_h = max(8.0, screen_h)
                            num_rows = clamp(int(screen_h / 25), 4, 80)

                            now = time.time()
                            prev_cam = getattr(self, '_prev_cam_pos', None)
                            prev_time = getattr(self, '_prev_cam_time', None)
                            cam_motion = 0.0
                            cam_speed = 0.0
                            if prev_cam is not None and prev_time is not None:
                                dx = (self.cam_pos.x - prev_cam.x); dy = (self.cam_pos.y - prev_cam.y); dz = (self.cam_pos.z - prev_cam.z)
                                cam_motion = math.sqrt(dx*dx + dy*dy + dz*dz)
                                dt = max(1e-6, now - prev_time)
                                cam_speed = cam_motion / dt
                            self._prev_cam_pos = Vec3(self.cam_pos.x, self.cam_pos.y, self.cam_pos.z)
                            self._prev_cam_time = now

                            sine_speed = 1.6
                            sine_amp = 50.0
                            sine_phase = 0.28
                            base_brightness = 130

                            face_col = f.get('col', (20,24,40))
                            window_base = (min(255, face_col[0] + 8), min(255, face_col[1] + 16), min(255, face_col[2] + 56))

                            MIN_HALF_H = 10.0
                            MIN_FULL_W = 28.0

                            idx_counter = 0
                            margin_world = half_h_world / max(avg_vert_len_world, 1e-6)
                            margin_world = clamp(margin_world, 0.0, 0.45)

                            for r in range(num_rows):
                                frac = (r + 0.5) / num_rows
                                u_center = margin_world + frac * (1.0 - 2.0 * margin_world)

                                cx_w = lerp(mid_top.x, mid_bot.x, u_center)
                                cy_w = lerp(mid_top.y, mid_bot.y, u_center)
                                cz_w = lerp(mid_top.z, mid_bot.z, u_center)
                                center_world = Vec3(cx_w, cy_w, cz_w)

                                tl_w = v_sub(v_sub(center_world, v_mul(u_world, half_w_world)), v_mul(v_world, half_h_world))
                                tr_w = v_add(v_sub(center_world, v_mul(v_world, half_h_world)), v_mul(u_world, half_w_world))
                                br_w = v_add(v_add(center_world, v_mul(u_world, half_w_world)), v_mul(v_world, half_h_world))
                                bl_w = v_sub(v_add(center_world, v_mul(v_world, half_h_world)), v_mul(u_world, half_w_world))

                                p_tl = project_point(tl_w, self.cam_pos, self.forward, self.right, self.up, fov)
                                p_tr = project_point(tr_w, self.cam_pos, self.forward, self.right, self.up, fov)
                                p_br = project_point(br_w, self.cam_pos, self.forward, self.right, self.up, fov)
                                p_bl = project_point(bl_w, self.cam_pos, self.forward, self.right, self.up, fov)
                                if not (proj_ok(p_tl) and proj_ok(p_tr) and proj_ok(p_br) and proj_ok(p_bl)):
                                    idx_counter += 1
                                    continue

                                rect = [(p_tl[0], p_tl[1]), (p_tr[0], p_tr[1]), (p_br[0], p_br[1]), (p_bl[0], p_bl[1])]
                                if not safe_poly(rect):
                                    idx_counter += 1
                                    continue

                                proj_half_h = 0.5 * math.hypot(rect[0][0]-rect[3][0], rect[0][1]-rect[3][1])
                                proj_full_w = math.hypot(rect[1][0]-rect[0][0], rect[1][1]-rect[0][1])

                                cx = sum(pt[0] for pt in rect) / 4.0
                                cy = sum(pt[1] for pt in rect) / 4.0

                                edge_dx = rect[1][0] - rect[0][0]; edge_dy = rect[1][1] - rect[0][1]
                                edge_len = math.hypot(edge_dx, edge_dy)
                                if edge_len > 1e-6:
                                    edge_dir = (edge_dx/edge_len, edge_dy/edge_len)
                                else:
                                    edge_dir = (1.0, 0.0)
                                v_dx = rect[3][0] - rect[0][0]; v_dy = rect[3][1] - rect[0][1]
                                v_len_screen = math.hypot(v_dx, v_dy)
                                if v_len_screen > 1e-6:
                                    v_dir = (v_dx / v_len_screen, v_dy / v_len_screen)
                                else:
                                    v_dir = (0.0, 1.0)

                                rebuild = False
                                half_w_screen = proj_full_w * 0.5
                                half_h_screen = proj_half_h
                                if proj_half_h < MIN_HALF_H:
                                    half_h_screen = MIN_HALF_H
                                    rebuild = True
                                if proj_full_w < MIN_FULL_W:
                                    half_w_screen = MIN_FULL_W * 0.5
                                    rebuild = True

                                if rebuild:
                                    max_half_w = max(half_w_screen, 0.5 * proj_full_w)
                                    half_w_screen = min(half_w_screen, max_half_w)
                                    tl = (cx - edge_dir[0]*half_w_screen - v_dir[0]*half_h_screen,
                                          cy - edge_dir[1]*half_w_screen - v_dir[1]*half_h_screen)
                                    tr = (cx + edge_dir[0]*half_w_screen - v_dir[0]*half_h_screen,
                                          cy + edge_dir[1]*half_w_screen - v_dir[1]*half_h_screen)
                                    br = (cx + edge_dir[0]*half_w_screen + v_dir[0]*half_h_screen,
                                          cy + edge_dir[1]*half_w_screen + v_dir[1]*half_h_screen)
                                    bl = (cx - edge_dir[0]*half_w_screen + v_dir[0]*half_h_screen,
                                          cy - edge_dir[1]*half_w_screen + v_dir[1]*half_h_screen)
                                    rect = [tl, tr, br, bl]

                                sine = math.sin(t * sine_speed + idx_counter * sine_phase)
                                movement_boost = clamp(min(cam_speed / 4.0, 1.0), 0.0, 0.9)
                                intensity = clamp(0.25 + 0.75 * movement_boost + 0.35 * (sine * 0.5 + 0.5), 0.0, 1.0)
                                brightness = int(clamp(base_brightness + sine_amp * (sine * 0.6 + 0.4) + intensity * 40.0, 120, 255))

                                wr = int(clamp(window_base[0] * 0.35 + brightness * 0.65, 0, 255))
                                wg = int(clamp(window_base[1] * 0.30 + brightness * 0.70, 0, 255))
                                wb = int(clamp(window_base[2] * 0.25 + brightness * 0.75, 0, 255))

                                v_dir_x = (rect[3][0] - rect[0][0])
                                v_dir_y = (rect[3][1] - rect[0][1])
                                v_dir_len = math.hypot(v_dir_x, v_dir_y)
                                if v_dir_len > 1e-6:
                                    v_dir_x /= v_dir_len; v_dir_y /= v_dir_len
                                else:
                                    v_dir_x, v_dir_y = 0.0, 1.0

                                shadow_off = max(1.0, half_h_screen * 0.25)
                                back = [(p[0] - v_dir_x*shadow_off, p[1] - v_dir_y*shadow_off) for p in rect]
                                pygame.draw.polygon(s, (8,8,10), back)

                                cx_draw = sum(pt[0] for pt in rect) / 4.0
                                cy_draw = sum(pt[1] for pt in rect) / 4.0
                                shrink_inner = 0.94
                                inner_shrunk = [((pt[0]-cx_draw)*shrink_inner + cx_draw, (pt[1]-cy_draw)*shrink_inner + cy_draw) for pt in rect]

                                pygame.draw.polygon(s, (28,32,36), inner_shrunk)
                                pygame.draw.polygon(s, (int(brightness-20), int(brightness+6), min(255, int(brightness+30))), inner_shrunk)
                                pygame.draw.polygon(s, (6,6,8), inner_shrunk, 1)
                                idx_counter += 1

                except Exception:
                    continue

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

        # LEVEL COMPLETE overlay (restored) + press N prompt
        if self.level_completed:
            # show overlay while waiting for N — if N is pressed we clear level_completed immediately (see event handler)
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
            hint_surf = self.font.render("Press N to continue", True, (240,240,200))
            s.blit(hint_surf, (WIN_W//2 - hint_surf.get_width()//2, WIN_H//2 + 64))

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

        # during the cutscene apply fade overlay if any
        if self.cutscene_active and self.fade_alpha > 0.001:
            ov = pygame.Surface((WIN_W, WIN_H))
            alpha = int(clamp(self.fade_alpha, 0.0, 1.0) * 255)
            ov.set_alpha(alpha)
            ov.fill((0,0,0))
            s.blit(ov, (0,0))

    def draw_ui(self, mantle_available=False):
        # Hide cinematic HUD elements during cutscene for a clean cinematic feel
        if self.cutscene_active:
            return

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

        # controls text: made cleaner
        controls = "WASD / Arrow Keys  Space: Jump  E: Mantle  R: Reset"
        ctr_surf = self.font.render(controls, True, (170,190,210))
        # draw a slightly transparent box behind controls (same feel as the level start overlay)
        padding_x = 12
        padding_y = 8
        w_box = ctr_surf.get_width() + padding_x*2
        h_box = ctr_surf.get_height() + padding_y*2
        box_surf = pygame.Surface((w_box, h_box), pygame.SRCALPHA)
        box_surf.fill((6,6,10,180))  # same alpha as level start overlay
        # subtle border
        pygame.draw.rect(box_surf, (18,18,20,220), (0,0,w_box,h_box), 2, border_radius=6)
        self.screen.blit(box_surf, (12, WIN_H - 26 - padding_y - 2))
        self.screen.blit(ctr_surf, (12 + padding_x, WIN_H - 26 - padding_y))

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
                        self.goto_menu()
                    # ignore other inputs while cutscene active
                    continue

                if self.state == 'play':
                    # If controls are locked (after final-level completion) we still want to allow
                    # ESC to return to menu and N to continue, but we ignore movement / camera / reset / sprint / mantle.
                    if ev.type == pygame.MOUSEBUTTONDOWN:
                        if not self.controls_locked:
                            if ev.button == 1:
                                self.lmb_held = True
                                pygame.mouse.get_rel()
                            elif ev.button == 4:
                                self.cam_dist = clamp(self.cam_dist * 0.92, CAM_DIST_MIN, CAM_DIST_MAX)
                            elif ev.button == 5:
                                self.cam_dist = clamp(self.cam_dist / 0.92, CAM_DIST_MIN, CAM_DIST_MAX)
                    elif ev.type == pygame.MOUSEBUTTONUP:
                        if not self.controls_locked and ev.button == 1:
                            self.lmb_held = False
                            pygame.mouse.get_rel()
                    elif ev.type == pygame.KEYDOWN:
                        # movement & action keys only if not locked
                        if not self.controls_locked:
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
                        # ESC always allowed to go to menu
                        if ev.key == pygame.K_ESCAPE:
                            self.goto_menu()
                        # N pressed to continue; allowed even if controls locked (that's the point)
                        if ev.key == pygame.K_n and self.level_completed and not self.cutscene_active:
                            # N pressed to continue
                            self.play_sfx('menu_confirm')
                            # hide level complete overlay immediately
                            self.level_completed = False
                            if self.level_index < len(LEVELS) - 1:
                                # go to next level (do NOT restart music)
                                self.level_index += 1
                                self.reset_world(self.level_index)
                            else:
                                # final level -> start camera pan then cutscene after pan completes
                                # ensure a pan was prepared during completion; start it now and flag to start cutscene after pan.
                                self.cam_pan_active = True
                                self._start_cutscene_after_pan = True
                    elif ev.type == pygame.KEYUP:
                        if not self.controls_locked:
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
                                self.reset_world(self.selected_level)
                                # clear inputs so player doesn't move at start
                                for k in inputs: inputs[k] = False
                                self.state = 'play'
                                # start background music explicitly when entering from menu
                                self.play_music(force=True)
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
                            self.reset_world(self.selected_level)
                            for k in inputs: inputs[k] = False
                            self.state = 'play'
                            self.play_music(force=True)
                        if ev.key == pygame.K_ESCAPE:
                            self.state = 'menu'

                elif self.state == 'paused':
                    if ev.type == pygame.KEYDOWN and ev.key == pygame.K_p:
                        self.state = 'play'

                elif self.state == 'victory':
                    if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                        self.goto_menu()

                elif self.state == 'gameover':
                    if ev.type == pygame.KEYDOWN:
                        if ev.key == pygame.K_ESCAPE:
                            self.goto_menu()
                        elif ev.key == pygame.K_RETURN:
                            # pressing start on the final YOU WIN screen should go to level 1
                            self.selected_level = 0
                            self.reset_world(0)
                            for k in inputs: inputs[k] = False
                            self.state = 'play'

            # mouse rotation while LMB held
            if self.state == 'play' and self.lmb_held and not self.cutscene_active and not self.controls_locked:
                mx, my = pygame.mouse.get_rel()
                self.cam_yaw += -mx * self.yaw_sens
                self.cam_pitch += -my * self.pitch_sens
                self.cam_pitch = clamp(self.cam_pitch, CAM_PITCH_MIN, CAM_PITCH_MAX)
            else:
                pygame.mouse.get_rel()

            # If controls are locked, ensure inputs are cleared so movement stops immediately.
            if self.controls_locked:
                for k in inputs:
                    inputs[k] = False

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
