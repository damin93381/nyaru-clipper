from __future__ import annotations

import importlib
import sys
import threading
import time
import types
from datetime import datetime
from datetime import timedelta
from pathlib import Path

import pytest
from sqlmodel import Field, SQLModel, select


def _reset_runtime_state() -> None:
    try:
        from app.db import reset_db_runtime
    except ModuleNotFoundError:
        return
    reset_db_runtime()


@pytest.fixture()
def backend_env(tmp_path, monkeypatch) -> dict[str, Path]:
    data_dir = tmp_path / "data"
    db_path = tmp_path / "task-state.sqlite3"
    monkeypatch.setenv("APP_DATA_DIR", str(data_dir))
    monkeypatch.setenv("APP_DATABASE_URL", f"sqlite:///{db_path}")
    _reset_runtime_state()
    return {"data_dir": data_dir, "db_path": db_path}


@pytest.fixture(autouse=True)
def task_control_shim(monkeypatch):
    from app.db import get_engine
    import app.models as app_models

    TaskExecutionControl = getattr(app_models, "TaskExecutionControl", None)
    if TaskExecutionControl is None:
        class TaskExecutionControl(SQLModel, table=True):
            __tablename__ = "task_execution_control"

            task_id: str = Field(primary_key=True, foreign_key="task.id")
            execution_token: str | None = Field(default=None, index=True)
            active_process_group_id: int | None = Field(default=None)
            cancel_requested: bool = Field(default=False, index=True)
            force_kill_requested: bool = Field(default=False)
            heartbeat_at: datetime | None = Field(default=None)
            created_at: datetime = Field(default_factory=app_models.utc_now)
            updated_at: datetime = Field(default_factory=app_models.utc_now)

        setattr(app_models, "TaskExecutionControl", TaskExecutionControl)
    if "TaskExecutionControl" not in app_models.__all__:
        app_models.__all__.append("TaskExecutionControl")

    def _ensure_control_table(session) -> None:
        SQLModel.metadata.create_all(get_engine(), tables=[TaskExecutionControl.__table__])

    class StaleExecutionTokenError(RuntimeError):
        def __init__(
            self,
            *,
            task_id: str,
            execution_token: str | None,
            current_execution_token: str | None,
        ):
            self.task_id = task_id
            self.execution_token = execution_token
            self.current_execution_token = current_execution_token
            super().__init__(
                f"Execution token for task {task_id!r} is stale: "
                f"{execution_token!r} != {current_execution_token!r}"
            )

    def bind_execution_context(session, *, task_id: str, execution_token: str) -> None:
        session.info["pipeline_execution_context"] = {
            "task_id": task_id,
            "execution_token": execution_token,
        }

    def get_execution_context(session):
        context = session.info.get("pipeline_execution_context")
        return context if isinstance(context, dict) else None

    def activate_execution(session, *, task_id: str, execution_token: str, heartbeat_at=None) -> None:
        _ensure_control_table(session)
        control = session.get(TaskExecutionControl, task_id)
        if control is None:
            control = TaskExecutionControl(task_id=task_id)
        now = app_models.utc_now()
        control.execution_token = execution_token
        control.active_process_group_id = None
        control.cancel_requested = False
        control.force_kill_requested = False
        control.heartbeat_at = heartbeat_at or now
        control.updated_at = now
        session.add(control)
        session.commit()

    def ensure_current_execution_context(session, *, task_id: str) -> None:
        context = get_execution_context(session)
        if context is None or context.get("task_id") != task_id:
            raise RuntimeError(f"No execution context bound for task {task_id!r}")
        _ensure_control_table(session)
        control = session.get(TaskExecutionControl, task_id)
        current_execution_token = control.execution_token if control is not None else None
        execution_token = context.get("execution_token")
        if execution_token != current_execution_token:
            raise StaleExecutionTokenError(
                task_id=task_id,
                execution_token=execution_token if isinstance(execution_token, str) else None,
                current_execution_token=current_execution_token,
            )

    def request_cancel(session, *, task_id: str) -> None:
        _ensure_control_table(session)
        control = session.get(TaskExecutionControl, task_id)
        if control is None:
            raise ValueError(f"Task execution control missing for task {task_id!r}")
        control.cancel_requested = True
        control.updated_at = app_models.utc_now()
        session.add(control)
        session.commit()

    def request_force_kill(session, *, task_id: str) -> None:
        _ensure_control_table(session)
        control = session.get(TaskExecutionControl, task_id)
        if control is None:
            raise ValueError(f"Task execution control missing for task {task_id!r}")
        control.force_kill_requested = True
        control.updated_at = app_models.utc_now()
        session.add(control)
        session.commit()

    def finalize_cancelled(session, *, task_id: str, execution_token: str) -> None:
        ensure_current_execution_context(session, task_id=task_id)
        control = session.get(TaskExecutionControl, task_id)
        if control is None:
            raise ValueError(f"Task execution control missing for task {task_id!r}")
        control.execution_token = None
        control.active_process_group_id = None
        control.cancel_requested = False
        control.force_kill_requested = False
        control.heartbeat_at = None
        control.updated_at = app_models.utc_now()
        session.add(control)

    shim = types.ModuleType("app.services.task_control")
    shim.StaleExecutionTokenError = StaleExecutionTokenError
    shim.activate_execution = activate_execution
    shim.bind_execution_context = bind_execution_context
    shim.ensure_current_execution_context = ensure_current_execution_context
    shim.finalize_cancelled = finalize_cancelled
    shim.get_execution_context = get_execution_context
    shim.request_cancel = request_cancel
    shim.request_force_kill = request_force_kill

    monkeypatch.setitem(sys.modules, "app.services.task_control", shim)
    import app.services.pipeline_support as pipeline_support

    importlib.reload(pipeline_support)
    yield


