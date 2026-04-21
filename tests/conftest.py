import pytest
from unittest.mock import MagicMock
import sys

@pytest.fixture(scope="session", autouse=True)
def mock_audio_streams():
    """
    Globally mocks sounddevice and speech recognition threads to prevent 
    C++ coreaudio/portaudio/sounddevice Segmentation Faults when pytest exits.
    """
    # Fake sounddevice module entirely for testing so it never accesses real mic
    import numpy as np
    sd_mock = MagicMock()
    # Mock stream.read() to return a tuple to prevent unpack errors in background threads
    sd_mock.InputStream.return_value.__enter__.return_value.read.return_value = (np.zeros((2048, 1), dtype=np.int16), False)
    sys.modules['sounddevice'] = sd_mock
    sys.modules['pyaudio'] = MagicMock()
    sys.modules['speech_recognition'] = MagicMock()
