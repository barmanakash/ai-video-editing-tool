"""Shared lock so heavy jobs (FFmpeg / OpenCV) run one at a time.

Keeps peak RAM and CPU low on an 8 GB machine.
"""
import threading

processing_lock = threading.Lock()
