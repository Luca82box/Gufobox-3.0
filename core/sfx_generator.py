"""
core/sfx_generator.py — Genera effetti sonori sintetici con Python puro.

Usa solo moduli standard: wave, struct, math, random.
Ogni effetto è un file WAV 44.1 kHz 16-bit mono.
"""

import math
import os
import random
import struct
import wave

# =========================================================
# CATALOGO
# =========================================================

SFX_CATALOG = {
    # Natura
    "rain_light":       "Pioggia leggera",
    "rain_heavy":       "Pioggia forte",
    "wind_gentle":      "Vento leggero",
    "wind_storm":       "Tempesta di vento",
    "thunder":          "Tuono",
    "birds_morning":    "Uccelli al mattino",
    "crickets_night":   "Grilli notturni",
    "river_stream":     "Ruscello",
    "ocean_waves":      "Onde del mare",
    "fire_crackling":   "Fuoco scoppiettante",
    # Animali
    "owl_hoot":         "Verso del gufo",
    "wolf_howl":        "Ululato del lupo",
    "horse_gallop":     "Galoppo di cavallo",
    "cat_meow":         "Miagolio",
    "dog_bark":         "Abbaio",
    "rooster_crow":     "Gallo che canta",
    # Azioni
    "footsteps_grass":  "Passi sull'erba",
    "footsteps_stone":  "Passi sulla pietra",
    "footsteps_snow":   "Passi sulla neve",
    "door_open":        "Porta che si apre",
    "door_creak":       "Porta che cigola",
    "door_slam":        "Porta che sbatte",
    "knock_door":       "Bussare alla porta",
    "key_lock":         "Chiave nella serratura",
    # Magia / Fantasy
    "magic_sparkle":    "Scintillio magico",
    "magic_whoosh":     "Soffio magico",
    "magic_bell":       "Campanella magica",
    "dragon_roar":      "Ruggito del drago",
    "sword_draw":       "Spada sguainata",
    "sword_clash":      "Scontro di spade",
    "treasure_open":    "Scrigno del tesoro",
    "potion_bubble":    "Pozione che bolle",
    # Ambienti
    "crowd_cheer":      "Folla che applaude",
    "clock_tick":       "Ticchettio orologio",
    "bell_tower":       "Campana",
    "drip_cave":        "Goccia in grotta",
    "wooden_bridge":    "Ponte di legno scricchiolante",
}

SAMPLE_RATE = 44100
MAX_AMP = 32767


# =========================================================
# UTILITÀ DI BASSO LIVELLO
# =========================================================

def _clamp(v: float) -> int:
    return max(-MAX_AMP, min(MAX_AMP, int(v * MAX_AMP)))


def _write_wav(path: str, samples: list) -> None:
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        data = struct.pack(f"<{len(samples)}h", *samples)
        wf.writeframes(data)


def _fade(samples: list, fade_in_ms: int = 20, fade_out_ms: int = 50) -> list:
    n = len(samples)
    fi = int(SAMPLE_RATE * fade_in_ms / 1000)
    fo = int(SAMPLE_RATE * fade_out_ms / 1000)
    result = list(samples)
    for i in range(min(fi, n)):
        result[i] = int(result[i] * i / fi)
    for i in range(min(fo, n)):
        idx = n - 1 - i
        result[idx] = int(result[idx] * i / fo)
    return result


def _white_noise(duration_s: float, amp: float = 0.3) -> list:
    n = int(SAMPLE_RATE * duration_s)
    return [_clamp(random.uniform(-amp, amp)) for _ in range(n)]


def _sine(freq: float, duration_s: float, amp: float = 0.5) -> list:
    n = int(SAMPLE_RATE * duration_s)
    return [_clamp(amp * math.sin(2 * math.pi * freq * i / SAMPLE_RATE)) for i in range(n)]


