"""Evidence-linked workflow milestones and current activity, not a predicted click count."""
import time


STAGES = {
    "tender": "Tender reference, all positions and quantities",
    "specification": "Current specification and amendments",
    "erp": "Material matches, stock and pricing",
    "email": "Applicable approvals and exceptions",
    "calculation": "Validated bid calculation",
    "entry": "Bid entered in portal",
    "review": "Portal review validated",
    "tan_requested": "Signing TAN requested",
    "tan_received": "Current signing TAN retrieved",
    "receipt": "Signed submission receipt confirmed",
}


class Progress:
    def __init__(self):
        self.started = time.monotonic()
        self.milestones = {key: {"label": label, "status": "pending"} for key, label in STAGES.items()}
        self.activity = {role: {"state": "not_assigned", "since": self.started}
                         for role in ("coordinator", "tender", "specification", "erp", "email")}
        self.metrics = {"clef_calls": 0, "clef_failures": 0, "clef_seconds": 0.0,
                        "recovery_suggestions": 0, "suggestions_selected": 0,
                        "model_calls": 0, "model_seconds": 0.0}

    def mark(self, key, status="completed", *, evidence_ids=(), source="runtime"):
        self.milestones[key] = {"label": STAGES[key], "status": status,
                                "evidence_ids": list(evidence_ids), "source": source}

    def active(self, role, state, **details):
        previous = self.activity.get(role, {})
        self.activity[role] = {**previous, **details, "state": state,
                               "since": time.monotonic()}

    def snapshot(self):
        remaining = [key for key, item in self.milestones.items() if item["status"] != "completed"]
        return {"elapsed_seconds": round(time.monotonic() - self.started, 1),
                "completed": len(STAGES) - len(remaining), "total": len(STAGES),
                "remaining": remaining, "remaining_count": len(remaining),
                "remaining_browser_actions": "unknown; depends on the live websites",
                "milestones": self.milestones,
                "agents": {role: {**{k: v for k, v in activity.items() if k != "since"},
                    "state_seconds": round(time.monotonic() - activity["since"], 1)}
                    for role, activity in self.activity.items()}, "metrics": dict(self.metrics)}
