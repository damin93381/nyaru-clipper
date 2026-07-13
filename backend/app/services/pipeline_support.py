from __future__ import annotations

import importlib
import json
import os
import queue
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from sqlmodel import Session, select

import app.models as models
from app.services.workstation_events import publish_stage_updated, publish_task_updated

PROCESS_GROUP_POLL_INTERVAL_SECONDS = 0.2


@dataclass(slots=True)
class StructuredProcessGroupResult:
    completed_process: subprocess.CompletedProcess[str]
    events: list[dict[str, Any]]
    latest_event: dict[str, Any] | None


class StructuredProgressProtocolError(RuntimeError):
    def __init__(self, *, code: str, message: str, raw_line: str):
        super().__init__(message)
        self.code = code
        self.raw_line = raw_line


def _task_control_module():
    return importlib.import_module("app.services.task_control")


def _task_execution_control_model():
    control_model = getattr(models, "TaskExecutionControl", None)
    if control_model is None:
        raise RuntimeError("app.models.TaskExecutionControl is unavailable")
    return control_model


def _stale_execution_token_error_type():
    stale_error = getattr(_task_control_module(), "StaleExecutionTokenError", None)
    if stale_error is None:
        raise RuntimeError("app.services.task_control.StaleExecutionTokenError is unavailable")
    return stale_error


def append_stage_log(log_path: Path, message: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"{message}\n")