def _sine_sweep(f_start: float, f_end: float, duration_s: float, amp: float = 0.5) -> list:
    n = int(SAMPLE_RATE * duration_s)
    samples = []
    for i in range(n):
        t = i / SAMPLE_RATE
        freq = f_start + (f_end - f_start) * (i / n)
        samples.append(_clamp(amp * math.sin(2 * math.pi * freq * t)))
    return samples


def _mix(*signals: list) -> list:
    n = max(len(s) for s in signals)
    out = []
    for i in range(n):
        v = sum(s[i] if i < len(s) else 0 for s in signals)
        out.append(max(-MAX_AMP, min(MAX_AMP, v)))
    return out


def _concat(*signals: list) -> list:
    result = []
    for s in signals:
        result.extend(s)
    return result


def _silence(duration_s: float) -> list:
    return [0] * int(SAMPLE_RATE * duration_s)


def _lpf(samples: list, cutoff_hz: float = 1000.0) -> list:
    rc = 1.0 / (2 * math.pi * cutoff_hz)
    dt = 1.0 / SAMPLE_RATE
    alpha = dt / (rc + dt)
    out = []
    prev = 0.0
    for s in samples:
        y = prev + alpha * (s - prev)
        out.append(int(y))
        prev = y
    return out


# =========================================================
# GENERATORI
# =========================================================

def _gen_rain_light(path):
    samples = _lpf(_white_noise(2.5, 0.25), 1200)
    _write_wav(path, _fade(samples))


def _gen_rain_heavy(path):
    samples = _lpf(_white_noise(3.0, 0.55), 2500)
    _write_wav(path, _fade(samples))


def _gen_wind_gentle(path):
    n = int(SAMPLE_RATE * 3.0)
    samples = []
    for i in range(n):
        amp = 0.15 + 0.10 * math.sin(2 * math.pi * 0.3 * i / SAMPLE_RATE)
        samples.append(_clamp(random.uniform(-amp, amp)))
    _write_wav(path, _fade(samples, 80, 150))


def _gen_wind_storm(path):
    n = int(SAMPLE_RATE * 4.0)
    samples = []
    for i in range(n):
        amp = 0.4 + 0.3 * math.sin(2 * math.pi * 0.5 * i / SAMPLE_RATE)
        samples.append(_clamp(random.uniform(-amp, amp)))
    _write_wav(path, _fade(samples, 100, 200))


def _gen_thunder(path):
    crack = _white_noise(0.08, 0.9)
    n = int(SAMPLE_RATE * 2.0)
    rumble = []
    for i in range(n):
        amp = 0.6 * math.exp(-3 * i / n)
        rumble.append(_clamp(random.uniform(-amp, amp)))
    _write_wav(path, _fade(_concat(crack, rumble), 2, 300))


def _gen_birds_morning(path):
    def chirp(freq, dur):
        return _fade(_sine_sweep(freq, freq * 1.3, dur, 0.35), 5, 30)

    parts = []
    for _ in range(6):
        f = random.uniform(1800, 3200)
        parts.append(chirp(f, 0.12))
        parts.append(_silence(random.uniform(0.05, 0.25)))
    _write_wav(path, _concat(*parts))


def _gen_crickets_night(path):
    n = int(SAMPLE_RATE * 3.0)
    freq = 3800.0
    samples = []
    for i in range(n):
        chirp_val = math.sin(2 * math.pi * freq * i / SAMPLE_RATE)
        envelope = 1.0 if (i % int(SAMPLE_RATE * 0.08)) < int(SAMPLE_RATE * 0.05) else 0.0
        samples.append(_clamp(0.3 * chirp_val * envelope))
    _write_wav(path, _fade(samples, 100, 200))


def _gen_river_stream(path):
    samples = _lpf(_white_noise(3.0, 0.3), 800)
    n = len(samples)
    for i in range(n):
        mod = 0.85 + 0.15 * math.sin(2 * math.pi * 0.7 * i / SAMPLE_RATE)
        samples[i] = int(samples[i] * mod)
    _write_wav(path, _fade(samples, 150, 200))


