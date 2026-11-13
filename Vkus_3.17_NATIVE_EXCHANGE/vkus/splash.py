import io
import queue
import subprocess
import threading
from pathlib import Path

import tkinter as tk

try:
    from PIL import Image, ImageTk
except Exception:
    Image = ImageTk = None


class SplashScreen:
    """Optional Vkus startup video. Missing/unsupported video never blocks startup."""
    VIDEO_FILENAME = 'vkus_start.mp4'
    DURATION_MS = 8000

    def __init__(self, root, video_path, on_done):
        self.root = root
        self.video_path = Path(video_path)
        self.on_done = on_done
        self.canvas = None
        self.photo = None
        self._queue = queue.Queue(maxsize=3)
        self._process = None
        self._stopped = False
        self._done_called = False
        self._thread = None
        self._started_at = None
        self._duration_ms = self.DURATION_MS
        self._ffmpeg = None

    def start(self):
        self.canvas = tk.Canvas(self.root, bg='#000000', highlightthickness=0, bd=0)
        self.canvas.pack(fill='both', expand=True)
        self.canvas.create_text(self.root.winfo_width() / 2, self.root.winfo_height() / 2,
                                text='VKUS', fill='#19d8ff', font=('TkDefaultFont', 30, 'bold'), tags='fallback')
        # Never silently fall back to the text screen just because ffmpeg is not in PATH.
        # Prefer the system ffmpeg; otherwise use the binary bundled by imageio-ffmpeg.
        if Image is None or not self.video_path.exists():
            self.root.after(self._duration_ms, self.finish)
            return
        try:
            import shutil
            self._ffmpeg = shutil.which('ffmpeg')
            if not self._ffmpeg:
                import imageio_ffmpeg
                self._ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception as exc:
            self._ffmpeg = None
            try:
                print(f'[VKUS SPLASH] ffmpeg недоступен: {exc}')
            except Exception:
                pass
            self.root.after(self._duration_ms, self.finish)
            return
        self._started_at = __import__('time').monotonic()
        self._thread = threading.Thread(target=self._decode, daemon=True)
        self._thread.start()
        self.root.after(15, self._poll)

    def _decode(self):
        try:
            cmd = [
                self._ffmpeg, '-hide_banner', '-loglevel', 'warning', '-re', '-i', str(self.video_path),
                '-vf', 'fps=24,scale=1280:-2:force_original_aspect_ratio=decrease',
                '-f', 'image2pipe', '-vcodec', 'mjpeg', '-q:v', '5', '-'
            ]
            self._process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            buf = b''
            while not self._stopped:
                chunk = self._process.stdout.read(65536)
                if not chunk:
                    break
                buf += chunk
                while True:
                    start = buf.find(b'\xff\xd8')
                    if start < 0:
                        buf = buf[-1:]
                        break
                    end = buf.find(b'\xff\xd9', start + 2)
                    if end < 0:
                        if start > 0:
                            buf = buf[start:]
                        break
                    frame = buf[start:end + 2]
                    buf = buf[end + 2:]
                    try:
                        image = Image.open(io.BytesIO(frame)).convert('RGB')
                        image.load()
                        try:
                            self._queue.put_nowait(image)
                        except queue.Full:
                            try:
                                self._queue.get_nowait()
                                self._queue.put_nowait(image)
                            except queue.Empty:
                                pass
                    except Exception:
                        continue
        except Exception as exc:
            try:
                print(f'[VKUS SPLASH] ошибка воспроизведения: {exc}')
            except Exception:
                pass
        finally:
            try:
                if self._process is not None:
                    self._process.stdout.close()
                    self._process.wait(timeout=1)
            except Exception:
                pass
            # The splash has a deliberate fixed 8-second presentation window.
            # Do not finish merely because ffmpeg reached EOF early; the last decoded
            # frame remains on screen until the 8-second window expires.

    def _poll(self):
        if self._stopped:
            return
        try:
            if self._started_at is not None and (__import__('time').monotonic() - self._started_at) * 1000 >= self._duration_ms:
                self.finish()
                return
            image = None
            while True:
                try:
                    image = self._queue.get_nowait()
                except queue.Empty:
                    break
            if image is not None and self.canvas is not None and self.canvas.winfo_exists():
                w = max(1, self.canvas.winfo_width())
                h = max(1, self.canvas.winfo_height())
                scale = min(w / image.width, h / image.height)
                size = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
                if size != image.size:
                    image = image.resize(size, Image.Resampling.LANCZOS)
                self.photo = ImageTk.PhotoImage(image)
                self.canvas.delete('all')
                self.canvas.create_image(w / 2, h / 2, image=self.photo, anchor='center')
        except Exception:
            pass
        self.root.after(40, self._poll)

    def finish(self):
        if self._done_called:
            return
        self._done_called = True
        self._stopped = True
        try:
            if self._process is not None and self._process.poll() is None:
                self._process.terminate()
        except Exception:
            pass
        try:
            if self.canvas is not None and self.canvas.winfo_exists():
                self.canvas.destroy()
        except Exception:
            pass
        self.on_done()

    def stop(self):
        self._stopped = True
        try:
            if self._process is not None and self._process.poll() is None:
                self._process.terminate()
        except Exception:
            pass
