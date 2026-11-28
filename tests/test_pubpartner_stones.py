"""Stepping stones: reading, storing, recalling and rebuilding sentence-sized memories (2026-11-28).

Deterministic, local, no network, no model, no CI service. Three layers:
  * the reader (modules/pubpartner_stone_text.py): exact spans, honest unknowns, hostile input;
  * the store (modules/pubpartner_stones.py): rarity-weighted recall with reasons, isolation, rebuild from the vault;
  * the spine: recall and fusion inside a real turn, privacy of audiences, and a failure never blocking a turn.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import modules.pubpartner_core as core
from modules.pubpartner_core import MemoryRef, PubPartnerSpine, VerbatimVault
from modules.pubpartner_memory_map import build_memory_map
from modules.pubpartner_stone_text import (
    SLOTS, ground_proposed_answers, grounding_problems, read_message, split_sentences, terms,
)
from modules.pubpartner_stones import FusionItem, StoneLibrary, StoneStore, explain, fuse, sync_from_vault

BASE = dict(user_id="u", friend="alex", provider={"provider": "mock"}, project_id="p", room_id="phone")
DAY = 86400.0
NOW = 1_795_000_000.0  # a fixed "now" so ranking tests do not depend on the clock


@pytest.fixture(autouse=True)
def no_identity_pause(monkeypatch):
    real = core.identity_checkpoint
    monkeypatch.setattr(core, "identity_checkpoint", lambda turn, number, **kw: real(turn, number, minimum_seconds=0.0))


def answers_of(text, **kw):
    return [d for d in read_message(text, **kw)]


def stated(draft, slot):
    answer = draft.answers[slot]
    return [f.text for f in answer.fragments] if answer.state == "stated" else None


def make_store(tmp_path, user="josie", friend="alex"):
    return StoneLibrary(tmp_path).store(user, friend)


def add(store, source_id, text, *, age_days=0.0, project="p", room="phone", session="s1"):
    return store.ingest(source_id=source_id, session_id=session, text=text, created_at=NOW - age_days * DAY,
                        project_id=project, room_id=room)


def sid(n):
    return f"src_{n}_{n:012x}_{n:08x}"


# ═════════════════════════════════════ the reader ═════════════════════════════════════

CORPUS = [
    "After rehearsal, I moved the guest mic closer. I hoped people could hear her better.",
    "My friend Sam loves baseball. Sam's team is the Dodgers. Sam loves strawberry sherbet ice cream.",
    "I moved it by turning the dial because the room was loud, at 3pm yesterday in the Studio. Maybe it helped?",
    "Dr. Smith said e.g. the mic was fine. U.S. stuff happens. I gave it to Sam. We met in Lisbon in 2019, after the show.",
    "Привет, я сегодня устал после работы в студии.",
    "我今天很累。因为工作太多了",
    "Ünïcode café São Paulo naïve résumé. Zoë's flight lands on 2026-12-03 at 7:45 pm!",
    'She said "never again, not ever" and left.\nWhat if we moved the stage? If only it were quiet.',
    "line one\r\nline two\r\n\r\n\ttabbed   and   spaced   words with trailing space   ",
    "😀 emoji 🎤 mic check, one two. 𝔘𝔫𝔦𝔠𝔬𝔡𝔢 math letters. ｆｕｌｌｗｉｄｔｈ text.",
]


@pytest.mark.parametrize("text", CORPUS)
def test_every_filled_answer_is_an_exact_span_of_the_message(text):
    drafts = answers_of(text)
    assert drafts, "the corpus is chosen so that each message makes at least one stone"
    for draft in drafts:
        assert grounding_problems(text, draft) == []
        for slot in SLOTS:
            answer = draft.answers[slot]
            assert answer.state in {"stated", "unknown"}
            for fragment in answer.fragments:
                assert text[fragment.start:fragment.end] == fragment.text
                assert draft.start <= fragment.start < fragment.end <= draft.end


def test_what_is_always_the_whole_sentence_and_the_rest_is_unknown_unless_said():
    (draft,) = answers_of("My friend Sam loves baseball.")
    assert stated(draft, "what") == ["My friend Sam loves baseball."]
    assert stated(draft, "who") == ["My friend", "Sam"]
    for slot in ("where", "when", "why", "how"):
        assert draft.answers[slot].state == "unknown", slot


def test_a_name_is_stored_the_way_it_will_be_searched_plural_looking_multi_word_and_hyphenated():
    text = "My friend Sam Houston loves the Dodgers. I met Jean-Luc and James in New York on Monday."
    first, second = answers_of(text)
    assert first.name_terms == ("sam", "houston", "dodger")   # "Dodgers" and a search for "Dodger's" are the same word
    assert second.name_terms == ("jean", "luc", "jame", "new", "york")  # a day name is not a person
    assert second.place_terms == ("new", "york")
    assert stated(second, "who") == ["I", "Jean-Luc", "James"]  # the place has its own answer
    assert stated(second, "where") == ["in New York"]
    for draft in (first, second):
        assert grounding_problems(text, draft) == []


def test_a_name_that_is_only_ever_the_first_word_of_a_sentence_is_not_guessed_but_is_still_findable():
    # "Sam" opening the first sentence looks exactly like any capitalized word, so who stays unknown (not guessed);
    # the word itself is still searchable, and the name is learned the first time it appears mid-sentence or twice.
    (draft,) = answers_of("Sam loves baseball.")
    assert draft.answers["who"].state == "unknown" and draft.name_terms == ()
    assert "sam" in draft.word_terms
    (known,) = answers_of("Sam loves baseball.", known_names={"sam"})
    assert stated(known, "who") == ["Sam"] and known.name_terms == ("sam",)


def test_a_hope_is_recorded_as_a_motive_and_not_as_a_reason_or_a_result():
    first, second = answers_of("After rehearsal, I moved the guest mic closer. I hoped people could hear her better.")
    assert stated(first, "when") == ["After rehearsal"]
    assert first.answers["why"].state == "unknown"
    assert second.answers["why"].mode == "motive"
    assert stated(second, "why") == ["I hoped people could hear her better"]
    assert second.unresolved_reference is True  # "her" is not tied to anyone in this sentence


def test_a_stated_reason_and_manner_stop_at_their_clause_and_a_place_is_not_a_who():
    first, second = answers_of("I moved it by turning the dial because the room was loud, at 3pm yesterday in the Studio. Maybe it helped?")
    assert stated(first, "how") == ["by turning the dial"]
    assert stated(first, "why") == ["because the room was loud"]
    assert first.answers["why"].mode == "reason"
    assert stated(first, "where") == ["in the Studio"]
    assert stated(first, "who") == ["I"]  # Studio answers where, and is not also listed as a person
    assert stated(first, "when") == ["3pm", "yesterday"]
    assert second.modality == "question"


def test_lasting_facts_and_one_day_statements_are_told_apart():
    loves, lost = answers_of("Sam loves baseball. Sam's team lost today.")
    assert loves.temporal == "lasting" and loves.expires_after_seconds is None
    assert lost.temporal == "situational" and lost.expires_after_seconds and lost.expires_after_seconds < 3 * DAY


def test_questions_guesses_and_what_ifs_are_marked_so_they_are_not_read_as_facts():
    drafts = answers_of("Is the Studio too small? Maybe the mic is broken. What if we moved the stage?")
    assert [d.modality for d in drafts] == ["question", "tentative", "question"]
    (hypo,) = answers_of("If only it were quiet in here tonight.")
    assert hypo.modality == "hypothetical"


def test_a_name_seen_mid_message_is_still_a_name_at_the_start_of_another_sentence():
    drafts = answers_of("I told Sam about it. Sam loved the idea.")
    assert [d.name_terms for d in drafts] == [("sam",), ("sam",)]
    assert stated(drafts[1], "who") == ["Sam"]


def test_abbreviations_do_not_split_sentences_and_cjk_full_stops_do():
    spans = split_sentences("Dr. Smith said e.g. the mic was fine. U.S. stuff happens.")
    assert len(spans) == 2
    assert len(split_sentences("我今天很累。因为工作太多了")) == 2
    assert len(split_sentences("Wait... Really?! Yes. (Done.) He said \"stop.\" Then left.")) == 6


def test_other_languages_get_word_recall_but_every_english_only_question_stays_unknown():
    (draft,) = answers_of("Привет, я сегодня устал после работы в студии.", language="ru")
    assert draft.reading == "words_only"
    assert "студии" in draft.word_terms
    assert [draft.answers[s].state for s in ("who", "where", "when", "why", "how")] == ["unknown"] * 5
    assert draft.temporal == "unknown"


def test_terms_fold_case_accents_width_and_plurals_without_inventing_words():
    assert terms("Dodgers DODGER's dodger") == ["dodger"]
    assert terms("ｆｕｌｌｗｉｄｔｈ") == ["fullwidth"]
    assert terms("the and of to") == []
    assert terms("x" * 100) == []  # one unbroken blob is not a word


def test_a_proposed_answer_is_accepted_only_if_the_person_really_said_those_words():
    sentence = "I hoped  people could hear her better."
    accepted, rejected = ground_proposed_answers(
        sentence, {"why": "People could hear her BETTER", "how": "by using magic", "when": "", "mood": "sad"})
    fragment = accepted["why"]
    assert sentence[fragment.start:fragment.end] == fragment.text == "people could hear her better"
    assert rejected["how"] == "these words are not in the sentence"
    assert rejected["when"] == "empty"
    assert rejected["mood"] == "not one of the six questions"
    squashed, _ = ground_proposed_answers(sentence, {"what": "hoped people"})
    assert squashed["what"].text == "hoped  people"  # the person's own spacing comes back, not the claim's


@pytest.mark.parametrize("name,text", [
    ("dots", "." * 200_000), ("dotted", "a." * 50_000), ("blob", "x" * 300_000), ("newlines", "\n" * 100_000),
    ("closers", ".)" * 100_000 + " end"), ("quotes", '."' * 100_000), ("caps", "A" * 100_000),
    ("apostrophes", "a'" * 100_000), ("repeat-name", "Sam " * 50_000 + "lost."), ("because", "because " * 20_000),
    ("by", "by running " * 20_000), ("after", "after " * 30_000), ("cjk", "。" * 100_000),
])
def test_hostile_input_is_read_quickly_and_bounded(name, text):
    started = time.perf_counter()
    drafts = read_message(text)
    assert time.perf_counter() - started < 5.0, name
    assert len(drafts) <= 60
    for draft in drafts:
        assert len(draft.excerpt) <= 700
        assert grounding_problems(text[:200_000], draft) == []


# ═════════════════════════════════════ the store ═════════════════════════════════════

def test_ingest_is_idempotent_checks_the_hash_and_skips_what_is_not_conversation(tmp_path):
    store = make_store(tmp_path)
    assert add(store, sid(1), "Sam loves baseball.")["status"] == "ingested"
    assert add(store, sid(1), "Sam loves baseball.")["status"] == "already_ingested"
    assert store.status()["stones"] == 1
    refused = store.ingest(source_id=sid(2), session_id="s", text="Hello there friend.", created_at=NOW, sha256="0" * 64)
    assert refused["status"] == "refused" and not store.has_source(sid(2))
    code = store.ingest(source_id=sid(3), session_id="s", text="def f():\n    return 1", created_at=NOW, kind="code")
    assert code["status"] == "skipped" and not store.has_source(sid(3))
    assert store.ingest(source_id=sid(4), session_id="s", text="   \n ", created_at=NOW)["status"] == "skipped"


def test_baseball_and_sherbet_a_name_in_the_news_brings_back_what_is_known_about_that_person(tmp_path):
    store = make_store(tmp_path)
    add(store, sid(1), "My friend Sam loves baseball. Sam's team is the Dodgers. Sam loves strawberry sherbet ice cream.", age_days=20)
    add(store, sid(2), "I moved the guest mic closer after rehearsal.", age_days=10)
    add(store, sid(3), "I need to fix the orchid project database port.", age_days=5)
    found = store.recall("The Dodgers lost today and everyone is miserable", now=NOW)
    texts = [(item.ring, item.excerpt) for item in found]
    assert (1, "Sam's team is the Dodgers.") in texts
    ring_two = {item.excerpt: item for item in found if item.ring == 2}
    assert "Sam loves strawberry sherbet ice cream." in ring_two
    assert "My friend Sam loves baseball." in ring_two
    assert all(item.via == "sam" for item in ring_two.values())
    assert not any("mic" in item.excerpt or "orchid" in item.excerpt for item in found)
    for item in found:
        assert explain(item)  # every recalled memory says why


def test_a_name_gets_the_name_boost_even_when_it_ends_in_s_or_has_two_words(tmp_path):
    store = make_store(tmp_path)
    add(store, sid(1), "My friend Sam Houston loves the Dodgers.")
    import sqlite3
    conn = sqlite3.connect(str(store.path))
    kinds = {term: kind for term, kind in conn.execute("SELECT term, kind FROM terms WHERE kind = 'n'")}
    conn.close()
    assert {"sam", "houston", "dodger"} <= set(kinds)
    for query in ("Dodgers", "Houston", "the Dodger's lineup"):
        (hit,) = store.recall(query, now=NOW)
        assert hit.excerpt == "My friend Sam Houston loves the Dodgers."


def test_a_word_everyone_uses_cannot_recall_anything_by_itself_but_a_rare_one_can(tmp_path):
    store = make_store(tmp_path)
    for n in range(40):
        add(store, sid(n), f"The project uses port {4000 + n} for the database.")
    add(store, sid(99), "The orchid greenhouse needs misting.")
    assert store.recall("the project", now=NOW) == []
    found = store.recall("how is the orchid project doing", now=NOW)
    assert found and found[0].excerpt == "The orchid greenhouse needs misting."
    assert found[0].matched == ["orchid"]


def test_matching_is_by_whole_words_not_by_letters_inside_other_words(tmp_path):
    store = make_store(tmp_path)
    add(store, sid(1), "This is important to the whole team.")
    add(store, sid(2), "Port 4417 is open on the router.")
    found = store.recall("which port is open", now=NOW)
    assert [item.excerpt for item in found] == ["Port 4417 is open on the router."]


def test_a_statement_about_one_day_fades_after_that_day_and_says_so(tmp_path):
    store = make_store(tmp_path)
    add(store, sid(1), "Sam's team lost today and he is upset.", age_days=10)
    add(store, sid(2), "Sam loves baseball and his team is the Dodgers.", age_days=10)
    found = store.recall("how is Sam's team doing", now=NOW)
    by_text = {item.excerpt: item for item in found}
    old_day = by_text["Sam's team lost today and he is upset."]
    lasting = by_text["Sam loves baseball and his team is the Dodgers."]
    assert old_day.expired is True and old_day.score < lasting.score
    assert "may be out of date" in explain(old_day)
    fresh = store.recall("how is Sam's team doing", now=NOW - 9.5 * DAY)
    assert {i.excerpt: i for i in fresh}["Sam's team lost today and he is upset."].expired is False


def test_a_question_or_a_what_if_is_never_pulled_in_as_something_known_about_a_person(tmp_path):
    store = make_store(tmp_path)
    add(store, sid(1), "Sam loves baseball. Is Sam coming to the studio on Friday? What if Sam moved to Boston?")
    found = store.recall("baseball season starts", now=NOW)
    ring_two = [item.excerpt for item in found if item.ring == 2]
    assert not any("?" in text for text in ring_two)


def test_non_english_text_is_recalled_by_its_own_words(tmp_path):
    store = make_store(tmp_path)
    store.ingest(source_id=sid(1), session_id="s", text="Привет, я сегодня устал после работы в студии.", created_at=NOW, language="ru")
    store.ingest(source_id=sid(2), session_id="s", text="我今天很累。因为工作太多了", created_at=NOW, language="zh")
    assert [i.excerpt for i in store.recall("работы в студии", now=NOW)] == ["Привет, я сегодня устал после работы в студии."]
    assert store.recall("工作太多", now=NOW)[0].excerpt == "因为工作太多了"


def test_each_person_and_friend_has_their_own_file_and_nothing_crosses(tmp_path):
    library = StoneLibrary(tmp_path)
    one, two = library.store("alice", "alex"), library.store("bob", "alex")
    other_friend = library.store("alice", "cadence")
    add(one, sid(1), "Alice keeps a secret garden in Lisbon.")
    add(two, sid(2), "Bob keeps a secret workshop in Lisbon.")
    add(other_friend, sid(3), "Alice told Cadence about the Lisbon garden.")
    assert [i.excerpt for i in two.recall("secret garden Lisbon", now=NOW)] == ["Bob keeps a secret workshop in Lisbon."]
    assert [i.excerpt for i in one.recall("workshop", now=NOW)] == []
    assert len({library.path_for("alice", "alex"), library.path_for("bob", "alex"), library.path_for("alice", "cadence")}) == 3
    # two ids that read alike once cleaned up must still be different files
    assert library.path_for("a/b", "alex") != library.path_for("a_b", "alex")
    assert library.path_for("../../etc", "alex").resolve().is_relative_to(library.root.resolve())


def test_hosts_that_isolate_memory_by_project_and_room_get_the_same_isolation(tmp_path):
    store = make_store(tmp_path)
    add(store, sid(1), "The Orchid stage plan uses two microphones.", project="orchid", room="stage")
    add(store, sid(2), "The Orchid dinner plan uses two tables.", project="dinner", room="home")
    assert len(store.recall("Orchid plan", now=NOW)) == 2
    only = store.recall("Orchid plan", now=NOW, project_id="orchid", room_id="stage")
    assert [i.excerpt for i in only] == ["The Orchid stage plan uses two microphones."]


def test_a_stone_already_in_the_visible_conversation_is_not_offered_again(tmp_path):
    store = make_store(tmp_path)
    add(store, sid(1), "The guest microphone feeds back near the speakers.")
    assert store.recall("guest microphone feedback", now=NOW)
    shown = ["user said: The guest microphone feeds back near the speakers. Can you help?"]
    assert store.recall("guest microphone feedback", now=NOW, skip_if_in=shown) == []


def test_marking_a_memory_as_shown_counts_it_without_changing_the_order(tmp_path):
    store = make_store(tmp_path)
    add(store, sid(1), "Sam loves baseball.")
    add(store, sid(2), "Sam loves tennis.")
    before = [i.stone_id for i in store.recall("Sam loves", now=NOW)]
    assert store.mark_surfaced(before, now=NOW) == len(before)
    assert [i.stone_id for i in store.recall("Sam loves", now=NOW)] == before
    rows = store.stones_for_source(sid(1))
    assert rows[0]["surfaced_count"] == 1 and rows[0]["last_surfaced_at"] == NOW


def test_status_says_how_often_each_question_could_be_answered(tmp_path):
    store = make_store(tmp_path)
    add(store, sid(1), "Sam loves baseball. After rehearsal I moved the mic.")
    status = store.status()
    assert status["stones"] == 2 and status["slots_stated"]["what"] == 2
    assert status["slots_stated"]["where"] == 0 and status["slots_stated"]["how"] == 0
    assert status["slots_stated"]["when"] == 1


def test_a_database_from_a_newer_version_is_refused_rather_than_touched(tmp_path):
    store = make_store(tmp_path)
    import sqlite3
    conn = sqlite3.connect(str(store.path))
    conn.execute("PRAGMA user_version = 99")
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError, match="newer version"):
        StoneStore(store.path, user_id="josie", friend_id="alex")


# ═════════════════════════════════════ fusion ═════════════════════════════════════

def items(prefix, n, source=""):
    return [FusionItem(key=f"{prefix}{i}", source_id=source, payload=f"{prefix}{i}") for i in range(n)]


def test_fusion_drops_a_pointer_to_a_message_whose_sentence_is_already_there_and_the_message_being_answered():
    covered, current = sid(1), sid(2)
    stones = [FusionItem(key="Sam loves baseball.", source_id=covered, payload="stone-1")]
    jeremy = [
        FusionItem(key=f"Exact user turn preserved as {covered} sha256=ab kind=message: Sam loves baseball.", source_id="", payload="dup"),
        FusionItem(key=f"Exact user turn preserved as {current} sha256=cd kind=message: what about Sam", source_id="", payload="self"),
        FusionItem(key="A standing instruction the stones do not hold.", source_id="", payload="keep"),
    ]
    assert fuse(stones, jeremy, limit=6, exclude_source_ids=[current]) == ["stone-1", "keep"]


def test_fusion_always_leaves_room_for_what_only_jeremy_holds():
    merged = fuse(items("s", 10), items("j", 3), limit=6)
    assert len(merged) == 6
    assert [m for m in merged if m.startswith("j")] == ["j0", "j1"]  # one slot in three, never zero
    assert fuse(items("s", 10), [], limit=4) == ["s0", "s1", "s2", "s3"]
    assert fuse([], items("j", 3), limit=2) == ["j0", "j1"]
    assert fuse(items("s", 3), items("j", 3), limit=0) == []


# ═════════════════════════════════════ rebuild from the vault ═════════════════════════════════════

def vault_record(vault, text, *, user="u", session="s1", friend="alex", room="phone", audience="private", kind="message", extra=None):
    meta = {"project_id": "p", "room_id": room, "friend_id": friend}
    if audience is not None:
        meta["audience"] = audience
    meta.update(extra or {})
    return vault.store(user_id=user, session_id=session, text=text, kind=kind, language="en", metadata=meta)


def test_stones_can_be_rebuilt_from_the_vault_and_a_second_run_does_nothing(tmp_path):
    vault = VerbatimVault(tmp_path)
    vault_record(vault, "My friend Sam loves baseball. Sam loves strawberry sherbet ice cream.")
    vault_record(vault, "I moved the guest mic closer after rehearsal.", session="s2")
    library = StoneLibrary(tmp_path)
    first = sync_from_vault(library, vault, audience_of=lambda r: (r.metadata or {}).get("audience"))
    assert first["complete"] is True and first["ingested"] == 2 and first["stones"] == 3
    before = [(i.excerpt, i.ring) for i in library.store("u", "alex").recall("baseball", now=time.time() + 5)]
    again = sync_from_vault(library, vault, audience_of=lambda r: (r.metadata or {}).get("audience"))
    assert again["ingested"] == 0 and again["complete"] is True
    # delete everything derived, rebuild, and the same memories come back
    import shutil
    shutil.rmtree(library.root)
    fresh = StoneLibrary(tmp_path)
    sync_from_vault(fresh, vault, audience_of=lambda r: (r.metadata or {}).get("audience"))
    after = [(i.excerpt, i.ring) for i in fresh.store("u", "alex").recall("baseball", now=time.time() + 5)]
    assert after == before and before


def test_rebuild_admits_only_messages_proved_private_and_reports_the_rest(tmp_path):
    vault = VerbatimVault(tmp_path)
    vault_record(vault, "A private thought about the garden.")
    vault_record(vault, "A line said on the shared stage about the garden.", audience="shared", room="studio")
    vault_record(vault, "An old message with no recorded audience about the garden.", audience=None)
    vault_record(vault, "def garden():\n    return 1", kind="code")
    vault_record(vault, "A message with no friend about the garden.", extra={"friend_id": ""})
    library = StoneLibrary(tmp_path)
    result = sync_from_vault(library, vault, audience_of=lambda r: (r.metadata or {}).get("audience"))
    assert result["ingested"] == 1
    assert result["not_private"] == 1 and result["unverified"] == 1 and result["no_friend"] == 1
    assert result["not_message"] >= 1
    found = library.store("u", "alex").recall("garden", now=time.time() + 5)
    assert [i.excerpt for i in found] == ["A private thought about the garden."]


def test_rebuild_stops_at_its_time_budget_and_the_next_call_carries_on(tmp_path):
    vault = VerbatimVault(tmp_path)
    for n in range(6):
        vault_record(vault, f"Message number {n} talks about the harbor lantern.")
    library = StoneLibrary(tmp_path)
    audience = lambda r: (r.metadata or {}).get("audience")  # noqa: E731
    none_yet = sync_from_vault(library, vault, audience_of=audience, time_budget_s=0.0)
    assert none_yet["complete"] is False and none_yet["ingested"] == 0
    part = sync_from_vault(library, vault, audience_of=audience, max_sources=2)
    assert part["complete"] is False and part["ingested"] == 2
    rest = sync_from_vault(library, vault, audience_of=audience)
    assert rest["complete"] is True and rest["ingested"] == 4


def test_a_vault_record_that_fails_its_own_checks_is_never_read_around(tmp_path):
    vault = VerbatimVault(tmp_path)
    record = vault_record(vault, "Sam loves baseball and the Dodgers.")
    sidecar = next(Path(vault.root).rglob(f"{record.source_id}.utf8"))
    sidecar.write_bytes(b"Sam loves nothing at all.")
    library = StoneLibrary(tmp_path)
    result = sync_from_vault(library, vault, audience_of=lambda r: "private")
    assert result["unreadable"] == 1 and result["ingested"] == 0
    assert not library.stores_on_disk()


def test_deleting_one_persons_stones_file_makes_only_their_messages_be_read_again(tmp_path):
    vault = VerbatimVault(tmp_path)
    vault_record(vault, "Talking to Alex about the harbor lantern.", friend="alex")
    vault_record(vault, "Talking to Cadence about the harbor lantern.", friend="cadence", session="s2")
    library = StoneLibrary(tmp_path)
    audience = lambda r: (r.metadata or {}).get("audience")  # noqa: E731
    assert sync_from_vault(library, vault, audience_of=audience)["ingested"] == 2
    for leftover in library.path_for("u", "alex").parent.glob(library.path_for("u", "alex").name + "*"):
        leftover.unlink()
    library = StoneLibrary(tmp_path)  # a fresh process: nothing cached
    again = sync_from_vault(library, vault, audience_of=audience)
    assert again["ingested"] == 1 and again["already"] == 0
    assert library.store("u", "alex").recall("harbor lantern", now=time.time() + 5)
    assert sync_from_vault(library, vault, audience_of=audience)["ingested"] == 0


def test_unverified_messages_can_be_looked_at_again_when_asked(tmp_path):
    vault = VerbatimVault(tmp_path)
    vault_record(vault, "An old message about the harbor lantern.", audience=None)
    library = StoneLibrary(tmp_path)
    known = {"value": None}
    audience = lambda r: known["value"]  # noqa: E731
    assert sync_from_vault(library, vault, audience_of=audience)["unverified"] == 1
    known["value"] = "private"
    assert sync_from_vault(library, vault, audience_of=audience)["ingested"] == 0  # remembered as unverified
    assert sync_from_vault(library, vault, audience_of=audience, retry_unverified=True)["ingested"] == 1


# ═════════════════════════════════════ the spine ═════════════════════════════════════

def memories_of(turn):
    return (turn.get("fcp1") or {}).get("m") or []


@pytest.mark.asyncio
async def test_in_a_real_turn_a_name_brings_back_what_was_said_about_that_person_and_says_why(tmp_path):
    spine = PubPartnerSpine(tmp_path)
    await spine.run_turn(session_id="s1", message="My friend Sam loves baseball. Sam's team is the Dodgers. "
                         "Sam loves strawberry sherbet ice cream.", **BASE)
    await spine.run_turn(session_id="s1", message="I moved the guest mic closer after rehearsal.", **BASE)
    turn = await spine.build_turn_packet(session_id="s2", message="The Dodgers lost today and everyone is miserable.", **BASE)
    stone_refs = [m for m in memories_of(turn) if m["id"].startswith("stone:")]
    texts = [m["txt"] for m in stone_refs]
    assert "Sam's team is the Dodgers." in texts
    assert any("sherbet" in t for t in texts) and any("baseball" in t for t in texts)
    assert all(m["why"] and m["src"] == "pubpartner_stones" for m in stone_refs)
    assert not any("mic" in t for t in texts)
    assert turn["stones_status"]["status"] == "ok" and turn["stones_status"]["recalled"] == len(stone_refs)
    assert turn["stones_status"]["ring2"] >= 2


@pytest.mark.asyncio
async def test_the_message_being_answered_is_never_echoed_back_as_a_memory(tmp_path):
    from modules.jeremy_cricket import CricketKeeper

    keeper = CricketKeeper(data_dir=tmp_path / "jeremy")
    await keeper.init()
    try:
        for enabled in (True, False):
            spine = PubPartnerSpine(tmp_path / f"d{enabled}", cricket_keeper=keeper, stones_enabled=enabled)
            turn = await spine.build_turn_packet(
                session_id="s", message="The orchid greenhouse needs misting every morning.", **BASE)
            source_id = turn["source"]["id"]
            assert not any(source_id in m["txt"] for m in memories_of(turn)), f"stones_enabled={enabled}"
    finally:
        await keeper.close() if hasattr(keeper, "close") else None


@pytest.mark.asyncio
async def test_shared_rooms_neither_recall_nor_record_private_memories(tmp_path):
    spine = PubPartnerSpine(tmp_path)
    await spine.run_turn(session_id="s1", message="My friend Sam loves baseball and the Dodgers.", **BASE)
    shared = dict(BASE, room_id="studio")
    turn = await spine.build_turn_packet(session_id="s2", message="Who loves baseball and the Dodgers?", **shared)
    assert turn["stones_status"]["status"] == "not_private"
    assert not any(m["id"].startswith("stone:") for m in memories_of(turn))
    await spine.run_turn(session_id="s3", message="On stage we mention the Orchid greenhouse.", **shared)
    store = spine.stones.store("u", "alex")
    assert store.recall("Orchid greenhouse", now=time.time() + 5) == []
    # a client cannot turn a shared room private by asking
    sneaky = await spine.build_turn_packet(session_id="s4", message="Who loves baseball?", task={"audience": "private"}, **shared)
    assert sneaky["stones_status"]["status"] == "not_private"


@pytest.mark.asyncio
async def test_code_and_pasted_documents_are_not_turned_into_memories(tmp_path):
    spine = PubPartnerSpine(tmp_path)
    turn = await spine.build_turn_packet(session_id="s", message="def orchid():\n    return 'greenhouse'\n",
                                         content_kind="code", **BASE)
    assert turn["stones_status"]["status"] == "not_message"
    assert not spine.stones.stores_on_disk()


@pytest.mark.asyncio
async def test_with_stones_off_the_packet_is_exactly_what_it_was_before(tmp_path):
    spine = PubPartnerSpine(tmp_path, stones_enabled=False)
    await spine.run_turn(session_id="s1", message="My friend Sam loves baseball.", **BASE)
    turn = await spine.build_turn_packet(session_id="s2", message="Tell me about Sam and baseball.", **BASE)
    assert turn["stones_status"]["status"] == "disabled"
    assert all("why" not in m for m in memories_of(turn))
    assert not spine.stones.stores_on_disk()
    assert MemoryRef(id="a", kind="k", text="t").compact().keys() == {"id", "k", "imp", "src", "txt"}
    assert "why" in MemoryRef(id="a", kind="k", text="t", why="matched x").compact()


@pytest.mark.asyncio
async def test_the_environment_switch_turns_stones_off_for_the_whole_app(tmp_path, monkeypatch):
    for value in ("off", "0", "FALSE", " no "):
        monkeypatch.setenv("PUBPARTNER_STONES", value)
        assert PubPartnerSpine(tmp_path / value.strip()).stones_enabled is False
    monkeypatch.setenv("PUBPARTNER_STONES", "on")
    assert PubPartnerSpine(tmp_path / "on").stones_enabled is True
    monkeypatch.delenv("PUBPARTNER_STONES")
    assert PubPartnerSpine(tmp_path / "unset").stones_enabled is True
    assert PubPartnerSpine(tmp_path / "arg", stones_enabled=False).stones_enabled is False


@pytest.mark.asyncio
async def test_hosts_that_scope_memory_keep_each_project_and_room_apart(tmp_path):
    spine = PubPartnerSpine(tmp_path, scoped_memory=True)
    await spine.run_turn(session_id="s1", message="The Orchid stage plan uses two microphones.", **dict(BASE, project_id="orchid"))
    inside = await spine.build_turn_packet(session_id="s2", message="What is the Orchid plan?", **dict(BASE, project_id="orchid"))
    outside = await spine.build_turn_packet(session_id="s3", message="What is the Orchid plan?", **dict(BASE, project_id="dinner"))
    assert any(m["id"].startswith("stone:") for m in memories_of(inside))
    assert not any(m["id"].startswith("stone:") for m in memories_of(outside))
    unscoped = PubPartnerSpine(tmp_path / "other")
    await unscoped.run_turn(session_id="s1", message="The Orchid stage plan uses two microphones.", **dict(BASE, project_id="orchid"))
    across = await unscoped.build_turn_packet(session_id="s3", message="What is the Orchid plan?", **dict(BASE, project_id="dinner"))
    assert any(m["id"].startswith("stone:") for m in memories_of(across))


@pytest.mark.asyncio
async def test_a_failing_stone_store_never_blocks_the_turn_and_is_named(tmp_path, monkeypatch):
    spine = PubPartnerSpine(tmp_path)

    def boom(*args, **kwargs):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(StoneStore, "recall", boom)
    monkeypatch.setattr(StoneStore, "ingest", boom)
    result = await spine.run_turn(session_id="s", message="My friend Sam loves baseball.", **BASE)
    assert result["ok"] is True and result["friend_response"]
    problems = result["stones_status"]["problems"]
    assert any(p.startswith("recall:") for p in problems) and any(p.startswith("ingest:") for p in problems)


@pytest.mark.asyncio
async def test_an_unopenable_stone_store_is_reported_and_the_turn_continues(tmp_path):
    spine = PubPartnerSpine(tmp_path)
    blocker = tmp_path / "pubpartner" / "stones"
    blocker.parent.mkdir(parents=True, exist_ok=True)
    blocker.write_text("not a folder", encoding="utf-8")
    result = await spine.run_turn(session_id="s", message="My friend Sam loves baseball.", **BASE)
    assert result["ok"] is True
    assert result["stones_status"]["status"] == "unavailable"
    assert result["stones_status"]["problems"][0].startswith("open:")


@pytest.mark.asyncio
async def test_messages_saved_while_stones_were_off_become_recallable_after_sync(tmp_path):
    off = PubPartnerSpine(tmp_path, stones_enabled=False)
    await off.run_turn(session_id="s1", message="My friend Sam loves baseball. Sam's team is the Dodgers.", **BASE)
    await off.run_turn(session_id="s1", message="Quick note about the studio lights.", **dict(BASE, room_id="studio"))
    on = PubPartnerSpine(tmp_path)
    result = on.sync_stones(time_budget_s=10)
    assert result["status"] == "ok" and result["complete"] is True
    assert result["ingested"] == 1 and result["not_private"] == 1
    turn = await on.build_turn_packet(session_id="s9", message="The Dodgers lost today.", **BASE)
    assert any("Dodgers" in m["txt"] for m in memories_of(turn) if m["id"].startswith("stone:"))
    assert on.sync_stones(time_budget_s=10)["ingested"] == 0
    assert PubPartnerSpine(tmp_path, stones_enabled=False).sync_stones() == {"status": "disabled"}


@pytest.mark.asyncio
async def test_old_vault_records_without_a_recorded_audience_use_the_turn_log_or_stay_out(tmp_path):
    spine = PubPartnerSpine(tmp_path)
    log = spine.session_dir / "u_s1_turns.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for text, room, task in [
        ("Private old note about the harbor lantern.", "phone", {}),
        ("Old note from a private room that asked to be shared about the harbor lantern.", "phone", {"audience": "shared"}),
        ("Old note with no log row about the harbor lantern.", None, None),
    ]:
        record = vault_record(spine.vault, text, audience=None, room=room or "phone")
        if room is not None:
            rows.append({"source": {"id": record.source_id}, "fcp1": {"proj": {"room": room}, "task": task}})
    log.write_text("\n".join(json.dumps(r) for r in rows) + "\nthis line is not json\n", encoding="utf-8")
    result = spine.sync_stones(time_budget_s=10)
    assert result["ingested"] == 1 and result["not_private"] == 1 and result["unverified"] == 1
    found = spine.stones.store("u", "alex").recall("harbor lantern", now=time.time() + 5)
    assert [i.excerpt for i in found] == ["Private old note about the harbor lantern."]


@pytest.mark.asyncio
async def test_the_memory_map_lists_the_stones_without_touching_them(tmp_path):
    spine = PubPartnerSpine(tmp_path)
    await spine.run_turn(session_id="s", message="My friend Sam loves baseball. Sam loves sherbet.", **BASE)
    before = sorted((str(p.relative_to(tmp_path)), p.stat().st_size) for p in (tmp_path / "pubpartner" / "stones").rglob("*") if p.is_file()
                    and not p.name.endswith(("-wal", "-shm")))
    report = build_memory_map(tmp_path, runtime={"stones_sync": {"status": "ok", "complete": True, "ingested": 0}})
    entry = next(s for s in report["stores"] if s["id"] == "stones")
    assert entry["counts"]["stones"] == 2 and entry["counts"]["sources"] == 1 and entry["counts"]["stores"] == 1
    assert entry["counts"]["start_sync"]["status"] == "ok"
    assert entry["problems"] == []
    after = sorted((str(p.relative_to(tmp_path)), p.stat().st_size) for p in (tmp_path / "pubpartner" / "stones").rglob("*") if p.is_file()
                   and not p.name.endswith(("-wal", "-shm")))
    assert after == before


@pytest.mark.asyncio
async def test_the_app_reads_saved_messages_into_stones_at_start_and_reports_it_in_the_memory_map(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import pubpartner_app

    before = PubPartnerSpine(tmp_path, stones_enabled=False)  # messages saved before stones existed
    await before.run_turn(session_id="s1", message="My friend Sam loves baseball. Sam's team is the Dodgers.", **BASE)
    await before.run_turn(session_id="s1", message="Studio talk that must stay out of private memory.", **dict(BASE, room_id="studio"))
    monkeypatch.setattr(pubpartner_app, "DATA_DIR", tmp_path)
    monkeypatch.setattr(pubpartner_app, "TWOI_DIR", tmp_path / "no-2i")
    monkeypatch.setenv("PUBCAST_ENFORCE_AUTH", "0")
    with TestClient(pubpartner_app.app):
        status = json.loads((tmp_path / "pubpartner" / "memory_status.json").read_text(encoding="utf-8"))
    assert status["ok"], status["warnings"]
    entry = next(s for s in status["stores"] if s["id"] == "stones")
    assert entry["counts"]["stones"] == 2 and entry["counts"]["sources"] == 1
    assert status["runtime"]["stones_sync"]["ingested"] == 1 and status["runtime"]["stones_sync"]["not_private"] == 1
    with TestClient(pubpartner_app.app):
        again = json.loads((tmp_path / "pubpartner" / "memory_status.json").read_text(encoding="utf-8"))
    assert again["runtime"]["stones_sync"]["ingested"] == 0  # a restart with nothing new reads nothing twice
