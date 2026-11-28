# PubPartner recall: stepping stones (2026-11-28)

Branch: `claude/pubpartner-recall-stones-2026-11-28` (made from `claude/pubpartner-memory-debug-2026-11-27` at `7d502b8`).
Written by Claude for Josie, and for any AI that picks this up cold. Nothing in this document is a guess unless it says "guess".
Everything under "Verified" was run; everything under "Not verified" was not.

## 1. What Josie asked for, in her words

- "Every memory is a stepping stone to and from somewhere."
- "Like, look, it's how journalists gather news. Every story has to have who, what, where, when, why, how, to the best of your ability. It's a good way to make sense of the world. And when, with persistent memory, that's all the more important because it all links together."
- "Yeah, I mean, not just, I mean, the memory shouldn't just be a word search. It should be like a proximity search. You know, just like a series of Venn diagrams."
- On the go-ahead: "All right, so go through the code and adjust what you need to, redo what you need to. Let's do this right."
- She called the whole design "an experiment", so every part below is meant to be inspected and changed.

## 2. What was built

A new layer called stones, beside Jeremy (not inside it). One stone is one sentence the person said in private chat.

New files:
- `modules/pubpartner_stone_text.py`: reads a message into stones. No model, no network.
- `modules/pubpartner_stones.py`: stores stones (one SQLite file per user and friend), recalls them, merges them with Jeremy's list, rebuilds them from the verbatim vault, and has a small command-line tool.
- `tests/test_pubpartner_stones.py`: 70 tests.

Changed files:
- `modules/pubpartner_core.py`: `MemoryRef` gets an optional `why`; `PubPartnerSpine` gets `stones_enabled`, `_stone_turn` (recall, merge, then read the new message), `sync_stones`, and a fix so Jeremy no longer returns the message being answered as its own memory.
- `pubpartner_app.py`: at start, reads saved private messages that have no stones yet (limited to 5 seconds per start).
- `modules/pubpartner_memory_map.py`: a "Stepping stones" entry (counts only; read-only) and one note.
- `tests/test_pubpartner_memory_tuneup.py`: store list gains "stones"; the strict xfail recall test is now an ordinary passing test (its own note said to remove the marker when recall changed).
- `docs/PUBPARTNER_MEMORY_TUNEUP_2026-11-27.md`: pointers to this document.
- `.gitignore`: `data/pubpartner/stones/`.

Not touched: `modules/jeremy_cricket.py` (shared, pinned), Alex Core, the vessel, the verbatim vault.

## 3. How a message becomes stones

1. The message is split into sentences (abbreviations such as "Dr." and "U.S." do not split; Chinese and Japanese full stops do).
2. Each sentence is asked six questions: who, what, where, when, why, how. An answer is either the person's exact words (stored with its position in the message) or "unknown". Nothing is paraphrased. Before a stone is saved, every answer is checked to be an exact piece of the message; one that is not is dropped and reported, never repaired.
3. A hope or a want ("I hoped people could hear her better") is stored as a motive, not as a reason. A motive says what the person was after; it does not say anything worked.
4. Each stone also records how it was said: statement, question, guess ("maybe", "I think"), what-if, or quotation. And whether it sounds lasting ("Sam loves baseball") or about one day ("Sam's team lost today"). A "today" statement is kept, but counts for much less once that day has passed, and says so when recalled.
5. A sentence that starts with he, she, it or they and names nobody is flagged: who it is about is not known from that sentence. It is not guessed.
6. Names, roles ("my friend", "my boss"), places and ordinary words are stored as separate circles. A name is stored the same way a search word is, so "Dodgers" is found by "Dodger's".
7. Non-English text gets word search only; every question that needs English rules stays unknown.
8. Only ordinary private messages are read (not code, lyrics, pasted documents, and not anything said in a shared room).

## 4. How memories come back

For each private message, before the reply:
1. Words, names, roles and places of the new message are matched against the stones. A match counts for more the rarer the term is among this person's own memories. A word nearly everyone uses cannot bring a memory back by itself; a name or an unusual word can. (Measured against about 20 imagined unrelated memories, so a person's first few memories are not all treated as "common".)
2. Ring 1 is what overlaps the message. Ring 2 is one step out: lasting facts that share a name or role with the top ring-1 memories. Example in the tests: "The Dodgers lost today" brings back "Sam's team is the Dodgers", then "Sam loves baseball" and "Sam loves strawberry sherbet ice cream", because they share the name Sam. Questions and what-ifs are never pulled in at ring 2.
3. Stones are merged with Jeremy's list (weighted rank fusion, stones 1.0, Jeremy 0.5). A Jeremy pointer to a message whose sentence is already there is dropped. At least one slot in three stays available to Jeremy.
4. Each stone reaches the model as one line of the sentence plus a short `why`: what matched (or the shared name), the date it was said, "described as lasting" or "may be out of date", whether it was a question or a guess, and any who/where/when/why/how that were actually stated.
5. After the reply is built, the new message is read into stones. Memories shown are counted (`surfaced_count`); the count does not change ranking yet.

