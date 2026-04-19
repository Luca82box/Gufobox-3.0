"""
core/music_generator.py — Genera musiche di sottofondo sintetiche con Python puro.

Usa solo moduli standard: wave, struct, math, random.
Ogni brano è un file WAV 44.1 kHz 16-bit mono (loop di 25-42 secondi).
"""

import math
import os
import random
import struct
import wave

# =========================================================
# CATALOGO
# =========================================================

MUSIC_CATALOG = {
    "gentle_fantasy":      "Fantasia dolce (arpa + pad)",
    "adventure_epic":      "Avventura epica (percussioni + archi)",
    "mystery_dark":        "Mistero oscuro (pad grave + pizzicato)",
    "happy_playful":       "Allegro giocoso (xilofono + campanelle)",
    "night_lullaby":       "Ninna nanna notturna (carillon)",
    "forest_ambient":      "Foresta ambientale (pad + natura)",
    "castle_royal":        "Castello reale (fanfara + archi)",
    "underwater":          "Sott'acqua (pad acquatico + bolle)",
    "space_cosmic":        "Spazio cosmico (synth + pad)",
    "victory_celebration": "Vittoria e festa (fanfara allegra)",
}

SAMPLE_RATE = 44100
MAX_AMP = 32767

_PENTATONIC_MAJOR = [0, 2, 4, 7, 9]
_PENTATONIC_MINOR = [0, 3, 5, 7, 10]
_MAJOR_SCALE = [0, 2, 4, 5, 7, 9, 11]
_MINOR_SCALE = [0, 2, 3, 5, 7, 8, 10]


# =========================================================
# UTILITÀ
# =========================================================

def _note_freq(midi: int) -> float:
    return 440.0 * (2 ** ((midi - 69) / 12))


def _clamp(v: float) -> int:
    return max(-MAX_AMP, min(MAX_AMP, int(v * MAX_AMP)))


def _write_wav(path: str, samples: list) -> None:
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        data = struct.pack(f"<{len(samples)}h", *samples)
        wf.writeframes(data)


def _silence(dur_s: float) -> list:
    return [0] * int(SAMPLE_RATE * dur_s)


def _fade(samples: list, fi_ms: int = 50, fo_ms: int = 100) -> list:
    n = len(samples)
    fi = int(SAMPLE_RATE * fi_ms / 1000)
    fo = int(SAMPLE_RATE * fo_ms / 1000)
    result = list(samples)
    for i in range(min(fi, n)):
        result[i] = int(result[i] * i / fi)
    for i in range(min(fo, n)):
        idx = n - 1 - i
        result[idx] = int(result[idx] * i / fo)
    return result


def _mix_tracks(*tracks: list) -> list:
    n = max(len(t) for t in tracks)
    out = []
    for i in range(n):
        v = sum(t[i] if i < len(t) else 0 for t in tracks)
        out.append(max(-MAX_AMP, min(MAX_AMP, v)))
    return out


def _pad_note(freq: float, dur_s: float, amp: float = 0.3) -> list:
    n = int(SAMPLE_RATE * dur_s)
    attack = int(n * 0.15)
    release = int(n * 0.3)
    samples = []
    for i in range(n):
        if i < attack:
            env = i / attack
        elif i > n - release:
            env = (n - i) / release
        else:
            env = 1.0
        v = (math.sin(2 * math.pi * freq * i / SAMPLE_RATE) * 0.6 +
             math.sin(2 * math.pi * freq * 2 * i / SAMPLE_RATE) * 0.25 +
             math.sin(2 * math.pi * freq * 3 * i / SAMPLE_RATE) * 0.15)
        samples.append(_clamp(amp * env * v))
    return samples


def _pluck_note(freq: float, dur_s: float, amp: float = 0.4) -> list:
    n = int(SAMPLE_RATE * dur_s)
    decay = 4.0 / dur_s
    samples = []
    for i in range(n):
        env = math.exp(-decay * i / SAMPLE_RATE)
        samples.append(_clamp(amp * env * math.sin(2 * math.pi * freq * i / SAMPLE_RATE)))
    return samples


def _percussion(dur_s: float = 0.08, amp: float = 0.5, pitch_hz: float = 200.0) -> list:
    n = int(SAMPLE_RATE * dur_s)
    samples = []
    for i in range(n):
        env = math.exp(-20 * i / n)
        noise = random.uniform(-0.5, 0.5)
        tone = math.sin(2 * math.pi * pitch_hz * i / SAMPLE_RATE)
        samples.append(_clamp(amp * env * (0.6 * tone + 0.4 * noise)))
    return samples


