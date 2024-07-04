import io
import time
import datetime as dt
from picamera import PiCamera
from threading import Thread, Event
from queue import Queue, Empty
import argparse
import RPi.GPIO as GPIO
import os
import signal
import sys
import logging
import json

# Set high process priority
os.nice(-20)

def load_config(config_file='config.json'):
    """
    Load configuration parameters from a JSON file.

    Args:
    - config_file (str): Path to the JSON configuration file.

    Returns:
    - dict: Loaded configuration parameters as a dictionary.
    """
    with open(config_file, 'r') as file:
        return json.load(file)

# Global variables loaded from configuration
config = load_config()

WIDTH = config['camera']['width']
HEIGHT = config['camera']['height']
FRAMERATE = config['camera']['framerate']
VIDEO_STABILIZATION = config['camera']['video_stabilization']
EXPOSURE_MODE = config['camera']['exposure_mode']
BRIGHTNESS = config['camera']['brightness']
CONTRAST = config['camera']['contrast']
SHARPNESS = config['camera']['sharpness']
SATURATION = config['camera']['saturation']
AWB_MODE = config['camera']['awb_mode']
AWB_GAINS = config['camera']['awb_gains']
BOUNCETIME = config['gpio']['bouncetime']
PIN_TTL = config['gpio']['pin_ttl']
CAM_ID = str(config['camera']['id'])

# Directory and file names based on current timestamp
current_time = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
base_directory = f"recording_{current_time}"
os.makedirs(base_directory, exist_ok=True)

base_filename = f"{base_directory}/cam{CAM_ID}_{current_time}"

VIDEO_FILE_NAME = f"{base_filename}_output.h264"
TIMESTAMP_FILE_NAME = f"{base_filename}_timestamp.csv"
TTL_FILE_NAME = f"{base_filename}_ttl.csv"

# Setup logging
logging.basicConfig(filename=f"{base_filename}.log", level=logging.DEBUG,
                    format='%(asctime)s %(levelname)s:%(message)s')

