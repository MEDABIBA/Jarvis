from unittest.mock import Mock

from prompt_toolkit.keys import Keys

from jarvis.core.state import state
from jarvis.ui.keybindings import make_bindings


def press(bindings, key):
    bindings.get_bindings_for_keys((key,))[0].handler(None)


def test_muting_stops_current_audio(monkeypatch):
    monkeypatch.setattr(state, "tts_enabled", True)
    stop = Mock()
    bindings = make_bindings(Mock(), stop_speech=stop)
    press(bindings, Keys.F3)
    assert not state.tts_enabled
    stop.assert_called_once()
    press(bindings, Keys.F3)
    assert state.tts_enabled
    stop.assert_called_once()


def test_cancel_hotkey_calls_turn_callback():
    cancel = Mock()
    bindings = make_bindings(Mock(), cancel_turn=cancel)
    press(bindings, Keys.F4)
    cancel.assert_called_once()


def test_optional_callbacks_preserve_old_binding_signature():
    bindings = make_bindings(Mock())
    press(bindings, Keys.F4)