def _carillon_note(freq: float, dur_s: float, amp: float = 0.35) -> list:
    n = int(SAMPLE_RATE * dur_s)
    samples = []
    for i in range(n):
        t = i / SAMPLE_RATE
        env = math.exp(-2.5 * t)
        v = (math.sin(2 * math.pi * freq * t) +
             0.5 * math.sin(2 * math.pi * freq * 2.76 * t) +
             0.25 * math.sin(2 * math.pi * freq * 5.4 * t))
        samples.append(_clamp(amp * env * v / 1.75))
    return samples


def _xylophone_note(freq: float, dur_s: float, amp: float = 0.4) -> list:
    n = int(SAMPLE_RATE * dur_s)
    samples = []
    for i in range(n):
        env = math.exp(-8 * i / n)
        samples.append(_clamp(amp * env * math.sin(2 * math.pi * freq * i / SAMPLE_RATE)))
    return samples


def _place_notes(note_events: list, total_samples: int) -> list:
    track = [0] * total_samples
    for offset, note_samples in note_events:
        for i, s in enumerate(note_samples):
            idx = offset + i
            if idx < total_samples:
                track[idx] = max(-MAX_AMP, min(MAX_AMP, track[idx] + s))
    return track


# =========================================================
# GENERATORI
# =========================================================

def _gen_gentle_fantasy(path):
    duration = 30.0
    total = int(SAMPLE_RATE * duration)
    bpm = 72
    beat = SAMPLE_RATE * 60 // bpm
    root = 60
    melody_notes = [_PENTATONIC_MAJOR[i % 5] for i in range(20)]
    mel_events = []
    for i, interval in enumerate(melody_notes):
        offset = int(i * beat * 0.75)
        freq = _note_freq(root + interval + 12)
        mel_events.append((offset, _pluck_note(freq, 0.4, 0.35)))
    mel_track = _place_notes(mel_events, total)
    chord_freqs = [_note_freq(root), _note_freq(root + 4), _note_freq(root + 7)]
    pad_track = [0] * total
    for chord_offset in range(0, total, int(beat * 4)):
        for freq in chord_freqs:
            note = _pad_note(freq / 2, 2.0, 0.15)
            for i, s in enumerate(note):
                if chord_offset + i < total:
                    pad_track[chord_offset + i] += s
    pad_track = [max(-MAX_AMP, min(MAX_AMP, s)) for s in pad_track]
    _write_wav(path, _fade(_mix_tracks(mel_track, pad_track), 200, 500))


