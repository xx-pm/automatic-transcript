"""
core/storyboard.py – generate a Word document with a transcript table

Usage:
  python -m core.storyboard --video VIDEO.mov --fps 1 --silence -40 \
      --min_silence 500 --output /path/to/storyboard.docx --debug
"""
import os, subprocess, logging, argparse
from datetime import timedelta
from typing import List
import shutil # For cleaning up frame_folder
import math

from dotenv import load_dotenv
from openai import OpenAI
from pydub import AudioSegment, silence
from docx import Document
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from PIL import Image as PILImage 
import io

# ────────────────────────── CLI ──────────────────────────
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate storyboard Word document")
    p.add_argument("--video", required=True, help="input video file")
    # FPS here means the interval in seconds between frames
    p.add_argument("--fps", type=float, default=1.0, help="Interval in seconds between frame captures (e.g., 1.0 for 1 frame per second, 2.0 for 1 frame every 2 seconds)")
    p.add_argument("--silence", type=int, default=-40, help="silence threshold (dBFS)")
    p.add_argument("--min_silence", type=int, default=500, help="min silence (ms)")
    p.add_argument(
        "--output", default="storyboard.docx", help="destination Word document (default: cwd/storyboard.docx)"
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
DOCX_OUTPUT = ARGS.output

# FRAME_RATE_INTERVAL is the number of seconds between each frame capture
FRAME_RATE_INTERVAL = ARGS.fps
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
        raise RuntimeError(" ".join(cmd))

def extract_audio():
    logging.info("🎬 Extracting audio...")
    run(["ffmpeg", "-y", "-i", VIDEO_PATH, "-vn", "-acodec", "libmp3lame", AUDIO_PATH])

def extract_frames():
    logging.info("🖼️  Extracting frames...")
    os.makedirs(FRAME_FOLDER, exist_ok=True)
    # Ensure old frames are removed if the folder exists
    for filename in os.listdir(FRAME_FOLDER):
        file_path = os.path.join(FRAME_FOLDER, filename)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
        except Exception as e:
            logging.error(f'Failed to delete {file_path}. Reason: {e}')

    # FRAME_RATE_INTERVAL is e.g. 1.0 for 1s, 2.0 for 2s interval
    # ffmpeg fps filter needs frames per second, so 1/FRAME_RATE_INTERVAL
    ffmpeg_fps = 1 / FRAME_RATE_INTERVAL
    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            VIDEO_PATH,
            "-vf",
            f"fps={ffmpeg_fps}",
            "-vsync",
            "vfr", # Variable frame rate, to match the fps filter output
            # "-frame_pts", "1", # This might cause issues with vfr, let ffmpeg decide timestamps for frames
            os.path.join(FRAME_FOLDER, "frame_%06d.jpg"),
        ]
    )

def transcribe() -> List:
    logging.info("📝 Transcribing audio...")
    with open(AUDIO_PATH, "rb") as f:
        r = client.audio.transcriptions.create(
            model="whisper-1", file=f, response_format="verbose_json"
        )
    logging.info(r.segments)
    # Ensure segments is a list, handle potential None or other types if API changes
    return r.segments if hasattr(r, 'segments') and isinstance(r.segments, list) else []

def silence_cues(audio_duration_seconds: int) -> List[str]:
    logging.info("🔊 Detecting silence...")
    try:
        snd = AudioSegment.from_file(AUDIO_PATH)
        # Ensure audio_duration_seconds matches snd duration if possible, or use snd duration
        # Using actual sound duration for silence detection range might be more robust
        actual_audio_duration_sec = len(snd) // 1000
        rng = silence.detect_silence(snd, MIN_SILENCE_MS, SILENCE_THRESH)
        rng = [(s / 1000, e / 1000) for s, e in rng] # convert ms to seconds
        
        # Use the longer of the two durations to avoid index out of bounds
        # but primarily rely on actual_audio_duration_sec for iteration range
        max_duration_for_cues = max(audio_duration_seconds, actual_audio_duration_sec)
        out = ["" for _ in range(max_duration_for_cues + 1)] # +1 for safety

        for sec_start, sec_end in rng:
            for sec_tick in range(int(sec_start), int(sec_end) + 1):
                if sec_tick < len(out):
                    out[sec_tick] = "(Silence)"
        return out
    except Exception as e:
        logging.error(f"Error detecting silence: {e}")
        return ["" for _ in range(audio_duration_seconds + 1)] # Return empty cues on error

def tc(seconds_float: float) -> str:
    """Convert seconds (float) to HH:MM:SS.mmm string."""
    td = timedelta(seconds=seconds_float)
    # Extract total seconds and microseconds
    total_seconds_int = int(td.total_seconds())
    microseconds = td.microseconds
    
    hours, remainder = divmod(total_seconds_int, 3600)
    minutes, seconds = divmod(remainder, 60)
    milliseconds = microseconds // 1000 # Convert microseconds to milliseconds
    
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{milliseconds:03d}"
    else:
        return f"{minutes:02d}:{seconds:02d}:{milliseconds:03d}"

