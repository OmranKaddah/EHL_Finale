"""Named model tools avoid requiring a second, nested action discriminator."""
from __future__ import annotations


def model_tools(*, exclude: set[str] | frozenset[str] = frozenset()):
    specs = {
        "navigate": ("Visit an observed link or runtime site URL", {"url": "string", "new_tab": "boolean"}, ["url"]),
        "click": ("Click a current observed control", {"ref": "string"}, ["ref"]),
        "fill": ("Fill with text, an opaque credential handle, or captured TAN", {"ref": "string", "text": "string", "secret": "string", "tan": "boolean"}, ["ref"]),
        "select": ("Select an observed option", {"ref": "string", "label": "string", "value": "string"}, ["ref"]),
        "check": ("Set an observed checkbox", {"ref": "string", "checked": "boolean"}, ["ref"]),
        "press": ("Press a key on an observed control", {"ref": "string", "key": "string"}, ["ref", "key"]),
        "scroll": ("Scroll the selected frame", {"pixels": "integer"}, []),
        "tab": ("Switch to an observed tab", {"tab": "integer"}, ["tab"]),
        "frame": ("Select an observed frame for scrolling", {"frame": "integer"}, ["frame"]),
        "observe": ("Refresh the visible page", {}, []),
        "wait": ("Wait at most five seconds for a transient UI change", {"seconds": "number"}, []),
        "screenshot": ("Get a fresh masked screenshot", {}, []),
        "pixel_click": ("Click coordinates grounded in the current screenshot", {"observation": "string", "x": "integer", "y": "integer"}, ["observation", "x", "y"]),
        "drag": ("Drag a slider/unlock handle to the right or onto a target", {"ref": "string", "to_ref": "string", "dx": "integer", "dy": "integer", "observation": "string", "x": "integer", "y": "integer", "to_x": "integer", "to_y": "integer"}, []),
        "dialog": ("Respond to the current browser dialog", {"accept": "boolean"}, ["accept"]),
        "inspect_controls": ("Inspect selected independent disclosures and return durable before/after citation candidates", {"refs": "array:string"}, ["refs"]),
        "read_links": ("Read up to six explicitly selected record links from the current result set", {"refs": "array:string"}, ["refs"]),
        "document": ("Read a selected downloaded document or ZIP member", {"id": "string", "member": "string", "page": "integer"}, ["id"]),
        "cite": ("Create evidence from exact observed excerpts", {"observation": "string", "excerpt": "string", "scope": "object", "citations": "array:object"}, []),
        # Keep the model-facing contract deliberately singular.  Earlier
        # compatibility support for ``records`` made the function schema
        # contradictory (kind/data were required while a batch was offered),
        # and Qwen sometimes mixed both envelopes.  The parser still accepts
        # historical batched traces, but a live model now has one unambiguous
        # way to publish a typed, cited fact.
        "record": ("Validate one typed record with inline citations. kind and data are required; data needs id", {"kind": "string", "data": "object", "citations": "array:object"}, ["kind", "data"]),
        "schema": ("Read exact schemas for unfamiliar record fields", {"kind": "string", "kinds": "array:string"}, []),
        "inspect_evidence": ("Reread a retained observation or the evidence ledger", {"observation": "string"}, []),
        "calculate": ("Calculate deterministic prices from verified evidence", {"partial": "boolean"}, []),
        "prepare_submission": ("Validate the calculated answer against this run's schema", {"partial": "boolean"}, []),
        "fill_answer": ("Fill computed answer paths into observed form fields", {"fields": "array:object"}, ["fields"]),
        "request_tan": ("Request a new TAN only when the answer is ready", {"ref": "string"}, ["ref"]),
        "capture_tan": ("Capture the current matching signing message without exposing its TAN", {"observation": "string"}, ["observation"]),
        "sign": ("Sign after reviewing values and omissions", {"ref": "string", "reviewed": "boolean", "omissions_confirmed": "boolean"}, ["ref", "reviewed", "omissions_confirmed"]),
        "receipt": ("Verify current final acceptance on the submission website", {"observation": "string", "receipt_id": "string", "excerpt": "string"}, ["observation", "receipt_id", "excerpt"]),
        "api_submit": ("Submit only when runtime explicitly declares an API target", {}, []),
        "stage": ("Report investigation, pricing or submission progress", {"stage": "string"}, ["stage"]),
    }
    result = []
    for name, (description, fields, required) in specs.items():
        if name in exclude:
            continue
        properties = {"summary": {"type": "string", "maxLength": 500, "description": "Short observable purpose"}}
        for key, kind in fields.items():
            properties[key] = {"type": "array", "items": {"type": kind.split(":")[1]}} if kind.startswith("array:") else {"type": kind}
        result.append({"type": "function", "function": {"name": name, "description": description,
                       "parameters": {"type": "object", "properties": properties, "required": required, "additionalProperties": False}}})
    return result
