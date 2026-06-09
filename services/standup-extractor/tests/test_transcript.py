"""Unit tests for transcript grouping + roster mapping + envelope parsing."""
from app import schema
from app.transcript import group_by_speaker, participant_names, render_transcript


def _seg(start, text, speaker):
    # mimic the internal endpoint's alias-serialized shape (start/end aliases)
    return {"start": start, "end": start + 1, "text": text, "speaker": speaker}


def test_group_merges_consecutive_same_speaker_and_orders():
    segs = [
        _seg(2.0, "world", "Alice"),
        _seg(0.0, "Hello", "Alice"),
        _seg(3.0, "Hi all", "Bob"),
        _seg(4.0, "back to me", "Alice"),
    ]
    blocks = group_by_speaker(segs)
    assert [b["speaker"] for b in blocks] == ["Alice", "Bob", "Alice"]
    assert blocks[0]["text"] == "Hello world"          # merged + ordered by start
    assert blocks[2]["text"] == "back to me"


def test_group_skips_empty_and_handles_missing_speaker():
    segs = [_seg(0.0, "  ", "Alice"), {"start": 1.0, "text": "anon", "speaker": None}]
    blocks = group_by_speaker(segs)
    assert len(blocks) == 1
    assert blocks[0]["speaker"] == "Unknown speaker"


def test_roster_mapping_and_render():
    blocks = [{"speaker": "spk_1", "text": "did x"}, {"speaker": "Bob", "text": "did y"}]
    roster = {"spk_1": "Alice"}
    assert participant_names(blocks, roster) == ["Alice", "Bob"]
    rendered = render_transcript(blocks, roster)
    assert rendered == "Alice: did x\nBob: did y"


def test_extract_meeting_id_and_fields():
    env = {"event_type": "meeting.completed", "event_id": "evt_1",
           "data": {"meeting": {"id": 16, "platform": "google_meet", "user_email": "a@b.c"}}}
    assert schema.extract_meeting_id(env) == 16
    assert schema.meeting_field(env, "platform") == "google_meet"
    assert schema.extract_meeting_id({"data": {}}) is None


def test_response_format_is_strict_json_schema():
    rf = schema.response_format()
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["strict"] is True
    props = rf["json_schema"]["schema"]["properties"]["people"]["items"]["properties"]
    assert set(props) == {"name", "yesterday", "today", "blockers"}
