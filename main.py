"""
storyboard.py  –  portrait-A4 storyboard with working images
Requires:  python-dotenv, openai, pydub, reportlab   (and FFmpeg on PATH)
"""

import os, subprocess
from datetime import timedelta
from math import ceil
from typing import List

from dotenv import load_dotenv
from openai import OpenAI
from pydub import AudioSegment, silence
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4              # (595 × 842 pt)
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Image, Spacer
)

# ──────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ──────────────────────────────────────────────────────────────────────────
VIDEO_PATH      = "video.mov"
AUDIO_PATH      = "audio.mp3"
FRAME_FOLDER    = "frames"
PDF_OUTPUT      = "storyboard.pdf"

FRAME_RATE      = 1          # JPEG/sec
FRAMES_PER_ROW  = 5
SILENCE_THRESH  = -40        # dBFS
MIN_SILENCE_MS  = 500

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ──────────────────────────────────────────────────────────────────────────
# SHELL HELPER
# ──────────────────────────────────────────────────────────────────────────
def run(cmd: list[str]) -> None:
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode:
        print(res.stderr)
        raise RuntimeError(cmd)

# ──────────────────────────────────────────────────────────────────────────
# EXTRACTION
# ──────────────────────────────────────────────────────────────────────────
def extract_audio():
    run(["ffmpeg", "-y", "-i", VIDEO_PATH, "-vn", "-acodec", "libmp3lame", AUDIO_PATH])

def extract_frames():
    os.makedirs(FRAME_FOLDER, exist_ok=True)
    for f in os.listdir(FRAME_FOLDER):
        if f.endswith(".jpg"):
            os.remove(os.path.join(FRAME_FOLDER, f))
    run([
        "ffmpeg", "-y", "-i", VIDEO_PATH,
        "-vf", f"fps={FRAME_RATE}", "-vsync", "vfr", "-frame_pts", "1",
        os.path.join(FRAME_FOLDER, "frame_%06d.jpg")
    ])

# ──────────────────────────────────────────────────────────────────────────
# OPENAI WHISPER
# ──────────────────────────────────────────────────────────────────────────
def transcribe() -> List:
    with open(AUDIO_PATH, "rb") as f:
        r = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            response_format="verbose_json"
        )
    return r.segments                   # list of TranscriptionSegment objects

# ──────────────────────────────────────────────────────────────────────────
# SILENCE DETECTION
# ──────────────────────────────────────────────────────────────────────────
def silence_cues() -> List[str]:
    snd   = AudioSegment.from_file(AUDIO_PATH)
    rng   = silence.detect_silence(snd, MIN_SILENCE_MS, SILENCE_THRESH)
    rng   = [(s/1000, e/1000) for s, e in rng]
    total = int(len(snd)/1000) + 1
    out   = []
    for sec in range(total):
        out.append("Silence" if any(s<=sec<=e for s,e in rng) else "Normal")
    return out

# ──────────────────────────────────────────────────────────────────────────
# UTILITIES
# ──────────────────────────────────────────────────────────────────────────
def tc(sec: int) -> str:
    return str(timedelta(seconds=sec))[2:]      # “M:SS” / “MM:SS”

def speech_per_second(segments, seconds: int) -> List[str]:
    bucket = ["" for _ in range(seconds)]
    for seg in segments:
        idx = int(seg.start)
        if idx < seconds:
            bucket[idx] += seg.text.strip() + " "
    return [b.strip() for b in bucket]

# ──────────────────────────────────────────────────────────────────────────
# PDF
# ──────────────────────────────────────────────────────────────────────────
def build_pdf(frames, speech, cues):
    # comment-out “pagesize=A4” and uncomment next line for landscape
    doc = SimpleDocTemplate(PDF_OUTPUT, pagesize=A4,
    # doc = SimpleDocTemplate(PDF_OUTPUT, pagesize=landscape(A4),
                            leftMargin=25, rightMargin=25,
                            topMargin=25,  bottomMargin=25)
    elems = []

    usable_width = A4[0] - 50                 # portrait width minus margins
    img_w        = (usable_width - 40) / FRAMES_PER_ROW   # 40 pt label col
    img_h        = img_w * 0.56               # rough 16:9 thumbnail

    rows_total = ceil(len(frames) / FRAMES_PER_ROW)

    for r in range(rows_total):
        s, e     = r*FRAMES_PER_ROW, min((r+1)*FRAMES_PER_ROW, len(frames))
        tc_row   = ["TC:"] + [tc(i)             for i in range(s, e)]
        img_row  = [""]   + [Image(fp, img_w, img_h) for fp in frames[s:e]]
        dlg      = " ".join(speech[s:e]).strip()
        ger      = ", ".join(cues  [s:e]).strip()

        # pad rows to full width
        for row in (tc_row, img_row):
            row += [""] * (FRAMES_PER_ROW + 1 - len(row))

        data = [
            tc_row,
            img_row,
            ["Am:", dlg]      + [""]*(FRAMES_PER_ROW-1),
            ["Musik:"]        + [""]*FRAMES_PER_ROW,
            ["Geräusch:", ger]+ [""]*(FRAMES_PER_ROW-1),
        ]

        col_w = [40] + [img_w]*FRAMES_PER_ROW
        table = Table(data, colWidths=col_w)
        table.setStyle(TableStyle([
            ("GRID", (0,0), (-1,-1), 0.3, colors.black),
            ("VALIGN", (0,1), (-1,1), "MIDDLE"),
            ("ALIGN",  (1,0), (-1,0), "CENTER"),
            ("SPAN", (1,2), (-1,2)),
            ("SPAN", (1,3), (-1,3)),
            ("SPAN", (1,4), (-1,4)),
            ("FONTSIZE", (0,0), (-1,-1), 8),
        ]))
        elems.extend([table, Spacer(0, 6)])

    doc.build(elems)
    print("✅  Storyboard saved →", PDF_OUTPUT)

# ──────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("🎬  audio …");   extract_audio()
    print("🖼️   frames …");  extract_frames()

    frames = sorted(os.path.join(FRAME_FOLDER, f)
                    for f in os.listdir(FRAME_FOLDER) if f.endswith(".jpg"))
    secs   = len(frames)

    print("📝  whisper …");  segments = transcribe()
    speech = speech_per_second(segments, secs)

    print("🔊  silence …");  cues = silence_cues()

    print("📄  PDF …");      build_pdf(frames, speech, cues)