"""
main.py – Command-line interface for core.storyboard
Run: python main.py --video <path_to_video> --fps <frames_per_second> --output <output_path.docx>
"""

import sys
import subprocess
import argparse
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def generate_storyboard_cli(video_path: Path, fps: int, output_path: Path, debug: bool = False):
    """Calls the core.storyboard script to generate the storyboard."""
    if not video_path.exists():
        print(f"Error: Video file not found at {video_path}")
        return

    cmd = [
        sys.executable, '-m', 'core.storyboard',
        '--video', str(video_path),
        '--fps', str(fps),
        '--output', str(output_path)
    ]
    if debug:
        cmd.append('--debug')

    try:
        print(f"Generating storyboard for {video_path}...")
        print(f"Output will be saved to {output_path}")
        subprocess.check_call(cmd)
        print("Storyboard generated successfully!")
        # Attempt to open the generated file (optional)
        try:
            if sys.platform == "win32":
                subprocess.run(['start', str(output_path)], shell=True, check=False)
            elif sys.platform == "darwin": # macOS
                subprocess.run(['open', str(output_path)], check=False)
            else: # linux variants
                subprocess.run(['xdg-open', str(output_path)], check=False)
        except Exception as e:
            print(f"Could not automatically open the file: {e}")

    except subprocess.CalledProcessError as e:
        print(f"Error generating storyboard: {e}")
    except FileNotFoundError:
        print("Error: python-docx or other dependency for core.storyboard might be missing.")
        print("Please ensure all requirements from requirements.txt are installed.")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Generate a storyboard (transcript table in Word format) from a video file.")
    parser.add_argument("--video", type=Path, required=True, help="Path to the video file.")
    parser.add_argument(
        "--fps", 
        type=float, 
        default=1.0, 
        help="Interval in seconds between frame captures (e.g., 1.0 for 1 frame per second, 0.5 for 2 frames per second, 2.0 for 1 frame every 2 seconds)."
    )
    parser.add_argument("--output", type=Path, help="Path to save the output Word document. Defaults to <video_name>.storyboard.docx")
    parser.add_argument("--debug", action='store_true', help="Enable debug mode for core.storyboard.")

    args = parser.parse_args()

    output_file = args.output
    if not output_file:
        output_file = args.video.with_name(f"{args.video.stem}_storyboard.docx")
    else:
        # Ensure the output has a .docx extension if a custom path is provided
        if output_file.suffix.lower() != '.docx':
            output_file = output_file.with_suffix('.docx')

    generate_storyboard_cli(args.video, args.fps, output_file, args.debug)
