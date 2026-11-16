"""Sound under the narration, made by code (no licensed music): a dark pad that changes chord every few bars, a
low heartbeat drum, wind, and a whoosh at every cut with a deep impact on the hard ones.

Two stereo 48 kHz WAV files: `music` (pad, drum, wind; the render ducks it under the voice) and `hits` (whooshes and
impacts; not ducked, so a cut is felt even mid-sentence).
"""
import math
import wave

import numpy as np

RATE = 48000
# D minor → B flat → G minor → A (the classic dark lament), low enough to sit under a voice
CHORDS = [
    (73.42, 110.00, 146.83, 174.61, 220.00),
    (58.27, 116.54, 146.83, 174.61, 233.08),
    (49.00, 98.00, 146.83, 196.00, 233.08),
    (55.00, 110.00, 138.59, 164.81, 220.00),
]
CHORD_SECONDS = 8.0
BEAT = 60 / 76            # heartbeat drum, two hits a bar


def band(signal, low, high, rate=RATE):
    """Band-pass by FFT: keeps low–high Hz with soft edges."""
    spectrum = np.fft.rfft(signal)
    freqs = np.fft.rfftfreq(len(signal), 1 / rate)
    gain = 1 / (1 + (low / np.maximum(freqs, 1)) ** 4) / (1 + (freqs / high) ** 4)
    return np.fft.irfft(spectrum * gain, len(signal))


def rms(signal):
    return float(np.sqrt(np.mean(signal ** 2))) or 1.0


def pad(seconds, rng):
    count = int(seconds * RATE)
    out = np.zeros(count)
    start = -1.5
    index = 0
    while start < seconds:
        chord = CHORDS[index % len(CHORDS)]
        # each chord fades in over 3 s and out over 3 s, so neighbours overlap; only its own stretch is computed
        first, last = max(0, int(start * RATE)), min(count, int((start + CHORD_SECONDS + 3) * RATE))
        if last > first:
            t = np.arange(first, last) / RATE
            window = np.clip((t - start) / 3, 0, 1) * np.clip((start + CHORD_SECONDS + 3 - t) / 3, 0, 1)
            for note in chord:
                phase = rng.uniform(0, 2 * math.pi)
                tone = sum(np.sin(2 * math.pi * note * k * (1 + detune) * t + phase * k) / k ** 1.6
                           for k in range(1, 6) for detune in (-0.0015, 0.0015))
                out[first:last] += window * tone
        start += CHORD_SECONDS
        index += 1
    t = np.arange(count) / RATE
    swell = 0.75 + 0.25 * np.sin(2 * math.pi * t / 23 + 1.1)
    out *= swell
    return out / rms(out)


def drum(seconds):
    count = int(seconds * RATE)
    out = np.zeros(count)
    length = int(0.5 * RATE)
    t = np.arange(length) / RATE
    freq = 52 + 70 * np.exp(-t / 0.05)
    body = np.sin(2 * math.pi * np.cumsum(freq) / RATE) * np.exp(-t / 0.16)
    body += 0.35 * np.sin(4 * math.pi * np.cumsum(freq) / RATE) * np.exp(-t / 0.08)   # audible on a phone
    beat = 2.0                                                                            # after the title
    while beat < seconds - 0.5:
        for offset, level in ((0, 1.0), (0.28, 0.6)):                                      # lub-dub
            at = int((beat + offset) * RATE)
            piece = body[: count - at] * level
            out[at:at + len(piece)] += piece
        beat += 2 * BEAT
    return out / max(1e-9, np.abs(out).max())


def wind(seconds, rng):
    count = int(seconds * RATE)
    t = np.arange(count) / RATE
    noise = band(rng.standard_normal(count), 180, 900)
    noise *= 0.6 + 0.4 * np.sin(2 * math.pi * t / 11 + 0.7) * np.sin(2 * math.pi * t / 4.3)
    return noise / rms(noise)


def whoosh(rng, seconds=0.7, peak=0.5):
    count = int(seconds * RATE)
    t = np.arange(count) / RATE
    noise = band(rng.standard_normal(count), 500, 6000)
    rise = np.clip(t / peak, 0, 1) ** 3
    fall = np.exp(-np.clip(t - peak, 0, None) / 0.09)
    sweep = band(rng.standard_normal(count), 1500, 9000) * np.clip((t - peak * 0.6) / (peak * 0.4), 0, 1) ** 2
    out = (noise + 0.5 * sweep) * rise * fall
    return out / np.abs(out).max()


def impact(seconds=1.6):
    t = np.arange(int(seconds * RATE)) / RATE
    freq = 38 + 80 * np.exp(-t / 0.07)
    phase = 2 * math.pi * np.cumsum(freq) / RATE
    out = np.sin(phase) * np.exp(-t / 0.55) + 0.45 * np.sin(2 * phase) * np.exp(-t / 0.25)
    out += 0.3 * np.random.default_rng(7).standard_normal(len(t)) * np.exp(-t / 0.015)
    return out / np.abs(out).max()


def write_wav(path, mono, level):
    """Stereo 16-bit WAV, peak at `level` (0–1), a slight delay on the right channel for width."""
    mono = mono / max(1e-9, np.abs(mono).max()) * level
    right = np.concatenate([np.zeros(int(0.012 * RATE)), mono[: len(mono) - int(0.012 * RATE)]])
    frames = (np.stack([mono, right], axis=1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(frames.tobytes())


def soundtrack(seconds, cuts, music_path, hits_path, seed=40000):
    """cuts: [(time in seconds, strong)] of every cut after the first shot."""
    rng = np.random.default_rng(seed)
    seconds = max(1.0, seconds)
    music = 0.6 * pad(seconds, rng) + 0.9 * drum(seconds) + 0.25 * wind(seconds, rng)
    write_wav(music_path, music, 0.5)
    count = int(seconds * RATE)
    hits = np.zeros(count)
    swoosh, boom = whoosh(rng), impact()
    for at, strong in cuts:
        start = int((at - 0.5) * RATE)               # the whoosh peaks on the cut
        for sound, level, offset in ((swoosh, 0.55, start), *(((boom, 1.0, int(at * RATE)),) if strong else ())):
            first = max(0, offset)
            piece = sound[first - offset: first - offset + count - first] * level
            hits[first:first + len(piece)] += piece
    write_wav(hits_path, hits if hits.any() else np.zeros(count) + 1e-9, 0.6)