# Set Raspberry Pi board layout to BCM
GPIO.setmode(GPIO.BCM)
GPIO.setup(PIN_TTL, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
GPIO.add_event_detect(PIN_TTL, GPIO.BOTH, bouncetime=BOUNCETIME)

class VideoOutput(Thread):
    """
    Threaded video output handler.

    Args:
    - filename (str): Output filename for video.

    Attributes:
    - _output (io.BufferedWriter): Output stream for video data.
    - _event (threading.Event): Event object for thread synchronization.
    - _queue (queue.Queue): Queue for buffering video data.

    Methods:
    - write(buf): Write video data to the output stream.
    - run(): Thread execution loop to continuously write data from queue to output.
    - flush(): Flush the output stream and join the queue.
    - close(): Close the output stream and terminate the thread.
    """
    def __init__(self, filename):
        super(VideoOutput, self).__init__()
        self._output = io.open(filename, 'wb', buffering=0)
        self._event = Event()
        self._queue = Queue()
        self.start()

    def write(self, buf):
        """Write video data to the output stream."""
        self._queue.put(buf)
        return len(buf)

    def run(self):
        """Thread execution loop to continuously write data from queue to output."""
        while not self._event.is_set():
            try:
                buf = self._queue.get(timeout=0.1)
            except Empty:
                continue
            self._output.write(buf)
            self._queue.task_done()

    def flush(self):
        """Flush the output stream and join the queue."""
        self._queue.join()
        self._output.flush()

    def close(self):
        """Close the output stream and terminate the thread."""
        self._event.set()
        self.join()
        self._output.close()

class TimestampOutput:
    """
    Timestamp and TTL data handler.

    Args:
    - camera (picamera.PiCamera): PiCamera object for capturing video.
    - video_filename (str): Filename for video output.
    - timestamp_filename (str): Filename for timestamp data.
    - ttl_filename (str): Filename for TTL data.

    Attributes:
    - camera (picamera.PiCamera): PiCamera object for capturing video.
    - _video (VideoOutput): Video output handler.
    - _timestampFile (str): Filename for timestamp data.
    - _ttlFile (str): Filename for TTL data.
    - _timestamps (queue.Queue): Queue for buffering timestamp data.
    - _ttlTimestamps (queue.Queue): Queue for buffering TTL data.
    - _stop_event (threading.Event): Event object for thread synchronization.
    - _timestamp_thread (threading.Thread): Thread for writing timestamp data.
    - _ttl_thread (threading.Thread): Thread for writing TTL data.

    Methods:
    - ttlTimestampsWrite(input_pin): Record TTL timestamps based on input pin state.
    - write(buf): Write video data and capture timestamp data.
    - _write_timestamps(): Thread function to write timestamp data to file.
    - _write_ttl(): Thread function to write TTL data to file.
    - close(): Close video output and threads for data writing.
    """
    def __init__(self, camera, video_filename, timestamp_filename, ttl_filename):
        self.camera = camera
        self._video = VideoOutput(video_filename)
        self._timestampFile = timestamp_filename
        self._ttlFile = ttl_filename
        self._timestamps = Queue()
        self._ttlTimestamps = Queue()
        self._stop_event = Event()

        self._timestamp_thread = Thread(target=self._write_timestamps)
        self._ttl_thread = Thread(target=self._write_ttl)
        self._timestamp_thread.start()
        self._ttl_thread.start()

    def ttlTimestampsWrite(self, input_pin):
        """Record TTL timestamps based on input pin state."""
        inputState = GPIO.input(input_pin)
        timestamp = self.camera.frame.timestamp if self.camera.frame.timestamp else -1
        self._ttlTimestamps.put((inputState, self.camera.timestamp, timestamp, time.time(), time.perf_counter()))

    def write(self, buf):
        """Write video data and capture timestamp data."""
        if self.camera.frame.complete and self.camera.frame.timestamp is not None:
            self._timestamps.put((self.camera.timestamp, self.camera.frame.timestamp, time.time(), time.perf_counter()))
        return self._video.write(buf)

    def _write_timestamps(self):
        """Thread function to write timestamp data to file."""
        with io.open(self._timestampFile, 'w') as f:
            f.write('GPUTimestamp,CameraGPUTimestamp,time_time,clock_realtime\n')
            while not self._stop_event.is_set() or not self._timestamps.empty():
                try:
                    entry = self._timestamps.get(timeout=0.1)
                    f.write('%f,%f,%f,%f\n' % entry)
                    self._timestamps.task_done()
                except Empty:
                    continue

    def _write_ttl(self):
        """Thread function to write TTL data to file."""
        with io.open(self._ttlFile, 'w') as f:
            f.write('InputState,GPUTimestamp,CameraGPUTimestamp,time_time,clock_realtime\n')
            while not self._stop_event.is_set() or not self._ttlTimestamps.empty():
                try:
                    entry = self._ttlTimestamps.get(timeout=0.1)
                    f.write('%f,%f,%f,%f,%f\n' % entry)
                    self._ttlTimestamps.task_done()
                except Empty:
                    continue

    def close(self):
        """Close video output and threads for data writing."""
        self._video.close()
        self._stop_event.set()
        self._timestamp_thread.join()
        self._ttl_thread.join()

def signal_handler(sig, frame):
    """Signal handler for SIGINT and SIGTERM signals."""
    logging.info('Signal received: Closing Output File')
    output.close()
    GPIO.cleanup()
    sys.exit(0)

def parse_args():
    """
    Parse command line arguments.

    Returns:
    - argparse.Namespace: Parsed arguments.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("-hr", "--hours", type=int, default=0, help="number of hours to record")
    parser.add_argument("-m", "--minutes", type=int, default=0, help="number of minutes to record")
    parser.add_argument("-s", "--seconds", type=int, default=0, help="number of seconds to record")
    return parser.parse_args()

def main():
    """Main function to control the video recording process."""
    args = parse_args()
    runningTimeHours = args.hours if args.hours else 0
    runningTimeMinutes = args.minutes if args.minutes else 0
    runningTimeSeconds = args.seconds if args.seconds else 0
    totalRunningTime = runningTimeHours * 3600 + runningTimeMinutes * 60 + runningTimeSeconds

    with PiCamera(resolution=(WIDTH, HEIGHT), framerate=FRAMERATE) as camera:
        camera.brightness = BRIGHTNESS
        camera.contrast = CONTRAST
        camera.sharpness = SHARPNESS
        camera.saturation = SATURATION
        camera.video_stabilization = VIDEO_STABILIZATION
        camera.exposure_mode = EXPOSURE_MODE
        camera.awb_mode = AWB_MODE
        camera.awb_gains = AWB_GAINS

        time.sleep(2)  # Allow camera to adjust parameters

        camera.exposure_mode = 'off'  # Disable automatic exposure

        output = TimestampOutput(camera, VIDEO_FILE_NAME, TIMESTAMP_FILE_NAME, TTL_FILE_NAME)

        GPIO.add_event_callback(PIN_TTL, output.ttlTimestampsWrite)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        try:
            camera.start_preview()
            logging.info('Starting Recording')
            camera.start_recording(output, format='h264')
            logging.info('Started Recording')
            camera.wait_recording(totalRunningTime)
            camera.stop_recording()
            camera.stop_preview()
            logging.info('Recording Stopped')
        except KeyboardInterrupt:
            logging.info('Keyboard Interrupt: Closing Output File')
        except Exception as e:
            logging.error(f'Exception occurred: {str(e)}')
        finally:
            output.close()
            logging.info('Output File Closed')

if __name__ == "__main__":
    main()
