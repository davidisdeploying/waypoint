"""Governed, source-controlled hands-on lab templates."""

import json
from pathlib import Path

from lib import labs
from lib.api_logic import ApiError, now_iso

CATALOG_PATH = Path(__file__).resolve().parent.parent / "sources/lab_catalog/aplus-v1.json"
DIFFICULTIES = {"beginner", "intermediate", "advanced"}
LIST_FIELDS = ("prerequisites", "equipment", "safety_notes", "steps",
               "success_checks", "evidence_prompts")


def _load():
    payload = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not payload.get("catalog_version"):
        raise RuntimeError("lab catalog has no version")
    templates = payload.get("templates")
    if not isinstance(templates, list) or not templates:
        raise RuntimeError("lab catalog has no templates")
    slugs = set()
    for template in templates:
        required = {"slug", "exam_code", "objective_code", "title", "summary",
                    "difficulty", "estimated_minutes", *LIST_FIELDS}
        if not isinstance(template, dict) or required - set(template):
            raise RuntimeError("lab catalog template is incomplete")
        if template["slug"] in slugs:
            raise RuntimeError(f"duplicate lab template slug: {template['slug']}")
        slugs.add(template["slug"])
        if template["difficulty"] not in DIFFICULTIES:
            raise RuntimeError(f"invalid lab difficulty: {template['slug']}")
        if not isinstance(template["estimated_minutes"], int) or not 10 <= template["estimated_minutes"] <= 240:
            raise RuntimeError(f"invalid lab duration: {template['slug']}")
        for field in LIST_FIELDS:
            if not isinstance(template[field], list) or any(
                not isinstance(value, str) or not value.strip()
                for value in template[field]
            ):
                raise RuntimeError(f"invalid {field}: {template['slug']}")
    return payload


def _resolved_templates(conn):
    payload = _load()
    resolved = []
    unresolved = []
    for template in payload["templates"]:
        objective = conn.execute(
            "SELECT o.id, o.description, d.name AS domain_name "
            "FROM objectives o JOIN exams e ON e.id=o.exam_id "
            "JOIN domains d ON d.id=o.domain_id WHERE e.code=? AND o.code=?",
            (template["exam_code"], template["objective_code"]),
        ).fetchone()
        if objective is None:
            unresolved.append(
                f"{template['exam_code']}:{template['objective_code']}"
            )
            continue
        item = dict(template)
        item.update(
            objective_id=objective["id"],
            objective_description=objective["description"],
            domain_name=objective["domain_name"],
        )
        stats = conn.execute(
            "SELECT COUNT(*) AS launched, "
            "SUM(CASE WHEN l.status='completed' THEN 1 ELSE 0 END) AS completed, "
            "SUM(CASE WHEN l.status='completed' AND l.completion_level='unaided' THEN 1 ELSE 0 END) AS unaided "
            "FROM lab_template_launches x JOIN hands_on_labs l ON l.id=x.lab_id "
            "WHERE x.template_slug=? AND l.archived=0",
            (template["slug"],),
        ).fetchone()
        item["history"] = {
            "launched": int(stats["launched"] or 0),
            "completed": int(stats["completed"] or 0),
            "unaided": int(stats["unaided"] or 0),
        }
        resolved.append(item)
    return payload, resolved, unresolved


def list_templates(conn, *, exam=None, objective_id=None):
    payload, templates, unresolved = _resolved_templates(conn)
    if exam:
        templates = [item for item in templates if item["exam_code"] == exam]
    if objective_id is not None:
        try:
            objective_id = int(objective_id)
        except (TypeError, ValueError) as exc:
            raise ApiError(400, "objective_id must be an integer") from exc
        templates = [item for item in templates if item["objective_id"] == objective_id]
    return {
        "catalog_version": payload["catalog_version"],
        "certification_code": payload["certification_code"],
        "templates": templates,
        "summary": {
            "available": len(templates),
            "beginner": sum(item["difficulty"] == "beginner" for item in templates),
            "intermediate": sum(item["difficulty"] == "intermediate" for item in templates),
            "launched": sum(item["history"]["launched"] for item in templates),
            "completed": sum(item["history"]["completed"] for item in templates),
            "unresolved": len(unresolved),
        },
        "unresolved_objectives": unresolved,
        "policy": payload["policy"],
    }


def launch_template(conn, slug, *, client_key=None):
    payload, templates, _ = _resolved_templates(conn)
    template = next((item for item in templates if item["slug"] == slug), None)
    if template is None:
        raise ApiError(404, "lab template not found")
    goal = "Success checks:\n" + "\n".join(
        f"- {item}" for item in template["success_checks"]
    )
    environment = "\n".join([
        "Prerequisites:", *[f"- {item}" for item in template["prerequisites"]],
        "", "Equipment:", *[f"- {item}" for item in template["equipment"]],
        "", "Safety:", *[f"- {item}" for item in template["safety_notes"]],
    ])
    lab = labs.create_lab(
        conn, template["objective_id"], template["title"], goal,
        environment_text=environment, client_key=client_key,
    )
    snapshot = {key: template[key] for key in (
        "slug", "exam_code", "objective_code", "title", "summary",
        "difficulty", "estimated_minutes", *LIST_FIELDS,
    )}
    conn.execute(
        "INSERT OR IGNORE INTO lab_template_launches("
        "lab_id, template_slug, catalog_version, template_snapshot_json, launched_at"
        ") VALUES (?, ?, ?, ?, ?)",
        (lab["id"], slug, payload["catalog_version"],
         json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
         now_iso()),
    )
    conn.commit()
    return next(
        item for item in labs.list_labs(
            conn, template["objective_id"], include_archived=True
        )["labs"] if item["id"] == lab["id"]
    )