def _gen_ocean_waves(path):
    n = int(SAMPLE_RATE * 4.0)
    wave_period = SAMPLE_RATE * 2.5
    samples = []
    noise = [random.uniform(-1, 1) for _ in range(n)]
    for i in range(n):
        env = 0.5 + 0.5 * math.sin(math.pi * (i % int(wave_period)) / wave_period)
        samples.append(_clamp(0.35 * noise[i] * env))
    _write_wav(path, _fade(samples, 200, 300))


def _gen_fire_crackling(path):
    n = int(SAMPLE_RATE * 3.0)
    samples = []
    for i in range(n):
        base = random.uniform(-0.1, 0.1)
        if random.random() < 0.005:
            base += random.uniform(-0.7, 0.7)
        samples.append(_clamp(base))
    _write_wav(path, _fade(samples, 100, 200))


def _gen_owl_hoot(path):
    parts = []
    for _ in range(2):
        s = []
        for i in range(int(SAMPLE_RATE * 0.4)):
            freq = 320 + 40 * math.sin(2 * math.pi * 4 * i / SAMPLE_RATE)
            s.append(_clamp(0.45 * math.sin(2 * math.pi * freq * i / SAMPLE_RATE)))
        parts.append(_fade(s, 20, 60))
        parts.append(_silence(0.15))
    _write_wav(path, _concat(*parts))


def _gen_wolf_howl(path):
    n = int(SAMPLE_RATE * 2.0)
    samples = []
    for i in range(n):
        t = i / n
        freq = 200 + 300 * math.sin(math.pi * t)
        samples.append(_clamp(0.5 * math.sin(2 * math.pi * freq * i / SAMPLE_RATE)))
    _write_wav(path, _fade(samples, 50, 200))


def _gen_horse_gallop(path):
    parts = []
    for _ in range(8):
        for _ in range(4):
            click_n = int(SAMPLE_RATE * 0.015)
            click = [_clamp(0.7 * math.exp(-30 * j / click_n) * random.uniform(-1, 1))
                     for j in range(click_n)]
            parts.append(click)
        parts.append(_silence(0.28))
    _write_wav(path, _concat(*parts))


def _gen_cat_meow(path):
    n = int(SAMPLE_RATE * 0.6)
    samples = []
    for i in range(n):
        t = i / n
        freq = 700 + 400 * math.sin(math.pi * t * 1.5)
        env = math.sin(math.pi * t)
        samples.append(_clamp(0.45 * env * math.sin(2 * math.pi * freq * i / SAMPLE_RATE)))
    _write_wav(path, _fade(samples, 10, 80))


def _gen_dog_bark(path):
    def bark():
        n = int(SAMPLE_RATE * 0.18)
        s = []
        for i in range(n):
            env = math.exp(-5 * i / n)
            s.append(_clamp(0.6 * env * random.uniform(-1, 1)))
        return _fade(s, 5, 30)

    _write_wav(path, _concat(bark(), _silence(0.1), bark()))


def _gen_rooster_crow(path):
    parts = []
    for freq_base, dur in [(600, 0.15), (900, 0.3), (700, 0.4)]:
        n = int(SAMPLE_RATE * dur)
        s = []
        for i in range(n):
            t = i / n
            freq = freq_base + 200 * t
            env = math.sin(math.pi * t)
            s.append(_clamp(0.5 * env * math.sin(2 * math.pi * freq * i / SAMPLE_RATE)))
        parts.append(_fade(s, 10, 40))
        parts.append(_silence(0.05))
    _write_wav(path, _concat(*parts))


def _gen_footsteps_grass(path):
    parts = []
    for _ in range(4):
        n = int(SAMPLE_RATE * 0.08)
        step = [_clamp(0.25 * random.uniform(-1, 1) * math.exp(-15 * i / n)) for i in range(n)]
        parts.extend([_fade(step, 2, 10), _silence(0.28)])
    _write_wav(path, _concat(*parts))