def speech_per_second(segments: List, duration_seconds: int) -> List[str]:
    bucket = ["" for _ in range(duration_seconds + 1)] # +1 for safety
    for seg_obj in segments: # seg_obj is a TranscriptionSegment object
        start_time = seg_obj.start # Access attribute directly
        text = seg_obj.text         # Access attribute directly
        idx = int(start_time)
        if idx < len(bucket):
            bucket[idx] += text.strip() + " "
    return [b.strip() for b in bucket]

def get_video_duration(video_path: str) -> float:
    try:
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(res.stdout.strip())
    except Exception as e:
        logging.error(f"Could not get video duration: {e}")
        return 0.0 # Fallback

def build_word_table(frames: List[str], speech: List[str], cues: List[str], frame_interval: float, output_path: str):
    logging.info(f"📄 Building Word document: {output_path}")
    doc = Document()
    doc.add_heading('Video Transcript Storyboard', 0)
    # A4 paper width is approx 8.27 inches. Margins are usually 1 inch each side.
    # Usable width approx 6.27 inches.
    # For 1 label col + 5 frame cols: label_col_width + 5 * frame_col_width = usable_width

    FRAMES_PER_BLOCK = 5
    LABEL_COL_WIDTH = Inches(0.75)
    FRAME_COL_WIDTH = Inches(1.1) # (6.27 - 0.75) / 5 = 1.104

    num_total_frames = len(frames)
    num_blocks = math.ceil(num_total_frames / FRAMES_PER_BLOCK)

    for block_idx in range(num_blocks):
        start_frame_offset = block_idx * FRAMES_PER_BLOCK
        end_frame_offset = min((block_idx + 1) * FRAMES_PER_BLOCK, num_total_frames)
        
        current_block_frames_paths = frames[start_frame_offset:end_frame_offset]
        num_frames_in_this_block = len(current_block_frames_paths)

        if num_frames_in_this_block == 0:
            continue

        table = doc.add_table(rows=5, cols=1 + num_frames_in_this_block)
        table.style = 'Table Grid'

        # Set column widths
        table.columns[0].width = LABEL_COL_WIDTH
        for i in range(num_frames_in_this_block):
            table.columns[i + 1].width = FRAME_COL_WIDTH

        # --- Row 0: TC ---
        tc_label_cell = table.cell(0, 0)
        tc_label_cell.text = "TC:"
        tc_label_cell.paragraphs[0].runs[0].bold = True
        for i, frame_path in enumerate(current_block_frames_paths):
            actual_frame_index = start_frame_offset + i
            time_for_frame = actual_frame_index * frame_interval
            cell = table.cell(0, i + 1)
            cell.text = tc(time_for_frame)
            cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
            for run in cell.paragraphs[0].runs:
                run.font.size = Pt(8)

        # --- Row 1: Images ---
        img_label_cell = table.cell(1, 0)
        # img_label_cell.text = "" # No label text for image row per example
        for i, frame_path in enumerate(current_block_frames_paths):
            cell = table.cell(1, i + 1)
            try:
                p = cell.paragraphs[0]
                p.clear()
                run_img = p.add_run()
                with PILImage.open(frame_path) as img:
                    img_byte_arr = io.BytesIO()
                    # Resize image if it's too large for the cell, maintaining aspect ratio
                    # Max width for image could be FRAME_COL_WIDTH - small_margin
                    # Max height could be e.g. Inches(0.75)
                    # For simplicity, python-docx's width param handles scaling.
                    img.save(img_byte_arr, format='JPEG')
                    img_byte_arr.seek(0)
                    run_img.add_picture(img_byte_arr, width=FRAME_COL_WIDTH * 0.95) # Use slightly less than cell width
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            except FileNotFoundError:
                cell.text = "(Img NF)"
                logging.warning(f"Frame image not found: {frame_path}")
            except Exception as e:
                cell.text = "(Img Err)"
                logging.error(f"Error adding image {frame_path}. Exception: {str(e)}. Details: {repr(e)}")
            for run in cell.paragraphs[0].runs:
                 if not run.element.xpath('.//a:blip'): # Don't change font size for images
                    run.font.size = Pt(8)

        # --- Row 2: Transcript ("Am:") ---
        transcript_label_cell = table.cell(2, 0)
        transcript_label_cell.text = "Am:"
        transcript_label_cell.paragraphs[0].runs[0].bold = True
        block_speech_texts = []
        # Determine time range for this block's speech
        # Speech is per second, frames can be at sub-second or multi-second intervals
        min_sec_in_block = int(start_frame_offset * frame_interval)
        max_sec_in_block = int(math.ceil((end_frame_offset -1) * frame_interval))
        for sec in range(min_sec_in_block, max_sec_in_block + 1):
            if sec < len(speech) and speech[sec]:
                block_speech_texts.append(speech[sec])
        merged_speech_cell = table.cell(2, 1).merge(table.cell(2, num_frames_in_this_block))
        merged_speech_cell.text = " ".join(block_speech_texts).strip()
        merged_speech_cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.LEFT
        for run in merged_speech_cell.paragraphs[0].runs:
            run.font.size = Pt(8)

        # --- Row 3: Music ("Musik:") ---
        music_label_cell = table.cell(3, 0)
        music_label_cell.text = "Musik:"
        music_label_cell.paragraphs[0].runs[0].bold = True
        merged_music_cell = table.cell(3, 1).merge(table.cell(3, num_frames_in_this_block))
        merged_music_cell.text = "" # Placeholder for music
        merged_music_cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.LEFT
        for run in merged_music_cell.paragraphs[0].runs:
            run.font.size = Pt(8)

        # --- Row 4: Noise/Cues ("Geräusch:") ---
        noise_label_cell = table.cell(4, 0)
        noise_label_cell.text = "Geräusch:"
        noise_label_cell.paragraphs[0].runs[0].bold = True
        block_cue_texts = []
        for sec in range(min_sec_in_block, max_sec_in_block + 1):
            if sec < len(cues) and cues[sec]:
                block_cue_texts.append(cues[sec].replace("(Silence)", "Stille")) # Translate if needed
            elif sec < len(cues): # Add 'Normal' if no specific cue and not silence
                 block_cue_texts.append("Normal")
        # Consolidate consecutive 'Normal's
        consolidated_cues = []
        if block_cue_texts:
            consolidated_cues.append(block_cue_texts[0])
            for i in range(1, len(block_cue_texts)):
                if not (block_cue_texts[i] == "Normal" and consolidated_cues[-1] == "Normal"):
                    consolidated_cues.append(block_cue_texts[i])
        merged_noise_cell = table.cell(4, 1).merge(table.cell(4, num_frames_in_this_block))
        merged_noise_cell.text = ", ".join(consolidated_cues).strip()
        merged_noise_cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.LEFT
        for run in merged_noise_cell.paragraphs[0].runs:
            run.font.size = Pt(8)

        # Add a spacer paragraph between blocks if not the last block
        if block_idx < num_blocks - 1:
            doc.add_paragraph()

    doc.save(output_path)
    logging.info(f"✅ Word document saved → {output_path}")

