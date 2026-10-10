from atira_agent.contracts import AgentAction, Observation
from atira_agent.orchestrator import action_signature


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