def run_logged_command(
    args: list[str],
    *,
    log_path: Path,
    redactions: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command while replacing sensitive runtime-only paths before persistence."""
    def redact(message: str) -> str:
        if redactions is None:
            return message
        for source_path, safe_locator in redactions.items():
            message = message.replace(source_path, safe_locator)
        return message

    append_stage_log(log_path, redact(f"$ {' '.join(args)}"))
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.stdout:
        append_stage_log(log_path, redact(result.stdout.rstrip()))
    if result.stderr:
        append_stage_log(log_path, redact(result.stderr.rstrip()))
    append_stage_log(log_path, f"exit_code={result.returncode}")
    return result


def run_tracked_process_group_command(
    session: Session,
    *,
    task_id: str,
    args: list[str],
    log_path: Path,
    poll_interval_seconds: float = PROCESS_GROUP_POLL_INTERVAL_SECONDS,
) -> subprocess.CompletedProcess[str]:
    context = _task_control_module().get_execution_context(session)
    if context is None or context.get("task_id") != task_id:
        return run_logged_command(args, log_path=log_path)

    _task_control_module().ensure_current_execution_context(session, task_id=task_id)
    _finalize_cancelled_before_launch_if_requested(session, task_id=task_id)
    append_stage_log(log_path, f"$ {' '.join(args)}")
    process = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    process_group_id = process.pid
    _set_active_process_group(
        session,
        task_id=task_id,
        process_group_id=process_group_id,
    )

    term_sent = False
    kill_sent = False
    stdout = ""
    stderr = ""

    while True:
        try:
            stdout, stderr = process.communicate(timeout=poll_interval_seconds)
            break
        except subprocess.TimeoutExpired:
            try:
                _touch_active_process_group(session, task_id=task_id)
            except Exception as exc:
                if not isinstance(exc, _stale_execution_token_error_type()):
                    raise
                append_stage_log(
                    log_path,
                    f"task_control:stale_execution_terminating process_group={process_group_id}",
                )
                _terminate_process_group_and_wait(
                    process,
                    process_group_id=process_group_id,
                    signal_number=signal.SIGKILL,
                )
                raise
            cancel_requested, force_kill_requested = _load_control_requests(session, task_id=task_id)
            if force_kill_requested and not kill_sent:
                append_stage_log(
                    log_path,
                    f"task_control:force_kill_requested process_group={process_group_id}",
                )
                _terminate_process_group_and_wait(
                    process,
                    process_group_id=process_group_id,
                    signal_number=signal.SIGKILL,
                )
                kill_sent = True
            elif cancel_requested and not term_sent:
                append_stage_log(
                    log_path,
                    f"task_control:cancel_requested process_group={process_group_id}",
                )
                _signal_process_group(process_group_id, signal.SIGTERM)
                term_sent = True

    if stdout:
        append_stage_log(log_path, stdout.rstrip())
    if stderr:
        append_stage_log(log_path, stderr.rstrip())
    append_stage_log(log_path, f"exit_code={process.returncode}")

    if term_sent or kill_sent:
        _finalize_cancelled_process_group(session, task_id=task_id)

    _clear_active_process_group(session, task_id=task_id)
    return subprocess.CompletedProcess(
        args=args,
        returncode=process.returncode,
        stdout=stdout,
        stderr=stderr,
    )


def run_tracked_structured_process_group_command(
    session: Session,
    *,
    task_id: str,
    args: list[str],
    log_path: Path,
    poll_interval_seconds: float = PROCESS_GROUP_POLL_INTERVAL_SECONDS,
    cancel_grace_period_seconds: float = 10.0,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> StructuredProcessGroupResult:
    context = _task_control_module().get_execution_context(session)
    if context is None or context.get("task_id") != task_id:
        return _run_logged_structured_command(args, log_path=log_path, on_event=on_event)

    _task_control_module().ensure_current_execution_context(session, task_id=task_id)
    _finalize_cancelled_before_launch_if_requested(session, task_id=task_id)
    append_stage_log(log_path, f"$ {' '.join(args)}")
    process = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        start_new_session=True,
    )
    process_group_id = process.pid
    _set_active_process_group(
        session,
        task_id=task_id,
        process_group_id=process_group_id,
    )

    stdout_queue: queue.Queue[tuple[str, str | None]] = queue.Queue()
    stdout_reader = _start_pipe_reader(process.stdout, stream_name="stdout", output_queue=stdout_queue)
    stderr_reader = _start_pipe_reader(process.stderr, stream_name="stderr", output_queue=stdout_queue)

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    events: list[dict[str, Any]] = []
    latest_event: dict[str, Any] | None = None
    stdout_closed = False
    stderr_closed = False
    term_sent = False
    kill_sent = False
    cancel_deadline: float | None = None
    protocol_error: StructuredProgressProtocolError | None = None

    try:
        while True:
            if process.poll() is not None and stdout_closed and stderr_closed and stdout_queue.empty():
                break

            try:
                stream_name, line = stdout_queue.get(timeout=poll_interval_seconds)
            except queue.Empty:
                _touch_heartbeat_or_abort(session, task_id=task_id, log_path=log_path, process=process)
                term_sent, kill_sent, cancel_deadline = _apply_process_group_control(
                    session,
                    task_id=task_id,
                    log_path=log_path,
                    process=process,
                    process_group_id=process_group_id,
                    term_sent=term_sent,
                    kill_sent=kill_sent,
                    cancel_deadline=cancel_deadline,
                    cancel_grace_period_seconds=cancel_grace_period_seconds,
                )
                continue

            if line is None:
                if stream_name == "stdout":
                    stdout_closed = True
                else:
                    stderr_closed = True
            elif stream_name == "stdout":
                stripped_line = line.rstrip("\n")
                stdout_lines.append(line)
                if stripped_line:
                    try:
                        parsed_event = _parse_structured_event_line(stripped_line)
                    except StructuredProgressProtocolError as exc:
                        append_stage_log(log_path, f"classified_failure={exc.code}")
                        protocol_error = exc
                        _terminate_process_group_and_wait(
                            process,
                            process_group_id=process_group_id,
                            signal_number=signal.SIGKILL,
                            timeout_seconds=1.0,
                        )
                    else:
                        events.append(parsed_event)
                        latest_event = parsed_event
                        append_stage_log(log_path, _format_structured_event_for_log(parsed_event))
                        if on_event is not None:
                            on_event(parsed_event)
                        _touch_heartbeat_or_abort(session, task_id=task_id, log_path=log_path, process=process)
            else:
                stderr_lines.append(line)
                if line.rstrip():
                    append_stage_log(log_path, line.rstrip())

            if protocol_error is not None:
                continue

            term_sent, kill_sent, cancel_deadline = _apply_process_group_control(
                session,
                task_id=task_id,
                log_path=log_path,
                process=process,
                process_group_id=process_group_id,
                term_sent=term_sent,
                kill_sent=kill_sent,
                cancel_deadline=cancel_deadline,
                cancel_grace_period_seconds=cancel_grace_period_seconds,
            )
    finally:
        stdout_reader.join(timeout=1)
        stderr_reader.join(timeout=1)

    completed_process = subprocess.CompletedProcess(
        args=args,
        returncode=process.returncode,
        stdout="".join(stdout_lines),
        stderr="".join(stderr_lines),
    )
    append_stage_log(log_path, f"exit_code={process.returncode}")

    if term_sent or kill_sent:
        _finalize_cancelled_process_group(session, task_id=task_id)

    _clear_active_process_group(session, task_id=task_id)

    if protocol_error is not None:
        raise protocol_error

    return StructuredProcessGroupResult(
        completed_process=completed_process,
        events=events,
        latest_event=latest_event,
    )


def _run_logged_structured_command(
    args: list[str], *, log_path: Path, on_event: Callable[[dict[str, Any]], None] | None = None
) -> StructuredProcessGroupResult:
    append_stage_log(log_path, f"$ {' '.join(args)}")
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    events: list[dict[str, Any]] = []
    latest_event: dict[str, Any] | None = None
    for raw_line in result.stdout.splitlines():
        parsed_event = _parse_structured_event_line(raw_line)
        events.append(parsed_event)
        latest_event = parsed_event
        append_stage_log(log_path, _format_structured_event_for_log(parsed_event))
        if on_event is not None:
            on_event(parsed_event)
    if result.stderr:
        append_stage_log(log_path, result.stderr.rstrip())
    append_stage_log(log_path, f"exit_code={result.returncode}")
    return StructuredProcessGroupResult(
        completed_process=result,
        events=events,
        latest_event=latest_event,
    )


def _load_control_requests(session: Session, *, task_id: str) -> tuple[bool, bool]:
    session.expire_all()
    control = session.get(_task_execution_control_model(), task_id)
    if control is None:
        return False, False
    return bool(control.cancel_requested), bool(control.force_kill_requested)


def _finalize_cancelled_before_launch_if_requested(session: Session, *, task_id: str) -> None:
    cancel_requested, force_kill_requested = _load_control_requests(session, task_id=task_id)
    if cancel_requested or force_kill_requested:
        _finalize_cancelled_process_group(session, task_id=task_id)


def _set_active_process_group(session: Session, *, task_id: str, process_group_id: int) -> None:
    _task_control_module().ensure_current_execution_context(session, task_id=task_id)
    control = session.get(_task_execution_control_model(), task_id)
    if control is None:
        raise ValueError(f"Task execution control missing for task {task_id!r}")
    now = models.utc_now()
    control.active_process_group_id = process_group_id
    control.heartbeat_at = now
    control.updated_at = now
    session.add(control)
    session.commit()


def _touch_active_process_group(session: Session, *, task_id: str) -> None:
    _task_control_module().ensure_current_execution_context(session, task_id=task_id)
    control = session.get(_task_execution_control_model(), task_id)
    if control is None:
        return
    now = models.utc_now()
    control.heartbeat_at = now
    control.updated_at = now
    session.add(control)
    session.commit()


def _clear_active_process_group(session: Session, *, task_id: str) -> None:
    context = _task_control_module().get_execution_context(session)
    if context is None or context.get("task_id") != task_id:
        return
    _task_control_module().ensure_current_execution_context(session, task_id=task_id)
    control = session.get(_task_execution_control_model(), task_id)
    if control is None:
        return
    now = models.utc_now()
    control.active_process_group_id = None
    control.heartbeat_at = now
    control.updated_at = now
    session.add(control)
    session.commit()


def _finalize_cancelled_process_group(session: Session, *, task_id: str) -> None:
    context = _task_control_module().get_execution_context(session)
    execution_token = context.get("execution_token") if isinstance(context, dict) else None
    if not isinstance(execution_token, str):
        raise RuntimeError(f"No execution token bound while cancelling task {task_id!r}")
    _task_control_module().finalize_cancelled(
        session, task_id=task_id, execution_token=execution_token
    )
    session.commit()
    raise _stale_execution_token_error_type()(
        task_id=task_id,
        execution_token=execution_token,
        current_execution_token=None,
    )


def _signal_process_group(process_group_id: int, signal_number: int) -> None:
    try:
        os.killpg(process_group_id, signal_number)
    except ProcessLookupError:
        return


def _terminate_process_group_and_wait(
    process: subprocess.Popen[str],
    *,
    process_group_id: int,
    signal_number: int,
    timeout_seconds: float = 5.0,
) -> None:
    _signal_process_group(process_group_id, signal_number)
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        return


def _start_pipe_reader(
    pipe, *, stream_name: str, output_queue: queue.Queue[tuple[str, str | None]]
) -> threading.Thread:
    def _reader() -> None:
        if pipe is None:
            output_queue.put((stream_name, None))
            return
        try:
            for line in iter(pipe.readline, ""):
                output_queue.put((stream_name, line))
        finally:
            pipe.close()
            output_queue.put((stream_name, None))

    thread = threading.Thread(target=_reader, daemon=True)
    thread.start()
    return thread


def _parse_structured_event_line(raw_line: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw_line)
    except json.JSONDecodeError as exc:
        raise StructuredProgressProtocolError(
            code="malformed_progress_event",
            message="Child emitted malformed structured progress output",
            raw_line=raw_line,
        ) from exc
    if not isinstance(payload, dict):
        raise StructuredProgressProtocolError(
            code="malformed_progress_event",
            message="Child emitted a non-object structured progress event",
            raw_line=raw_line,
        )
    event_name = payload.get("event")
    if not isinstance(event_name, str) or not event_name:
        raise StructuredProgressProtocolError(
            code="malformed_progress_event",
            message="Child emitted structured progress without an event name",
            raw_line=raw_line,
        )
    return payload


def _format_structured_event_for_log(event: dict[str, Any]) -> str:
    message = event.get("message")
    if isinstance(message, str) and message.strip():
        return message.strip()
    return json.dumps(event, ensure_ascii=False, sort_keys=True)


def _touch_heartbeat_or_abort(
    session: Session,
    *,
    task_id: str,
    log_path: Path,
    process: subprocess.Popen[str],
) -> None:
    try:
        _touch_active_process_group(session, task_id=task_id)
    except Exception as exc:
        if not isinstance(exc, _stale_execution_token_error_type()):
            raise
        append_stage_log(log_path, f"task_control:stale_execution_terminating process_group={process.pid}")
        _terminate_process_group_and_wait(
            process,
            process_group_id=process.pid,
            signal_number=signal.SIGKILL,
            timeout_seconds=1.0,
        )
        raise


def _apply_process_group_control(
    session: Session,
    *,
    task_id: str,
    log_path: Path,
    process: subprocess.Popen[str],
    process_group_id: int,
    term_sent: bool,
    kill_sent: bool,
    cancel_deadline: float | None,
    cancel_grace_period_seconds: float,
) -> tuple[bool, bool, float | None]:
    cancel_requested, force_kill_requested = _load_control_requests(session, task_id=task_id)
    if force_kill_requested and not kill_sent:
        append_stage_log(log_path, f"task_control:force_kill_requested process_group={process_group_id}")
        _terminate_process_group_and_wait(
            process,
            process_group_id=process_group_id,
            signal_number=signal.SIGKILL,
            timeout_seconds=1.0,
        )
        return True, True, cancel_deadline
    if cancel_requested and not term_sent:
        append_stage_log(log_path, f"task_control:cancel_requested process_group={process_group_id}")
        _signal_process_group(process_group_id, signal.SIGTERM)
        return True, kill_sent, time.monotonic() + cancel_grace_period_seconds
    if (
        term_sent
        and not kill_sent
        and process.poll() is None
        and cancel_deadline is not None
        and time.monotonic() >= cancel_deadline
    ):
        append_stage_log(log_path, f"task_control:cancel_escalated_kill process_group={process_group_id}")
        _terminate_process_group_and_wait(
            process,
            process_group_id=process_group_id,
            signal_number=signal.SIGKILL,
            timeout_seconds=1.0,
        )
        return term_sent, True, cancel_deadline
    return term_sent, kill_sent, cancel_deadline


def set_stage_status(
    session: Session, *, task_id: str, stage_name: str, status: str, summary: str, failure_code: str | None = None
) -> None:
    task_control = _task_control_module()
    get_execution_context = getattr(task_control, "get_execution_context", None)
    context = get_execution_context(session) if get_execution_context is not None else None
    if context is not None:
        task_control.ensure_current_execution_context(session, task_id=task_id)
    stage = session.exec(
        select(models.TaskStage)
        .where(models.TaskStage.task_id == task_id)
        .where(models.TaskStage.name == stage_name)
    ).first()
    if stage is None:
        raise ValueError(f"Stage {stage_name!r} not found for task {task_id!r}")

    now = models.utc_now()
    stage.status = status
    stage.summary = summary
    if status == "failed":
        stage.failure_code = failure_code
    else:
        stage.failure_code = None
    stage.updated_at = now
    if status == "success":
        stage.finished_at = now
    elif status == "failed":
        stage.finished_at = now
        task = session.get(models.Task, task_id)
        if task is not None:
            task_status_changed = task.status != "failed"
            task.status = "failed"
            task.updated_at = now
            session.add(task)
            if task_status_changed:
                publish_task_updated(session, task)
    session.add(stage)
    publish_stage_updated(session, stage)
