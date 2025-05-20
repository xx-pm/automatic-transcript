"""
main.py – macOS GUI wrapper for core.storyboard
Run: python main.py
"""

import sys
import subprocess
import threading
import tempfile
from pathlib import Path
from dotenv import load_dotenv
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, QPushButton, QFileDialog,
    QSpinBox, QHBoxLayout, QProgressBar, QMessageBox
)

# Load environment variables
load_dotenv()

class StoryboardApp(QWidget):
    # Define signals at class level
    notify_success = pyqtSignal(str)
    notify_error = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Storyboard Generator")
        self.resize(600, 400)

        self.video_path: Path | None = None
        self.pdf_path: Path | None = None
        self.output_path: Path | None = None
        self.thumb_path: Path | None = None

        layout = QVBoxLayout(self)

        # Video selection and thumbnail
        self.thumb_label = QLabel("⬇️  Drag & drop a video or press ‘Select’.")
        self.thumb_label.setAlignment(Qt.AlignCenter)
        self.thumb_label.setFixedHeight(200)
        self.thumb_label.setAcceptDrops(True)
        layout.addWidget(self.thumb_label)

        btn_layout = QHBoxLayout()
        self.select_btn = QPushButton("Select Video")
        self.select_btn.clicked.connect(self.select_video)
        btn_layout.addWidget(self.select_btn)

        self.clear_btn = QPushButton("X")
        self.clear_btn.setEnabled(False)
        self.clear_btn.clicked.connect(self.clear_video)
        btn_layout.addWidget(self.clear_btn)
        layout.addLayout(btn_layout)

        # Save As button
        self.saveas_btn = QPushButton("Save As…")
        self.saveas_btn.clicked.connect(self.choose_output)
        self.saveas_btn.setEnabled(False)
        layout.addWidget(self.saveas_btn)

        # Frame rate selector
        hbox = QHBoxLayout()
        hbox.addWidget(QLabel("Seconds between frames:"))
        self.spin_fps = QSpinBox()
        self.spin_fps.setRange(1, 30)
        self.spin_fps.setValue(1)
        hbox.addWidget(self.spin_fps)
        layout.addLayout(hbox)

        # Progress bar
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)

        # Action buttons
        self.generate_btn = QPushButton("Generate Storyboard PDF")
        self.generate_btn.clicked.connect(self.generate_storyboard)
        self.generate_btn.setEnabled(False)
        layout.addWidget(self.generate_btn)

        self.open_btn = QPushButton("Open PDF")
        self.open_btn.clicked.connect(self.open_pdf)
        self.open_btn.setEnabled(False)
        layout.addWidget(self.open_btn)

        # Info button
        self.info_btn = QPushButton("Info")
        self.info_btn.clicked.connect(self.show_info)
        layout.addWidget(self.info_btn)

        # Connect signals
        self.notify_success.connect(self._on_success)
        self.notify_error.connect(self._on_error)

    # ─── drag & drop events ─────────────────────────────────────────────
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        url = e.mimeData().urls()[0]
        self.set_video(Path(url.toLocalFile()))

    # ─── file selection ──────────────────────────────────────────
    def select_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select video", "", "Video (*.mp4 *.mov *.mkv)"
        )
        if path:
            self.set_video(Path(path))

    def clear_video(self):
        self.video_path = None
        self.thumb_path = None
        self.thumb_label.clear()
        self.thumb_label.setText("⬇️  Drag & drop a video or press ‘Select’.")
        self.clear_btn.setEnabled(False)
        self.saveas_btn.setEnabled(False)
        self.generate_btn.setEnabled(False)

    def choose_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save PDF As", self.video_path.with_suffix('.storyboard.pdf'), "PDF Files (*.pdf)"
        )
        if path:
            self.output_path = Path(path)
            self.open_btn.setEnabled(False)

    def set_video(self, path: Path):
        self.video_path = path
        # extract first frame as thumbnail
        tmp = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
        thumb = tmp.name
        tmp.close()
        cmd = [
            'ffmpeg', '-y', '-i', str(path), '-vf', 'select=eq(n\\,0)', '-q:v', '2', thumb
        ]
        subprocess.run(cmd, capture_output=True)
        pix = QPixmap(thumb).scaled(self.thumb_label.size(), Qt.KeepAspectRatio)
        self.thumb_label.setPixmap(pix)
        self.thumb_path = Path(thumb)
        self.clear_btn.setEnabled(True)
        self.saveas_btn.setEnabled(True)
        self.generate_btn.setEnabled(True)

    # ─── storyboard generation ──────────────────────────────────
    def generate_storyboard(self):
        if not self.video_path:
            return
        self.progress.show()
        self.generate_btn.setEnabled(False)
        self.open_btn.setEnabled(False)

        def task():
            try:
                fps = self.spin_fps.value()
                out_pdf = self.output_path or self.video_path.with_suffix('.storyboard.pdf')
                cmd = [
                    sys.executable, '-m', 'core.storyboard',
                    '--video', str(self.video_path),
                    '--fps', str(fps),
                    '--output', str(out_pdf),
                    '--debug'
                ]
                subprocess.check_call(cmd)
                self.pdf_path = out_pdf
                self.notify_success.emit(str(out_pdf))
            except subprocess.CalledProcessError as e:
                self.notify_error.emit(str(e))
            finally:
                # UI updates on main thread
                self.progress.hide()
                self.generate_btn.setEnabled(True)

        threading.Thread(target=task, daemon=True).start()

    # ─── open generated PDF ───────────────────────────────────
    def open_pdf(self):
        if self.pdf_path and self.pdf_path.exists():
            subprocess.run(['open', str(self.pdf_path)])

    # ─── info dialog ─────────────────────────────────────────
    def show_info(self):
        QMessageBox.information(
            self, 'About',
            'StoryboardGen\nby Philipp Michalik\n\nMIT License\nv0.0.1'
        )

    # ─── signal handlers ───────────────────────────────────────
    def _on_success(self, msg: str):
        QMessageBox.information(self, 'Success', f'Storyboard saved to:\n{msg}')
        self.open_btn.setEnabled(True)

    def _on_error(self, msg: str):
        QMessageBox.critical(self, 'Error', msg)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    win = StoryboardApp()
    win.show()
    sys.exit(app.exec_())