def _create_task(*, source_url: str) -> str:
    from app.db import init_db, session_scope
    from app.repositories.tasks import create_task

    init_db()
    with session_scope() as session:
        payload, _ = create_task(session, source_url)
        return payload["task_id"]


def _bind_execution(session, *, task_id: str, execution_token: str, heartbeat_at=None) -> None:
    from app.services.task_control import activate_execution, bind_execution_context

    activate_execution(
        session,
        task_id=task_id,
        execution_token=execution_token,
        heartbeat_at=heartbeat_at,
    )
    bind_execution_context(session, task_id=task_id, execution_token=execution_token)


def _write_script(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _wait_for(predicate, *, timeout: float = 10.0, interval: float = 0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError("Timed out waiting for condition")


def _normalize_comparable_datetime(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.replace(tzinfo=None)


def test_set_stage_status_allows_direct_service_update_without_execution_context(backend_env) -> None:
    task_id = _create_task(source_url="https://www.bilibili.com/video/BV1directstatus001")

    from app.db import session_scope
    from app.models import TaskStage
    from app.services.pipeline_support import set_stage_status

    with session_scope() as session:
        set_stage_status(
            session,
            task_id=task_id,
            stage_name="ingest",
            status="success",
            summary="direct service update",
        )
        stage = session.exec(
            select(TaskStage)
            .where(TaskStage.task_id == task_id)
            .where(TaskStage.name == "ingest")
        ).one()
        stage_status = stage.status
        stage_summary = stage.summary

    assert stage_status == "success"
    assert stage_summary == "direct service update"


def _load_control(task_id: str):
    from app.db import session_scope
    from app.models import TaskExecutionControl

    with session_scope() as session:
        control = session.get(TaskExecutionControl, task_id)
        if control is None:
            return None
        return {
            "execution_token": control.execution_token,
            "active_process_group_id": control.active_process_group_id,
            "heartbeat_at": control.heartbeat_at,
            "cancel_requested": control.cancel_requested,
            "force_kill_requested": control.force_kill_requested,
        }


def test_structured_helper_streams_progress_events_and_logs_messages(backend_env, tmp_path) -> None:
    task_id = _create_task(source_url="https://www.bilibili.com/video/BV1structured001")
    log_path = tmp_path / "structured.log"
    script_path = tmp_path / "structured_progress.py"
    _write_script(
        script_path,
        """#!/usr/bin/env python3
import json
import sys

events = [
    {"event": "progress", "message": "booting", "progress": 0.1, "phase": "load"},
    {"event": "progress", "message": "finished", "progress": 1.0, "phase": "done"},
]
for event in events:
    sys.stdout.write(json.dumps(event) + "\\n")
    sys.stdout.flush()
""",
    )

    from app.db import session_scope
    from app.services.pipeline_support import run_tracked_structured_process_group_command

    with session_scope() as session:
        _bind_execution(session, task_id=task_id, execution_token="token-structured-progress")
        result = run_tracked_structured_process_group_command(
            session,
            task_id=task_id,
            args=[str(script_path)],
            log_path=log_path,
        )

    assert result.completed_process.returncode == 0
    assert [event["message"] for event in result.events] == ["booting", "finished"]
    assert result.latest_event["phase"] == "done"
    log_text = log_path.read_text(encoding="utf-8")
    assert "booting" in log_text
    assert "finished" in log_text
    assert "exit_code=0" in log_text


def test_structured_helper_touches_heartbeat_while_streaming(backend_env, tmp_path) -> None:
    task_id = _create_task(source_url="https://www.bilibili.com/video/BV1structured002")
    log_path = tmp_path / "heartbeat.log"
    script_path = tmp_path / "heartbeat_progress.py"
    _write_script(
        script_path,
        """#!/usr/bin/env python3
import json
import sys
import time

sys.stdout.write(json.dumps({"event": "progress", "message": "first", "progress": 0.2}) + "\\n")
sys.stdout.flush()
time.sleep(1.0)
sys.stdout.write(json.dumps({"event": "progress", "message": "second", "progress": 0.8}) + "\\n")
sys.stdout.flush()
time.sleep(0.4)
""",
    )

    from app.db import session_scope
    from app.models import utc_now
    from app.services.pipeline_support import run_tracked_structured_process_group_command

    old_heartbeat = utc_now() - timedelta(minutes=5)
    old_heartbeat_for_compare = _normalize_comparable_datetime(old_heartbeat)
    result_holder: dict[str, object] = {}

    def _target() -> None:
        with session_scope() as session:
            _bind_execution(
                session,
                task_id=task_id,
                execution_token="token-heartbeat",
                heartbeat_at=old_heartbeat,
            )
            result_holder["result"] = run_tracked_structured_process_group_command(
                session,
                task_id=task_id,
                args=[str(script_path)],
                log_path=log_path,
                poll_interval_seconds=0.1,
            )

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()

    control = _wait_for(
        lambda: (
            loaded
            if (loaded := _load_control(task_id)) is not None
            and loaded["active_process_group_id"] is not None
            and loaded["heartbeat_at"] is not None
            and _normalize_comparable_datetime(loaded["heartbeat_at"]) > old_heartbeat_for_compare
            else None
        )
    )
    assert control["active_process_group_id"] is not None
    assert control["heartbeat_at"] is not None
    assert _normalize_comparable_datetime(control["heartbeat_at"]) > old_heartbeat_for_compare

    thread.join(timeout=10)
    assert not thread.is_alive()
    result = result_holder.get("result")
    assert result is not None


def test_structured_helper_escalates_from_sigterm_to_sigkill_on_cancel(
    backend_env, tmp_path, monkeypatch
) -> None:
    task_id = _create_task(source_url="https://www.bilibili.com/video/BV1structured003")
    log_path = tmp_path / "cancel.log"
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    script_path = tmp_path / "ignore_term.py"
    _write_script(
        script_path,
        """#!/usr/bin/env python3
import os
import signal
import time
from pathlib import Path

state_dir = Path(os.environ["NYARU_STRUCTURED_STATE_DIR"])
state_dir.mkdir(parents=True, exist_ok=True)
(state_dir / "pid.txt").write_text(str(os.getpid()), encoding="utf-8")

def _handle_term(signum, frame):
    (state_dir / "term.txt").write_text("received", encoding="utf-8")

signal.signal(signal.SIGTERM, _handle_term)
while True:
    time.sleep(0.1)
""",
    )
    monkeypatch.setenv("NYARU_STRUCTURED_STATE_DIR", str(state_dir))

    from app.db import session_scope
    from app.services.pipeline_support import run_tracked_structured_process_group_command
    from app.services.task_control import StaleExecutionTokenError, request_cancel

    result_holder: dict[str, object] = {}

    def _target() -> None:
        try:
            with session_scope() as session:
                _bind_execution(session, task_id=task_id, execution_token="token-cancel-escalate")
                result_holder["result"] = run_tracked_structured_process_group_command(
                    session,
                    task_id=task_id,
                    args=[str(script_path)],
                    log_path=log_path,
                    poll_interval_seconds=0.1,
                    cancel_grace_period_seconds=0.2,
                )
        except BaseException as exc:  # pragma: no cover - asserted below
            result_holder["exception"] = exc

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()

    _wait_for(lambda: (state_dir / "pid.txt").exists())
    with session_scope() as session:
        request_cancel(session, task_id=task_id)

    thread.join(timeout=10)
    assert not thread.is_alive()
    assert isinstance(result_holder.get("exception"), StaleExecutionTokenError)
    assert (state_dir / "term.txt").read_text(encoding="utf-8") == "received"
    control = _load_control(task_id)
    assert control is not None
    assert control["execution_token"] is None
    assert control["active_process_group_id"] is None
    assert "task_control:cancel_requested" in log_path.read_text(encoding="utf-8")


def test_structured_helper_force_kill_request_skips_sigterm_and_clears_process_group(
    backend_env, tmp_path, monkeypatch
) -> None:
    task_id = _create_task(source_url="https://www.bilibili.com/video/BV1structuredforcekill001")
    log_path = tmp_path / "force-kill.log"
    state_dir = tmp_path / "state-force-kill"
    state_dir.mkdir(parents=True, exist_ok=True)
    script_path = tmp_path / "force_kill_target.py"
    _write_script(
        script_path,
        """#!/usr/bin/env python3
import os
import signal
import time
from pathlib import Path

state_dir = Path(os.environ[\"NYARU_STRUCTURED_STATE_DIR\"])
state_dir.mkdir(parents=True, exist_ok=True)
(state_dir / \"pid.txt\").write_text(str(os.getpid()), encoding=\"utf-8\")

def _handle_term(signum, frame):
    (state_dir / \"term.txt\").write_text(\"received\", encoding=\"utf-8\")

signal.signal(signal.SIGTERM, _handle_term)
while True:
    time.sleep(0.1)
""",
    )
    monkeypatch.setenv("NYARU_STRUCTURED_STATE_DIR", str(state_dir))

    from app.db import session_scope
    from app.services.pipeline_support import run_tracked_structured_process_group_command
    from app.services.task_control import StaleExecutionTokenError, request_force_kill

    result_holder: dict[str, object] = {}

    def _target() -> None:
        try:
            with session_scope() as session:
                _bind_execution(session, task_id=task_id, execution_token="token-force-kill")
                result_holder["result"] = run_tracked_structured_process_group_command(
                    session,
                    task_id=task_id,
                    args=[str(script_path)],
                    log_path=log_path,
                    poll_interval_seconds=0.1,
                    cancel_grace_period_seconds=5.0,
                )
        except BaseException as exc:  # pragma: no cover - asserted below
            result_holder["exception"] = exc

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()

    _wait_for(lambda: (state_dir / "pid.txt").exists())
    with session_scope() as session:
        request_force_kill(session, task_id=task_id)

    thread.join(timeout=10)
    assert not thread.is_alive()
    assert isinstance(result_holder.get("exception"), StaleExecutionTokenError)
    assert not (state_dir / "term.txt").exists()
    control = _load_control(task_id)
    assert control is not None
    assert control["execution_token"] is None
    assert control["active_process_group_id"] is None
    log_text = log_path.read_text(encoding="utf-8")
    assert "task_control:force_kill_requested" in log_text
    assert "task_control:cancel_requested" not in log_text


def test_structured_helper_classifies_malformed_event_output(backend_env, tmp_path, monkeypatch) -> None:
    task_id = _create_task(source_url="https://www.bilibili.com/video/BV1structured004")
    log_path = tmp_path / "malformed.log"
    state_dir = tmp_path / "state-malformed"
    state_dir.mkdir(parents=True, exist_ok=True)
    script_path = tmp_path / "malformed_progress.py"
    _write_script(
        script_path,
        """#!/usr/bin/env python3
import os
import time
from pathlib import Path

state_dir = Path(os.environ["NYARU_STRUCTURED_STATE_DIR"])
state_dir.mkdir(parents=True, exist_ok=True)
(state_dir / "pid.txt").write_text(str(os.getpid()), encoding="utf-8")
print("not-json", flush=True)
while True:
    time.sleep(0.1)
""",
    )
    monkeypatch.setenv("NYARU_STRUCTURED_STATE_DIR", str(state_dir))

    from app.db import session_scope
    from app.services.pipeline_support import (
        StructuredProgressProtocolError,
        run_tracked_structured_process_group_command,
    )

    with pytest.raises(StructuredProgressProtocolError) as exc_info:
        with session_scope() as session:
            _bind_execution(session, task_id=task_id, execution_token="token-malformed")
            run_tracked_structured_process_group_command(
                session,
                task_id=task_id,
                args=[str(script_path)],
                log_path=log_path,
                poll_interval_seconds=0.1,
            )

    assert exc_info.value.code == "malformed_progress_event"
    control = _load_control(task_id)
    assert control is not None
    assert control["active_process_group_id"] is None
    assert "malformed_progress_event" in log_path.read_text(encoding="utf-8")
