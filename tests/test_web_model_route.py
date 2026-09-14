from pathlib import Path
from types import SimpleNamespace

import pytest

from empy_studio.drivers import CodexDriver
from empy_studio.drivers.omniroute import OmniRouteCodexDriver
from empy_studio.web_desktop import GuidedState, RequestHandler


def test_route_persists_without_changing_fresh_start_or_economy(tmp_path: Path) -> None:
    state = GuidedState(tmp_path)
    assert type(state.driver) is CodexDriver
    state.set_model_route({'mode': 'omniroute', 'model': 'oc/big-pickle'})
    restored = GuidedState(tmp_path, restore_session=False)
    assert isinstance(restored.driver, OmniRouteCodexDriver)
    assert restored.model_route.model == 'oc/big-pickle'
    assert restored.phase == 'project'
    assert restored.budget_preset == 'economy'
    assert restored.active_task_id is None
    restored.set_model_route({'mode': 'direct'})
    assert type(restored.driver) is CodexDriver


def test_invalid_routes_do_not_replace_configuration(tmp_path: Path) -> None:
    state = GuidedState(tmp_path)
    for model in ['auto', 'auto/coding', 'openai/gpt-5', 'oc/unknown']:
        with pytest.raises(ValueError):
            state.set_model_route({'mode': 'omniroute', 'model': model})
        assert state.model_route.mode == 'direct'
        assert state.store.get_setting('model-route.v1') is None


def test_paid_route_requires_explicit_opt_in(tmp_path: Path) -> None:
    state = GuidedState(tmp_path)
    with pytest.raises(ValueError, match='free/local'):
        state.set_model_route({'mode': 'omniroute', 'model': 'gpt-5.6-mini'})
    assert state.model_route.mode == 'direct'
    state.set_model_route({'mode': 'omniroute', 'model': 'gpt-5.6-mini', 'allow_paid': True})
    assert state.model_route.allow_paid is True


def test_route_locked_during_run_and_recovery_gap(tmp_path: Path) -> None:
    state = GuidedState(tmp_path)
    state.running = True
    with pytest.raises(RuntimeError):
        state.set_model_route({'mode': 'omniroute'})
    state.running = False
    state.recovery.begin()
    state.recovery.status = 'ready'
    with pytest.raises(RuntimeError):
        state.set_model_route({'mode': 'omniroute'})
    state.recovery.stop('cancelled')
    state.set_model_route({'mode': 'omniroute'})


def test_startup_reservation_prevents_route_switch_and_unlocks_on_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = GuidedState(tmp_path)
    state.set_model_route({'mode': 'omniroute'})
    def preflight():
        with pytest.raises(RuntimeError):
            state.set_model_route({'mode': 'direct'})
        assert state.model_route.mode == 'omniroute'
        raise RuntimeError('Gateway offline')
    monkeypatch.setattr(state, '_start_run', preflight)
    with pytest.raises(RuntimeError, match='Gateway offline'):
        state.start_run()
    assert not state._starting_run
    state.set_model_route({'mode': 'direct'})


def test_route_endpoint_accepts_key_name_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = GuidedState(tmp_path)
    monkeypatch.setattr(GuidedState, 'public', lambda self: {'model_route': self.model_route.to_dict()})
    handler = SimpleNamespace(app=SimpleNamespace(state=state))
    response = RequestHandler._handle_post(handler, '/api/model-route', {'mode': 'omniroute', 'env_key': 'EMPY_OMNIROUTE_API_KEY'})
    assert response['model_route']['mode'] == 'omniroute'
    assert response['model_route']['env_key'] == 'EMPY_OMNIROUTE_API_KEY'


def test_corrupt_saved_route_fails_closed_without_account_fallback(tmp_path: Path) -> None:
    first = GuidedState(tmp_path)
    first.store.set_setting('model-route.v1', {'mode': 'omniroute', 'model': 'auto'})
    restored = GuidedState(tmp_path, restore_session=False)
    assert restored.route_settings_error
    assert isinstance(restored.driver, OmniRouteCodexDriver)
    with pytest.raises(RuntimeError, match='Saved model connection'):
        restored.start_run()
    restored.set_model_route({'mode': 'omniroute', 'model': 'oc/big-pickle'})
    assert restored.route_settings_error is None
