"""Stage templates: default checkpoint names for a kind of project.

Most work moves through the same skeleton — plan, design, build, test, deploy,
monitor — and each field has its own names for the steps. A template is that
list of names. Choosing one records it in the hub (`template.toml`, tracked, so
a clone knows the sequence too); from then on `mh checkpoint` with no name
creates the next stage, `mh status` says where the project stands, and the map
draws the stages still ahead. Nothing is created up front: a stage becomes a
checkpoint when the work reaches it, so the timeline keeps its real dates.

The built-in lists are a starting point, not a rule: the file carries a copy of
the stages, and editing it is how a project gets its own sequence.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path

from . import checkpoint as ck
from . import git
from .hub import MhError

FILE = "template.toml"


@dataclass(frozen=True)
class Template:
    name: str
    title: str
    stages: tuple[tuple[str, str], ...]  # (stage name, what happens there)


TEMPLATES: dict[str, Template] = {
    t.name: t
    for t in (
        Template(
            "quant",
            "Quant strategy — research → develop → backtest → deploy → monitor",
            (
                ("Research", "hypothesis, target market, alpha source, objectives"),
                ("Design", "architecture, data schema, strategy logic, stack, evaluation criteria"),
                ("Data Engineering", "collect, clean, store and pipeline the data"),
                ("Implementation", "strategy logic, signals, execution code"),
                ("Backtesting", "historical tests, overfitting checks, walk-forward analysis"),
                ("Optimization", "performance metrics, parameter tuning, risk analysis"),
                ("Paper Trading", "live-ish in a sandbox to verify real-time behaviour"),
                ("Live Deployment", "production rollout, capital allocation, monitoring"),
                ("Monitoring", "live performance vs expectations, decay detection, iteration"),
            ),
        ),
        Template(
            "frontend",
            "Frontend development",
            (
                ("Requirement Analysis", "requirements, UI/UX interactions"),
                ("UI/UX Design", "mockups, prototypes, design system"),
                ("Scaffolding", "project setup, stack choice"),
                ("Component Development", "components and pages"),
                ("API Integration", "backend endpoints, mock data"),
                ("State & Routing", "state management, routing"),
                ("Styling & Responsive", "polish, responsive layouts"),
                ("Testing", "unit and end-to-end tests"),
                ("Performance Optimization", "bundles, lazy loading, Core Web Vitals"),
                ("Build & Deployment", "CI/CD, static assets, CDN"),
            ),
        ),
        Template(
            "backend",
            "Backend development",
            (
                ("Requirement Analysis", "requirements, business rules"),
                ("System Design", "architecture, API contracts, data model"),
                ("Environment Setup", "scaffolding, development environment"),
                ("Database Development", "schema, migrations, ORM"),
                ("API Development", "controllers, services, repositories"),
                ("Business Logic", "core logic, transactions"),
                ("Authentication & Authorization", "JWT / OAuth / RBAC"),
                ("Testing", "unit, integration and API tests"),
                ("Performance & Security", "caching, rate limits, query tuning, hardening"),
                ("Deployment & Observability", "containers, CI/CD, logs, metrics, alerts"),
            ),
        ),
        Template(
            "sdlc",
            "General software — the classic lifecycle",
            (
                ("Planning", "scope and plan"),
                ("Analysis", "requirements"),
                ("Design", "architecture"),
                ("Implementation", "build it"),
                ("Testing", "verify it"),
                ("Deployment", "ship it"),
                ("Maintenance", "keep it running"),
            ),
        ),
        Template(
            "mobile",
            "Mobile development",
            (
                ("Requirement & PRD Review", "requirements and the PRD"),
                ("UI/UX Design", "mockups, prototypes"),
                ("Architecture Setup", "modules, state management"),
                ("Feature Development", "iOS / Android / cross-platform"),
                ("API Integration", "backend endpoints"),
                ("Local Storage & Offline", "persistence, offline handling"),
                ("Testing", "unit, UI automation, real devices"),
                ("Release Management", "builds, store review, staged rollout"),
                ("Crash Monitoring & Iteration", "crash reports, hotfixes"),
            ),
        ),
        Template(
            "devops",
            "DevOps / infrastructure",
            (
                ("Provisioning", "infrastructure as code"),
                ("Containerization", "images and compose"),
                ("CI Pipeline", "build and test"),
                ("CD Pipeline", "blue/green, canary, rolling deploys"),
                ("Monitoring & Alerting", "metrics, dashboards, logs"),
                ("Incident Response", "on-call, incident handling"),
                ("Optimization", "cost and capacity"),
            ),
        ),
        Template(
            "data",
            "Data engineering",
            (
                ("Data Requirement Analysis", "what data, for whom"),
                ("Data Source Integration", "connect the sources"),
                ("Pipeline Development", "ETL / ELT"),
                ("Data Warehouse Modeling", "layered modelling (ODS/DWD/DWS/ADS)"),
                ("Data Quality Validation", "quality checks"),
                ("Orchestration & Scheduling", "schedules and dependencies"),
                ("Monitoring & Maintenance", "keep the pipelines healthy"),
            ),
        ),
        Template(
            "ml",
            "Machine learning — CRISP-DM",
            (
                ("Business Understanding", "the problem"),
                ("Data Understanding", "exploration"),
                ("Data Preparation", "cleaning, features"),
                ("Modeling", "model choice, training"),
                ("Evaluation", "metrics, tuning"),
                ("Deployment", "serving"),
                ("Monitoring & Retraining", "drift, retraining"),
            ),
        ),
        Template(
            "sprint",
            "Agile sprint",
            (
                ("Backlog Grooming", "refine the backlog"),
                ("Sprint Planning", "plan the iteration"),
                ("Development", "build"),
                ("Code Review", "review"),
                ("QA & Testing", "test"),
                ("Release", "ship"),
                ("Review & Retrospective", "look back"),
            ),
        ),
        Template(
            "hotfix",
            "Bug fix / hotfix",
            (
                ("Reproduce", "reproduce the problem"),
                ("Root Cause Analysis", "find the cause"),
                ("Fix Development", "fix it"),
                ("Testing & Verification", "regression tests"),
                ("Review & Merge", "review and merge"),
                ("Deploy & Monitor", "ship and watch"),
            ),
        ),
    )
}


def path(hub: Path) -> Path:
    return hub / FILE


def get(name: str) -> Template:
    t = TEMPLATES.get(name.lower())
    if t is None:
        raise MhError(f"no template '{name}' (see 'mh template --list'): " + ", ".join(TEMPLATES))
    return t


def read(hub: Path) -> dict | None:
    """The hub's template — its name and stages as recorded, which may have
    been edited since — or None."""
    p = path(hub)
    if not p.is_file():
        return None
    try:
        data = tomllib.loads(p.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as e:
        raise MhError(f"{p.name} is not readable: {e}") from None
    stages = data.get("stages")
    if not isinstance(stages, list) or not all(isinstance(s, str) and s.strip() for s in stages):
        raise MhError(f"{p.name}: 'stages' must be a list of names")
    return {"name": str(data.get("name") or "custom"), "stages": [s.strip() for s in stages]}


def use(hub: Path, name: str) -> dict:
    """Record a template for this hub. The stages are copied into the file so
    the project owns its sequence: editing the file changes it, and a later
    change to mh's built-ins does not."""
    t = get(name)
    rows = ",\n  ".join(json.dumps(s) for s, _ in t.stages)
    path(hub).write_text(
        f"# Stage template: checkpoint names `mh checkpoint` (no name) creates in order.\n"
        f"# Edit the list to fit the project; a stage already created stays where it is.\n"
        f'name = "{t.name}"\nstages = [\n  {rows},\n]\n',
        encoding="utf-8",
    )
    git.auto_commit(hub, f"template: {t.name}")
    return read(hub)


