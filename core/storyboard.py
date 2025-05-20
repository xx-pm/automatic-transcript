"""
core/storyboard.py – generate an A4 portrait storyboard PDF

Usage:
  python -m core.storyboard --video VIDEO.mov --fps 1 --silence -40 \
      --min_silence 500 --output /path/to/storyboard.pdf --debug
"""
import os, subprocess, logging, argparse
from datetime import timedelta
from math import ceil
from typing import List

from dotenv import load_dotenv
from openai import OpenAI
from pydub import AudioSegment, silence
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Image, Spacer

# ────────────────────────── CLI ──────────────────────────
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate storyboard PDF")
    p.add_argument("--video", required=True, help="input video file")
    p.add_argument("--fps", type=int, default=1, help="frames per second")
    p.add_argument("--silence", type=int, default=-40, help="silence threshold (dBFS)")
    p.add_argument("--min_silence", type=int, default=500, help="min silence (ms)")
    p.add_argument(
        "--output", default="storyboard.pdf", help="destination PDF (default: cwd)"
    )
    p.add_argument("--debug", action="store_true", help="verbose logging")
    return p.parse_args()

ARGS = parse_args()
logging.basicConfig(
    level=logging.DEBUG if ARGS.debug else logging.INFO,
    format="%(levelname)s | %(message)s",
)

VIDEO_PATH = ARGS.video
AUDIO_PATH = "audio_temp.mp3"
FRAME_FOLDER = "frames_temp"
PDF_OUTPUT = ARGS.output

FRAME_RATE = ARGS.fps
FRAMES_PER_ROW = 5
SILENCE_THRESH = ARGS.silence
MIN_SILENCE_MS = ARGS.min_silence

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ─────────────────────── helpers/steps ───────────────────
def run(cmd: list[str]) -> None:
    logging.debug(" ".join(cmd))
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode:
        logging.error(res.stderr)
        raise RuntimeError(cmd)

def extract_audio():
    run(["ffmpeg", "-y", "-i", VIDEO_PATH, "-vn", "-acodec", "libmp3lame", AUDIO_PATH])

def extract_frames():
    os.makedirs(FRAME_FOLDER, exist_ok=True)
    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            VIDEO_PATH,
            "-vf",
            f"fps={FRAME_RATE}",
            "-vsync",
            "vfr",
            "-frame_pts",
            "1",
            os.path.join(FRAME_FOLDER, "frame_%06d.jpg"),
        ]
    )

def transcribe() -> List:
    with open(AUDIO_PATH, "rb") as f:
        r = client.audio.transcriptions.create(
            model="whisper-1", file=f, response_format="verbose_json"
        )
    return r.segments

def silence_cues() -> List[str]:
    snd = AudioSegment.from_file(AUDIO_PATH)
    rng = silence.detect_silence(snd, MIN_SILENCE_MS, SILENCE_THRESH)
    rng = [(s / 1000, e / 1000) for s, e in rng]
    total = int(len(snd) / 1000) + 1
    out = ["Silence" if any(s <= sec <= e for s, e in rng) else "Normal" for sec in range(total)]
    return out

def tc(sec: int) -> str:
    return str(timedelta(seconds=sec))[2:]

def speech_per_second(segments, seconds: int) -> List[str]:
    bucket = ["" for _ in range(seconds)]
    for seg in segments:
        idx = int(seg.start)
        if idx < seconds:
            bucket[idx] += seg.text.strip() + " "
    return [b.strip() for b in bucket]

def build_pdf(frames, speech, cues):
    doc = SimpleDocTemplate(
        PDF_OUTPUT,
        pagesize=A4,
        leftMargin=25,
        rightMargin=25,
        topMargin=25,
        bottomMargin=25,
    )
    elems = []
    usable_width = A4[0] - 50
    img_w = (usable_width - 40) / FRAMES_PER_ROW
    img_h = img_w * 0.56
    rows_total = ceil(len(frames) / FRAMES_PER_ROW)

    for r in range(rows_total):
        s, e = r * FRAMES_PER_ROW, min((r + 1) * FRAMES_PER_ROW, len(frames))
        tc_row = ["TC:"] + [tc(i) for i in range(s, e)]
        img_row = [""] + [Image(fp, img_w, img_h) for fp in frames[s:e]]
        dlg = " ".join(speech[s:e]).strip()
        ger = ", ".join(cues[s:e]).strip()
        for row in (tc_row, img_row):
            row += [""] * (FRAMES_PER_ROW + 1 - len(row))
        data = [
            tc_row,
            img_row,
            ["Speech:", dlg] + [""] * (FRAMES_PER_ROW - 1),
            ["Music:"] + [""] * FRAMES_PER_ROW,
            ["Noise:", ger] + [""] * (FRAMES_PER_ROW - 1),
        ]
        col_w = [40] + [img_w] * FRAMES_PER_ROW
        table = Table(data, colWidths=col_w)
        table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.black),
                    ("VALIGN", (0, 1), (-1, 1), "MIDDLE"),
                    ("ALIGN", (1, 0), (-1, 0), "CENTER"),
                    ("SPAN", (1, 2), (-1, 2)),
                    ("SPAN", (1, 3), (-1, 3)),
                    ("SPAN", (1, 4), (-1, 4)),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                ]
            )
        )
        elems.extend([table, Spacer(0, 6)])

    doc.build(elems)
    logging.info("✅  Storyboard saved → %s", PDF_OUTPUT)

def main():
    logging.info("🎬  extract audio"); extract_audio()
    logging.info("🖼️   extract frames"); extract_frames()
    frames = sorted(
        os.path.join(FRAME_FOLDER, f)
        for f in os.listdir(FRAME_FOLDER)
        if f.endswith(".jpg")
    )
    secs = len(frames)
    logging.info("📝  transcribe"); segments = transcribe()
    speech = speech_per_second(segments, secs)
    logging.info("🔊  detect silence"); cues = silence_cues()
    logging.info("📄  build PDF"); build_pdf(frames, speech, cues)

if __name__ == "__main__":
    main()