def _gen_footsteps_stone(path):
    parts = []
    for _ in range(4):
        n = int(SAMPLE_RATE * 0.06)
        step = [_clamp(0.4 * random.uniform(-1, 1) * math.exp(-25 * i / n)) for i in range(n)]
        parts.extend([_fade(step, 1, 8), _silence(0.30)])
    _write_wav(path, _concat(*parts))


def _gen_footsteps_snow(path):
    parts = []
    for _ in range(4):
        n = int(SAMPLE_RATE * 0.10)
        step = [_clamp(0.18 * random.uniform(-1, 1) * math.exp(-10 * i / n)) for i in range(n)]
        parts.extend([_fade(step, 3, 15), _silence(0.32)])
    _write_wav(path, _concat(*parts))


def _gen_door_open(path):
    sweep = _sine_sweep(80, 400, 0.5, 0.35)
    noise = _white_noise(0.5, 0.15)
    _write_wav(path, _fade(_mix(sweep, noise), 5, 80))


def _gen_door_creak(path):
    n = int(SAMPLE_RATE * 1.2)
    samples = []
    for i in range(n):
        t = i / n
        freq = 150 + 600 * t
        samples.append(_clamp(0.4 * math.sin(2 * math.pi * freq * i / SAMPLE_RATE)))
    _write_wav(path, _fade(samples, 10, 100))


def _gen_door_slam(path):
    impact_n = int(SAMPLE_RATE * 0.05)
    impact = [_clamp(0.9 * random.uniform(-1, 1) * math.exp(-40 * i / impact_n))
              for i in range(impact_n)]
    reverb_n = int(SAMPLE_RATE * 0.6)
    reverb = [_clamp(0.3 * random.uniform(-1, 1) * math.exp(-6 * i / reverb_n))
              for i in range(reverb_n)]
    _write_wav(path, _fade(_concat(impact, reverb), 2, 150))


def _gen_knock_door(path):
    def knock():
        n = int(SAMPLE_RATE * 0.07)
        return [_clamp(0.6 * random.uniform(-1, 1) * math.exp(-30 * i / n)) for i in range(n)]

    _write_wav(path, _concat(
        knock(), _silence(0.12),
        knock(), _silence(0.12),
        knock(),
    ))


def _gen_key_lock(path):
    click1 = _sine_sweep(800, 200, 0.1, 0.4)
    click2 = _sine_sweep(300, 900, 0.08, 0.35)
    _write_wav(path, _fade(_concat(click1, _silence(0.05), click2), 3, 40))


def _gen_magic_sparkle(path):
    parts = []
    for _ in range(8):
        freq = random.uniform(2000, 5000)
        n = int(SAMPLE_RATE * 0.05)
        s = [_clamp(0.3 * math.sin(2 * math.pi * freq * i / SAMPLE_RATE) * math.exp(-10 * i / n))
             for i in range(n)]
        parts.append(_fade(s, 2, 10))
        parts.append(_silence(random.uniform(0.02, 0.08)))
    _write_wav(path, _concat(*parts))


def _gen_magic_whoosh(path):
    sweep = _sine_sweep(100, 3000, 0.6, 0.5)
    noise = _white_noise(0.6, 0.2)
    _write_wav(path, _fade(_mix(sweep, noise), 10, 80))


def _gen_magic_bell(path):
    fundamentals = [1047, 2093, 3135]
    n = int(SAMPLE_RATE * 1.5)
    samples = [0] * n
    for freq in fundamentals:
        for i in range(n):
            t = i / n
            samples[i] += int(0.2 * math.exp(-3 * t) * math.sin(2 * math.pi * freq * i / SAMPLE_RATE) * MAX_AMP)
    samples = [max(-MAX_AMP, min(MAX_AMP, s)) for s in samples]
    _write_wav(path, _fade(samples, 5, 200))