def clear(hub: Path) -> bool:
    p = path(hub)
    if not p.is_file():
        return False
    p.unlink()
    git.auto_commit(hub, "template: none")
    return True


def progress(hub: Path) -> dict | None:
    """Where the project stands in its template: every stage with whether its
    checkpoint exists, and the next one to create — the first stage with no
    checkpoint, so a stage created out of turn does not skip the ones before.
    """
    rec = read(hub)
    if rec is None:
        return None
    # a stage is reached once any checkpoint sits in its column — design-2 counts
    existing = {col["stage"] for col in ck.stages(hub)}
    stages = []
    for s in rec["stages"]:
        slug = ck.slugify(s)
        stages.append({"name": s, "slug": slug, "exists": slug in existing})
    next_stage = next((s["name"] for s in stages if not s["exists"]), None)
    return {
        "name": rec["name"],
        "stages": stages,
        "done": sum(1 for s in stages if s["exists"]),
        "total": len(stages),
        "next": next_stage,
    }


def next_name(hub: Path) -> str:
    """The name `mh checkpoint` uses when given none."""
    p = progress(hub)
    if p is None:
        raise MhError(
            "a name is needed: 'mh checkpoint <name>' — or choose a stage template "
            "with 'mh template <name>' (see 'mh template --list') and mh names the stages"
        )
    if p["next"] is None:
        raise MhError(
            f"every stage of the {p['name']} template exists already; "
            "name the next checkpoint yourself, or edit template.toml"
        )
    return p["next"]


def catalogue() -> list[dict]:
    return [
        {"name": t.name, "title": t.title, "stages": [{"name": s, "about": a} for s, a in t.stages]}
        for t in TEMPLATES.values()
    ]
