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
    sys.modules['sounddevice'] = MagicMock()
    sys.modules['pyaudio'] = MagicMock()
    sys.modules['speech_recognition'] = MagicMock()