def _gen_dragon_roar(path):
    n = int(SAMPLE_RATE * 2.0)
    samples = []
    for i in range(n):
        t = i / n
        freq = 80 + 60 * math.sin(math.pi * t * 3)
        env = math.sin(math.pi * t)
        noise = random.uniform(-0.3, 0.3)
        samples.append(_clamp((0.5 * env * math.sin(2 * math.pi * freq * i / SAMPLE_RATE)) + noise * env))
    _write_wav(path, _fade(samples, 20, 200))


def _gen_sword_draw(path):
    sweep = _sine_sweep(400, 3000, 0.4, 0.45)
    noise = _white_noise(0.4, 0.1)
    _write_wav(path, _fade(_mix(sweep, noise), 5, 50))


def _gen_sword_clash(path):
    n = int(SAMPLE_RATE * 0.8)
    samples = []
    for i in range(n):
        t = i / n
        env = math.exp(-4 * t)
        freq = 1200 + 800 * math.exp(-10 * t)
        samples.append(_clamp(0.6 * env * (
            math.sin(2 * math.pi * freq * i / SAMPLE_RATE) + 0.3 * random.uniform(-1, 1)
        )))
    _write_wav(path, _fade(samples, 2, 100))


def _gen_treasure_open(path):
    n = int(SAMPLE_RATE * 0.8)
    samples = []
    for i in range(n):
        t = i / n
        freq = 200 + 1000 * t
        samples.append(_clamp(0.35 * math.sin(2 * math.pi * freq * i / SAMPLE_RATE)))
    bells = _sine(2500, 0.3, 0.3)
    _write_wav(path, _fade(_concat(_fade(samples, 5, 20), bells), 5, 80))


def _gen_potion_bubble(path):
    parts = []
    for _ in range(6):
        freq = random.uniform(300, 700)
        dur = random.uniform(0.04, 0.10)
        n = int(SAMPLE_RATE * dur)
        s = [_clamp(0.3 * math.sin(2 * math.pi * freq * i / SAMPLE_RATE) * math.exp(-8 * i / n))
             for i in range(n)]
        parts.append(_fade(s, 2, 15))
        parts.append(_silence(random.uniform(0.1, 0.25)))
    _write_wav(path, _concat(*parts))


def _gen_crowd_cheer(path):
    n = int(SAMPLE_RATE * 2.5)
    samples = []
    for i in range(n):
        t = i / n
        env = math.sin(math.pi * t)
        samples.append(_clamp(0.4 * env * random.uniform(-1, 1)))
    _write_wav(path, _lpf(_fade(samples, 100, 200), 3000))


