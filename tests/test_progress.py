from atira_agent.contracts import AgentAction, Observation
from atira_agent.orchestrator import action_signature, navigation_allowed, navigation_target


def signature(oid, index, text="Rows A and B"):
    ref = f"{oid}-f2-e{index}"
    obs = Observation(id=oid, action_id=1, tab=0, url="https://synthetic.test/table", title="Rows", text=text,
                      controls=[{"ref": ref, "label": "Reveal date", "frame": 2, "type": "button"}])
    return action_signature(AgentAction(action="click", summary="Reveal date", args={"ref": ref}), obs)


def test_same_labels_in_distinct_rows_are_not_repeated_action():
    assert signature("o1", 0) != signature("o2", 2)


def test_new_observation_id_does_not_hide_unchanged_retry():
    assert signature("o1", 0) == signature("o2", 0)


def test_pagination_and_newly_revealed_content_count_as_progress():
    assert signature("o1", 0, "Page 1") != signature("o2", 0, "Page 2")


def test_filled_state_allows_one_legitimate_session_relogin_step():
    action = AgentAction(action="fill", summary="Enter password", args={"ref": "o1-f0-e0", "secret": "portal:password"})
    resumed = AgentAction(action="fill", summary="Enter password", args={"ref": "o2-f0-e0", "secret": "portal:password"})
    base = dict(action_id=1, tab=0, url="https://synthetic.test/login", title="Login", text="Session expired")
    blank = Observation(id="o1", controls=[{"ref": "o1-f0-e0", "label": "Password", "filled": False}], **base)
    filled = Observation(id="o2", controls=[{"ref": "o2-f0-e0", "label": "Password", "filled": True}], **base)
    assert action_signature(action, blank) != action_signature(resumed, filled)


def test_explicit_navigation_cycle_allows_one_retry_then_stops():
    obs = Observation(id="o1", action_id=1, tab=0, url="https://synthetic.test/documents", title="Docs", text="Page")
    action = AgentAction(action="navigate", summary="Open requirement", args={"url": "/specification#section-2"})
    target = navigation_target(action, obs)
    assert target == "https://synthetic.test/specification"
    assert navigation_allowed([target], target)
    assert not navigation_allowed([target, target], target)