## 5. Switches and commands (PowerShell 5)

- Turn stones off for the whole app: `$env:PUBPARTNER_STONES = "off"` before starting (values off, 0, false, no). Or `stones_enabled=False` in code. Off means packets are byte-for-byte what they were, except the Jeremy self-match fix, which stays on.
- See everything PubPartner remembers, including stones: `python -m modules.pubpartner_memory_map --data-dir data`
- Stone counts for one person and friend: `python -m modules.pubpartner_stones status --data-dir data --user <user id> --friend alex`
- Try a recall: `python -m modules.pubpartner_stones search --data-dir data --user <user id> --friend alex --query "the Dodgers lost today"`
- Rebuild from scratch: delete the whole folder `data\pubpartner\stones` and start the app. It re-reads your saved private messages, at most 5 seconds per start, and carries on at the next start. If you delete only one person's file inside it, only their messages are re-read.

## 6. Privacy rules built in

- One file per user and friend. No query spans files, so recall cannot cross users or friends.
- Private audience only, for both recall and saving. A shared room (or a client asking for "private" in a shared room) neither sees nor adds stones.
- Hosts that isolate memory by project and room (`scoped_memory=True`) get the same isolation: stones are recalled only from the same project and room. Without that setting, stones are recalled across projects for the same user and friend (like Jeremy's friend-wide memory).
- When rebuilding from the vault, a message is admitted only if its audience can be shown to be private: new messages carry `audience` in their vault record; older ones are checked against the session's turn log. If neither says so, the message is counted as "unverified" and left out.
- A vault record that fails its own hash checks is never read around.

## 7. Verified (all run on a fresh assembled build, `tools/standalone/assemble.py`)

- Full suite: 329 passed, 4 skipped, 1 failed. The one failure, `test_existing_canonical_api_registered_in_both_hosts`, opens `main.py` (the PubCast host), which a standalone build does not contain. I ran it on an untouched build of `7d502b8` and it fails identically, so it is not caused by this work. Federation suite (`PYTHONPATH=pubpartner`): 14 passed. The earlier tune-up pass reported 258 passed + 1 xfailed + the same 1 failure.
- The 2026-11-27 recall scenario, through the real spine and real Jeremy, stones off versus on: with stones off the early fact is recalled after 90 later similar messages and lost after 120 and after 200 (the defect reproduced); with stones on it is recalled after 90, 120 and 200, and is the first memory offered.
- The reader on hostile input: runs of 200,000 dots, 300,000 characters without a space, 100,000 newlines, long runs of "because ", "by running ", "after ", quotes and brackets, NUL bytes, control characters, a 5 MB message, right-to-left text, emoji. Each finishes well under a second. I found and fixed one slow case on the way (a long run of dots made sentence splitting quadratic).
- Four operating-system processes writing the same stones file with the same 60 message ids: each id ingested exactly once, no errors, integrity check ok, no duplicate or orphan rows.
- Speed on synthetic text: about 15,000 stones (2,500 messages): ingest 7.1 ms per message, recall median 7.6 ms, 95th percentile 11.8 ms, file 13.2 MB. Reading 800 saved messages at start: 8.8 ms each (about 570 per 5-second start); a second start with nothing new: 0.01 s.
- `scripts/pubpartner_memory_probe.py` (real launcher, two boots; 18 checks, none failed) and `scripts/pubpartner_restart_probe.py` (ok) both pass on this code.
- The app starts over a vault of older messages, reads them into stones, reports it in `memory_status.json`, and reads nothing twice on the next start (a test).
- A stone-store failure (recall, save, or the store cannot open) never blocks a reply and is named in `stones_status.problems` (tests).

## 8. Not verified

- Nothing was run on Windows. SQLite file locking and the launcher were not tried there.
- A real provider was never run; only the mock provider. How a model uses the `why` lines is unknown.
- Real conversations: the speed and recall numbers use synthetic text. How well the English rules read real messages beyond the test sentences is unmeasured.
- The `why` text adds tokens to every private reply (up to 260 characters per stone). Not measured against a real model's budget.
- Two app processes on one data folder were tried only for stones (above), not for the older open items A to D.

## 9. Known limits found while testing

1. A name that is only ever the first word of a sentence ("Sam loves baseball." as the first sentence) cannot be told from any capitalized word, so "who" stays unknown. The word is still searchable. The name is learned the first time it appears mid-sentence, or in a multi-word name, or with 's. Messages already read are not re-read when a name is learned later (there is a `READER_VERSION` for a future re-read, but no tool for it yet).
2. Who/where/when/why/how extraction is English rules, not understanding. It misses a lot (no "where" for most sentences, "how" only for "by ...ing", "using", "via"). Unknown is the honest answer there. A language model could propose answers later; `ground_proposed_answers` in `pubpartner_stone_text.py` already rejects any proposed answer whose words are not exactly in the sentence.
3. Pronouns are not resolved ("His team is the Dodgers" is flagged as pointing back to someone, not linked to Sam).
4. Only the first 200,000 characters and 60 sentences of a message are read into stones. The whole message is still in the vault and in Jeremy's pointer.
5. Stone text in the packet is clipped at 220 characters like every memory (`MAX_MEMORY_SUMMARY_CHARS`); a longer sentence arrives cut with an ellipsis.
6. Jeremy's own list still has its faults (substring matching, ASCII-only words, hex and boilerplate in pointer text, recency floor, recall marks "accessed"). Stones do not fix Jeremy; they sit beside it. The pointer boilerplate still reaches the model for Jeremy's items.
7. Ring 2 is one step only. No co-occurrence profiles ("what usually comes with this name"), no longer trails.

## 10. Josie's design versus what exists

- Who/what/where/when/why/how with unknowns kept as unknowns: built (English rules).
- Link back and forward ("to and from somewhere"): partly. Each stone records its source and position and ring 2 links through shared names and roles. No explicit forward link between stones yet.
- Overlapping circles, not word search: built (words, names, roles, places; rarity weighted; one step out).
- Lasting facts versus today's context: built (lasting, one-day with expiry, dated, unknown).
- Graded confidence (probability, Occam's razor as a guide, history, evidence): not built. The stone records who said it and how (statement, guess, what-if); it does not grade whether it is true. The vessel already has the tentative, corroborated, confirmed ladder to reuse.
- Using a lead to check memory, search the web, or ask the person; bounding that by priority: not built.
- Model-written understanding of a stone (validator first): not built; the validator exists.
- Forget or retire a stone: not built. The way to remove one today is to delete the stones folder; it comes back from the vault.

## 11. Decisions for Josie (case for and against)

1. Stones ON by default (as built). For: it fixes the measured recall loss, it is rebuildable, and there is an off switch. Against: it changes what the model sees on every private reply, it has never run with a real provider, and the English rules are imperfect.
2. Merge weights stones 1.0 versus Jeremy 0.5, with one slot in three kept for Jeremy. For: stones are more precise. Against: Jeremy holds things stones never see (events from Alex and the bridge); weighting stones higher could crowd them out.
3. Jeremy left untouched. For: it is a shared, pinned file used by Alex Core. Against: its faults remain for everything that reads it directly.
4. Private audience only. For: it matches how guidance, Alex's memories and the archive are already kept. Against: shared-room conversation gets no stone memory.
5. Across projects for the same user and friend unless the host isolates memory. For: "it all links together". Against: a fact from one project can surface in another.
6. The earlier open items from the 2026-11-27 pass are still open and still hers to decide: A (two app processes on one data folder fork the verbatim chain), B (a torn last receipt row makes later turns in that session fail), C (user and session ids that clean up alike share files), and D (the recall defect: now addressed here, pending her answers above).

## 12. Next steps for the next AI

- Read this file, then `modules/pubpartner_stone_text.py` and `modules/pubpartner_stones.py` (both start with a docstring that states their limits).
- Highest value, in order: (a) run it with a real provider on real conversations and look at the `why` lines; (b) build the confidence bands from the vessel's tentative, corroborated, confirmed ladder, counting independent occasions rather than repetition; (c) the verify-or-ask behaviour and its priority limit; (d) a re-read tool for when the reader improves; (e) a way to retire a stone.
- Never edit `modules/jeremy_cricket.py` from this branch. Test only from an assembled build (`/home/claude/scratch/dbg/rebuild.sh` builds one); do not use GitHub Actions.