def _gen_clock_tick(path):
    def tick():
        n = int(SAMPLE_RATE * 0.02)
        return [_clamp(0.5 * math.exp(-40 * i / n) * (1 if i < n // 2 else -1))
                for i in range(n)]

    parts = []
    for _ in range(4):
        parts.extend([tick(), _silence(0.48)])
    _write_wav(path, _concat(*parts))


def _gen_bell_tower(path):
    fundamentals = [261, 522, 783, 1044]
    n = int(SAMPLE_RATE * 2.5)
    samples = [0] * n
    for k, freq in enumerate(fundamentals):
        amp = 0.3 / (k + 1)
        for i in range(n):
            t = i / n
            samples[i] += int(amp * math.exp(-1.5 * t) * math.sin(2 * math.pi * freq * i / SAMPLE_RATE) * MAX_AMP)
    samples = [max(-MAX_AMP, min(MAX_AMP, s)) for s in samples]
    _write_wav(path, _fade(samples, 10, 300))


def _gen_drip_cave(path):
    def drip():
        n = int(SAMPLE_RATE * 0.15)
        return [_clamp(0.4 * math.sin(2 * math.pi * 900 * i / SAMPLE_RATE) * math.exp(-20 * i / n))
                for i in range(n)]

    _write_wav(path, _concat(drip(), _silence(0.8), drip(), _silence(1.2), drip()))


def _gen_wooden_bridge(path):
    n = int(SAMPLE_RATE * 0.5)
    creak = []
    for i in range(n):
        t = i / n
        freq = 120 + 250 * math.sin(math.pi * t * 2)
        creak.append(_clamp(0.35 * math.sin(2 * math.pi * freq * i / SAMPLE_RATE) + 0.1 * random.uniform(-1, 1)))
    _write_wav(path, _fade(creak, 10, 80))


# =========================================================
# MAPPA ID → GENERATORE
# =========================================================

_GENERATORS = {
    "rain_light":      _gen_rain_light,
    "rain_heavy":      _gen_rain_heavy,
    "wind_gentle":     _gen_wind_gentle,
    "wind_storm":      _gen_wind_storm,
    "thunder":         _gen_thunder,
    "birds_morning":   _gen_birds_morning,
    "crickets_night":  _gen_crickets_night,
    "river_stream":    _gen_river_stream,
    "ocean_waves":     _gen_ocean_waves,
    "fire_crackling":  _gen_fire_crackling,
    "owl_hoot":        _gen_owl_hoot,
    "wolf_howl":       _gen_wolf_howl,
    "horse_gallop":    _gen_horse_gallop,
    "cat_meow":        _gen_cat_meow,
    "dog_bark":        _gen_dog_bark,
    "rooster_crow":    _gen_rooster_crow,
    "footsteps_grass": _gen_footsteps_grass,
    "footsteps_stone": _gen_footsteps_stone,
    "footsteps_snow":  _gen_footsteps_snow,
    "door_open":       _gen_door_open,
    "door_creak":      _gen_door_creak,
    "door_slam":       _gen_door_slam,
    "knock_door":      _gen_knock_door,
    "key_lock":        _gen_key_lock,
    "magic_sparkle":   _gen_magic_sparkle,
    "magic_whoosh":    _gen_magic_whoosh,
    "magic_bell":      _gen_magic_bell,
    "dragon_roar":     _gen_dragon_roar,
    "sword_draw":      _gen_sword_draw,
    "sword_clash":     _gen_sword_clash,
    "treasure_open":   _gen_treasure_open,
    "potion_bubble":   _gen_potion_bubble,
    "crowd_cheer":     _gen_crowd_cheer,
    "clock_tick":      _gen_clock_tick,
    "bell_tower":      _gen_bell_tower,
    "drip_cave":       _gen_drip_cave,
    "wooden_bridge":   _gen_wooden_bridge,
}


# =========================================================
# API PUBBLICA
# =========================================================

def generate_sfx(sfx_id: str, output_dir: str) -> str:
    """Genera un singolo SFX e lo salva in output_dir. Ritorna il path del WAV."""
    if sfx_id not in _GENERATORS:
        raise KeyError(f"SFX '{sfx_id}' non trovato nel catalogo")
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"{sfx_id}.wav")
    _GENERATORS[sfx_id](path)
    return path


def generate_all_sfx(output_dir: str) -> dict:
    """Genera tutti gli SFX. Ritorna {sfx_id: path | None}."""
    results = {}
    for sfx_id in _GENERATORS:
        try:
            results[sfx_id] = generate_sfx(sfx_id, output_dir)
        except Exception as e:
            try:
                from core.utils import log
                log(f"SFX generator [{sfx_id}]: {e}", "warning")
            except Exception:
                pass
            results[sfx_id] = None
    return results


def get_sfx_path(sfx_id: str, sfx_dir: str) -> str | None:
    """Ritorna il path del file WAV se esiste, altrimenti None."""
    path = os.path.join(sfx_dir, f"{sfx_id}.wav")
    return path if os.path.isfile(path) else None