def main():
    try:
        extract_audio()
        extract_frames()
        
        frames_list = sorted(
            os.path.join(FRAME_FOLDER, f)
            for f in os.listdir(FRAME_FOLDER)
            if f.endswith(".jpg") and os.path.isfile(os.path.join(FRAME_FOLDER, f))
        )

        if not frames_list:
            logging.warning("No frames were extracted. Check video path and ffmpeg installation.")
            # Attempt to get video duration anyway for transcription if audio was extracted
            video_duration_sec = get_video_duration(VIDEO_PATH)
            if video_duration_sec == 0 and os.path.exists(AUDIO_PATH):
                # Fallback: get duration from audio if video duration failed
                try:
                    audio_seg = AudioSegment.from_file(AUDIO_PATH)
                    video_duration_sec = len(audio_seg) / 1000.0
                except Exception as e:
                    logging.error(f"Could not determine audio duration: {e}")
                    video_duration_sec = 0 # Still 0 if fails
        else:
            # If frames were extracted, duration is based on frames and interval
            # However, transcription should use full audio duration
            video_duration_sec = get_video_duration(VIDEO_PATH)
            if video_duration_sec == 0 and os.path.exists(AUDIO_PATH):
                 try:
                    audio_seg = AudioSegment.from_file(AUDIO_PATH)
                    video_duration_sec = len(audio_seg) / 1000.0
                 except Exception as e:
                    logging.error(f"Could not determine audio duration: {e}")
                    video_duration_sec = (len(frames_list) * FRAME_RATE_INTERVAL) # Rough estimate if ffprobe fails

        segments = transcribe()
        speech_text_per_second = speech_per_second(segments, int(video_duration_sec))
        silence_data = silence_cues(int(video_duration_sec))
        
        build_word_table(frames_list, speech_text_per_second, silence_data, FRAME_RATE_INTERVAL, DOCX_OUTPUT)

    except Exception as e:
        logging.error(f"An error occurred during storyboard generation: {e}", exc_info=ARGS.debug)
    finally:
        # Clean up temporary files and folder
        logging.info("🧹 Cleaning up temporary files...")
        if os.path.exists(AUDIO_PATH):
            try:
                os.remove(AUDIO_PATH)
            except OSError as e:
                logging.warning(f"Could not remove temporary audio file {AUDIO_PATH}: {e}")
        if os.path.exists(FRAME_FOLDER):
            try:
                shutil.rmtree(FRAME_FOLDER)
            except OSError as e:
                logging.warning(f"Could not remove temporary frames folder {FRAME_FOLDER}: {e}")

if __name__ == "__main__":
    main()