def _gen_adventure_epic(path):
    duration = 32.0
    total = int(SAMPLE_RATE * duration)
    bpm = 120
    beat = SAMPLE_RATE * 60 // bpm
    perc_events = []
    for i in range(0, total, beat):
        perc_events.append((i, _percussion(0.06, 0.6, 180)))
        perc_events.append((i + beat // 2, _percussion(0.04, 0.35, 350)))
    perc_track = _place_notes(perc_events, total)
    root = 57
    scale = [_MINOR_SCALE[i % 7] for i in range(16)]
    mel_events = []
    for i, interval in enumerate(scale):
        offset = int(i * beat)
        freq = _note_freq(root + interval)
        mel_events.append((offset, _pad_note(freq, 0.7, 0.3)))
    mel_track = _place_notes(mel_events, total)
    _write_wav(path, _fade(_mix_tracks(perc_track, mel_track), 100, 400))


def _gen_mystery_dark(path):
    duration = 35.0
    total = int(SAMPLE_RATE * duration)
    bpm = 60
    beat = SAMPLE_RATE * 60 // bpm
    root = 45
    pad_track = [0] * total
    for i in range(0, total, int(beat * 4)):
        for interval in [0, 3, 7]:
            freq = _note_freq(root + interval)
            note = _pad_note(freq, 4.0, 0.18)
            for j, s in enumerate(note):
                if i + j < total:
                    pad_track[i + j] += s
    pad_track = [max(-MAX_AMP, min(MAX_AMP, s)) for s in pad_track]
    pluck_events = []
    for i in range(16):
        offset = int(i * beat * 1.2)
        freq = _note_freq(root + 12 + _PENTATONIC_MINOR[i % 5])
        pluck_events.append((offset, _pluck_note(freq, 0.5, 0.3)))
    pluck_track = _place_notes(pluck_events, total)
    _write_wav(path, _fade(_mix_tracks(pad_track, pluck_track), 300, 600))


def _gen_happy_playful(path):
    duration = 28.0
    total = int(SAMPLE_RATE * duration)
    bpm = 132
    beat = SAMPLE_RATE * 60 // bpm
    root = 60
    mel_events = []
    for i in range(28):
        offset = int(i * beat * 0.5)
        interval = _PENTATONIC_MAJOR[i % 5] + (12 if i % 7 < 3 else 0)
        freq = _note_freq(root + interval)
        mel_events.append((offset, _xylophone_note(freq, 0.25, 0.45)))
    mel_track = _place_notes(mel_events, total)
    bell_events = []
    for i in range(0, total, beat * 2):
        freq = _note_freq(root + 12 + _PENTATONIC_MAJOR[0])
        bell_events.append((i, _carillon_note(freq, 0.6, 0.3)))
    bell_track = _place_notes(bell_events, total)
    _write_wav(path, _fade(_mix_tracks(mel_track, bell_track), 100, 300))


def _gen_night_lullaby(path):
    duration = 40.0
    total = int(SAMPLE_RATE * duration)
    bpm = 56
    beat = SAMPLE_RATE * 60 // bpm
    root = 60
    pattern = [0, 4, 7, 4, 0, 4, 7, 9, 7, 4, 0, 2, 4, 2, 0]
    events = []
    for i, interval in enumerate(pattern * 3):
        offset = int(i * beat * 0.666)
        freq = _note_freq(root + interval)
        events.append((offset, _carillon_note(freq, 0.9, 0.4)))
    mel_track = _place_notes(events, total)
    pad_track = [0] * total
    for i in range(0, total, int(beat * 8)):
        freq = _note_freq(root - 12)
        note = _pad_note(freq, 5.5, 0.1)
        for j, s in enumerate(note):
            if i + j < total:
                pad_track[i + j] += s
    _write_wav(path, _fade(_mix_tracks(mel_track, pad_track), 500, 800))


def _gen_forest_ambient(path):
    duration = 40.0
    total = int(SAMPLE_RATE * duration)
    pad = []
    for i in range(total):
        lfo = 0.5 + 0.5 * math.sin(2 * math.pi * 0.2 * i / SAMPLE_RATE)
        noise = random.uniform(-0.05, 0.05)
        freq = 220
        pad.append(_clamp(0.15 * lfo * (math.sin(2 * math.pi * freq * i / SAMPLE_RATE) + noise)))
    root = 64
    events = []
    beat = int(SAMPLE_RATE * 0.9)
    for i in range(20):
        offset = int(i * beat * (1.2 + 0.3 * random.random()))
        freq = _note_freq(root + _PENTATONIC_MAJOR[i % 5] + (12 if random.random() > 0.7 else 0))
        events.append((offset, _pluck_note(freq, 0.6, 0.25)))
    mel_track = _place_notes(events, total)
    _write_wav(path, _fade(_mix_tracks(pad, mel_track), 500, 800))


def _gen_castle_royal(path):
    duration = 28.0
    total = int(SAMPLE_RATE * duration)
    bpm = 100
    beat = SAMPLE_RATE * 60 // bpm
    root = 67
    fanfare = [0, 4, 7, 12, 7, 4, 0, 4, 7, 12, 14, 12, 7]
    fan_events = []
    for i, interval in enumerate(fanfare):
        offset = int(i * beat * 0.5)
        freq = _note_freq(root + interval)
        fan_events.append((offset, _pad_note(freq, 0.6, 0.4)))
    fan_track = _place_notes(fan_events, total)
    perc_events = []
    for i in range(0, total, beat * 2):
        perc_events.append((i, _percussion(0.1, 0.7, 120)))
    perc_track = _place_notes(perc_events, total)
    _write_wav(path, _fade(_mix_tracks(fan_track, perc_track), 100, 300))


def _gen_underwater(path):
    duration = 38.0
    total = int(SAMPLE_RATE * duration)
    pad = []
    for i in range(total):
        lfo = 0.7 + 0.3 * math.sin(2 * math.pi * 0.15 * i / SAMPLE_RATE)
        freq = 220 + 20 * math.sin(2 * math.pi * 0.3 * i / SAMPLE_RATE)
        pad.append(_clamp(0.2 * lfo * math.sin(2 * math.pi * freq * i / SAMPLE_RATE)))
    bubble_events = []
    for _ in range(12):
        offset = random.randint(0, total - SAMPLE_RATE)
        freq = random.uniform(500, 1200)
        n = int(SAMPLE_RATE * 0.08)
        bubble = [_clamp(0.25 * math.sin(2 * math.pi * freq * j / SAMPLE_RATE) * math.exp(-15 * j / n))
                  for j in range(n)]
        bubble_events.append((offset, bubble))
    bubble_track = _place_notes(bubble_events, total)
    _write_wav(path, _fade(_mix_tracks(pad, bubble_track), 400, 600))


def _gen_space_cosmic(path):
    duration = 42.0
    total = int(SAMPLE_RATE * duration)
    pad = []
    for i in range(total):
        lfo1 = 0.5 + 0.5 * math.sin(2 * math.pi * 0.07 * i / SAMPLE_RATE)
        lfo2 = 0.5 + 0.5 * math.sin(2 * math.pi * 0.11 * i / SAMPLE_RATE)
        freq1 = 110 + 5 * math.sin(2 * math.pi * 0.05 * i / SAMPLE_RATE)
        freq2 = 165 + 8 * math.sin(2 * math.pi * 0.08 * i / SAMPLE_RATE)
        v = (0.15 * lfo1 * math.sin(2 * math.pi * freq1 * i / SAMPLE_RATE) +
             0.12 * lfo2 * math.sin(2 * math.pi * freq2 * i / SAMPLE_RATE))
        pad.append(_clamp(v))
    _write_wav(path, _fade(pad, 600, 800))


def _gen_victory_celebration(path):
    duration = 25.0
    total = int(SAMPLE_RATE * duration)
    bpm = 140
    beat = SAMPLE_RATE * 60 // bpm
    root = 60
    pattern = [0, 4, 7, 12, 7, 12, 14, 12, 9, 7, 4, 0]
    events = []
    for i, interval in enumerate(pattern * 2):
        offset = int(i * beat * 0.5)
        freq = _note_freq(root + interval)
        events.append((offset, _xylophone_note(freq, 0.35, 0.45)))
    mel_track = _place_notes(events, total)
    perc_events = []
    for i in range(0, total, beat):
        perc_events.append((i, _percussion(0.05, 0.55, 200)))
        if i + beat // 2 < total:
            perc_events.append((i + beat // 2, _percussion(0.04, 0.3, 400)))
    perc_track = _place_notes(perc_events, total)
    _write_wav(path, _fade(_mix_tracks(mel_track, perc_track), 50, 300))


# =========================================================
# MAPPA ID → GENERATORE
# =========================================================

_GENERATORS = {
    "gentle_fantasy":      _gen_gentle_fantasy,
    "adventure_epic":      _gen_adventure_epic,
    "mystery_dark":        _gen_mystery_dark,
    "happy_playful":       _gen_happy_playful,
    "night_lullaby":       _gen_night_lullaby,
    "forest_ambient":      _gen_forest_ambient,
    "castle_royal":        _gen_castle_royal,
    "underwater":          _gen_underwater,
    "space_cosmic":        _gen_space_cosmic,
    "victory_celebration": _gen_victory_celebration,
}


# =========================================================
# API PUBBLICA
# =========================================================

def generate_music(music_id: str, output_dir: str) -> str:
    """Genera un brano e lo salva in output_dir. Ritorna il path del WAV."""
    if music_id not in _GENERATORS:
        raise KeyError(f"Musica '{music_id}' non trovata nel catalogo")
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"{music_id}.wav")
    _GENERATORS[music_id](path)
    return path


def generate_all_music(output_dir: str) -> dict:
    """Genera tutte le musiche. Ritorna {music_id: path | None}."""
    results = {}
    for music_id in _GENERATORS:
        try:
            results[music_id] = generate_music(music_id, output_dir)
        except Exception as e:
            try:
                from core.utils import log
                log(f"Music generator [{music_id}]: {e}", "warning")
            except Exception:
                pass
            results[music_id] = None
    return results


def get_music_path(music_id: str, music_dir: str) -> str | None:
    """Ritorna il path del file WAV se esiste, altrimenti None."""
    path = os.path.join(music_dir, f"{music_id}.wav")
    return path if os.path.isfile(path) else None
