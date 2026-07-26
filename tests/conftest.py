"""Hermetic E2E fixtures: every test drives the real CLI as a subprocess with a
fake HOME — nothing reads from or writes to the real machine."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from memoryhub.purify import encode_project_dir

TIMEOUT = 30


@pytest.fixture()
def ws(tmp_path):
    home = tmp_path / "home"
    (home / ".config").mkdir(parents=True)
    gitconfig = home / "gitconfig"
    gitconfig.write_text(
        "[user]\n\tname = Test\n\temail = test@example.com\n"
        "[init]\n\tdefaultBranch = main\n"
    )
    env = {
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "GIT_CONFIG_GLOBAL": str(gitconfig),
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
        "PATH": os.environ["PATH"],
        "TZ": "UTC",
        "LC_ALL": "en_US.UTF-8",
    }
    return {"root": tmp_path, "home": home, "env": env}


@pytest.fixture()
def mh(ws):
    def run(*args, cwd, check=None, env_extra=None):
        env = dict(ws["env"])
        if env_extra:
            env.update(env_extra)
        proc = subprocess.run(
            [sys.executable, "-m", "memoryhub", *[str(a) for a in args]],
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
        if check is not None:
            assert proc.returncode == check, (
                f"mh {' '.join(map(str, args))} -> exit {proc.returncode}\n"
                f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
            )
        return proc

    return run


def git_run(cwd, env, *args) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    ).stdout


@pytest.fixture()
def project(ws):
    proj = ws["root"] / "proj"
    proj.mkdir()
    subprocess.run(
        ["git", "init", str(proj)],
        env=ws["env"],
        check=True,
        capture_output=True,
        timeout=TIMEOUT,
    )
    (proj / "main.py").write_text("print('hi')\n")
    git_run(proj, ws["env"], "add", "-A")
    git_run(proj, ws["env"], "commit", "-m", "initial")
    return proj


@pytest.fixture()
def hub_project(mh, project):
    mh("init", cwd=project, check=0)
    return project


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def make_records(turns, start="2026-07-10T04:00:00Z", cwd=None):
    """Fabricate a realistic Claude transcript: alternating user/assistant
    records with increasing timestamps, one minute apart."""
    t = datetime.fromisoformat(start.replace("Z", "+00:00"))
    recs = []
    for q, a in turns:
        rec = {
            "type": "user",
            "message": {"role": "user", "content": q},
            "timestamp": iso(t),
        }
        if cwd:
            rec["cwd"] = cwd
        recs.append(rec)
        t += timedelta(minutes=1)
        rec = {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": a}],
            },
            "timestamp": iso(t),
        }
        if cwd:
            rec["cwd"] = cwd
        recs.append(rec)
        t += timedelta(minutes=1)
    return recs


def dump_jsonl(path: Path, records) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return path


def write_transcript(home: Path, project_root: Path, sid: str, records) -> Path:
    tdir = home / ".claude" / "projects" / encode_project_dir(project_root)
    return dump_jsonl(tdir / f"{sid}.jsonl", records)


def make_pi_records(turns, start="2026-07-10T04:00:00Z", cwd=None, sid="x"):
    """pi schema: a session header (with cwd) then type:"message" records."""
    t = datetime.fromisoformat(start.replace("Z", "+00:00"))
    recs = []
    if cwd:
        recs.append(
            {
                "type": "session",
                "version": 3,
                "id": sid,
                "timestamp": iso(t),
                "cwd": cwd,
            }
        )
    for q, a in turns:
        recs.append(
            {
                "type": "message",
                "message": {"role": "user", "content": [{"type": "text", "text": q}]},
                "timestamp": iso(t),
            }
        )
        t += timedelta(minutes=1)
        recs.append(
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "hmm"},
                        {"type": "text", "text": a},
                    ],
                },
                "timestamp": iso(t),
            }
        )
        t += timedelta(minutes=1)
    recs.append({"type": "toolCall", "timestamp": iso(t)})
    return recs


def pi_dir_of(home: Path, project_root: Path) -> Path:
    esc = "-" + str(project_root).rstrip("/").replace("/", "-")
    return home / ".pi" / "agent" / "sessions" / (esc + "--")


def write_pi_transcript(
    home: Path,
    project_root: Path,
    sid: str,
    records,
    stamp_name="2026-07-10T04-00-00-000Z",
) -> Path:
    return dump_jsonl(
        pi_dir_of(home, project_root) / f"{stamp_name}_{sid}.jsonl", records
    )


def write_codex_rollout(
    home: Path,
    project_root: Path,
    sid: str,
    turns,
    start="2026-07-10T04:00:00Z",
    subagent=False,
) -> Path:
    t = datetime.fromisoformat(start.replace("Z", "+00:00"))
    payload: dict = {"id": sid, "timestamp": iso(t), "cwd": str(project_root)}
    if subagent:
        payload["source"] = {"subagent": {"other": "guardian"}}
    recs = [{"timestamp": iso(t), "type": "session_meta", "payload": payload}]
    recs.append(
        {
            "timestamp": iso(t),
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "<environment_context>x</environment_context>",
                    }
                ],
            },
        }
    )
    for q, a in turns:
        recs.append(
            {
                "timestamp": iso(t),
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": q}],
                },
            }
        )
        t += timedelta(minutes=1)
        recs.append(
            {
                "timestamp": iso(t),
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": a}],
                },
            }
        )
        t += timedelta(minutes=1)
    recs.append({"timestamp": iso(t), "type": "event_msg", "payload": {"type": "x"}})
    day = home / ".codex" / "sessions" / "2026" / "07" / "10"
    return dump_jsonl(day / f"rollout-{start.replace(':', '-')}-{sid}.jsonl", recs)
