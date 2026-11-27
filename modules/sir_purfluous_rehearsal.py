"""Rule-based director layer for Sir Purfluous. Python 3.10+, stdlib only.

HONEST SCOPE
This module reads the *words* a person types with regular expressions and picks one of
four moves. It does not understand the person. It is the decision skeleton of a director:

    QUESTION  draw the answer out of them (the default; one question at a time)
    NOTE      one actionable correction (a tone note, a craft note, "one thing at a time")
    TELL      stop asking and just say it (direct ask, out of time, or stuck after questions)
    DEMO      get up and show it (asked to see it, or a note did not land)

Voice is carried as data, so a human performer (or a TTS layer) can act it:
    register  'theatrical' (sing-song, announces himself) | 'plain' (accent drops: blunt,
              matter-of-fact) | 'whisper' (a shouting whisper)
    cue       a short stage direction for the performer

Limits that are deliberate and stated, not hidden:
  * It cannot improvise the other half of a scene. DEMO stages the chair swap and
    re-delivers the person's own quoted line (slowed, underplayed or stressed); it does
    not invent the opposite role's lines.
  * TELL gives a decisive process directive ("pick one, commit, adjust"). It has no
    domain knowledge, so it never claims to know the right answer to someone's problem.
  * It will not tell anyone who they are. Self-discovery stays a question.
Nothing here executes anything; NOTE and TELL carry a proposal with executed=False.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

DIRECTOR = {
    "rehearsal": ("Performance rehearsal", "Begin with intention: what does the character want? Play the objective once plainly, then vary tempo, stakes, and restraint."),
    "camera": ("Camera framing", "Find the story's point of view before choosing a lens. Establish geography, protect eyelines, and rehearse the movement before rolling."),
    "lighting": ("Lighting design", "Decide what the light should reveal or conceal. Establish a motivated source, then test contrast and continuity."),
    "sound": ("Sound preparation", "Confirm microphone placement, room tone, and gain before the take. A glorious image cannot rescue unintelligible dialogue."),
    "blocking": ("Stage blocking", "Identify entrances, exits, eyelines, sightlines, and safe movement. Mark positions before rehearsing."),
    "take": ("Another take", "Give one actionable note at a time. Specify what changes, then give the performer space to execute."),
}

_PATTERNS = {
    "direct_ask": [r"\bjust tell me\b", r"\btell me what (to|i should)\b", r"\bgive me the answer\b",
                   r"\bwhat should i (do|say|pick|choose|go with)\b", r"\bwhich (one )?should i\b",
                   r"\bjust give me\b", r"\bjust answer\b"],
    "rushed": [r"\bout of time\b", r"\bno time\b", r"\bdon'?t have time\b", r"\bdeadline\b",
               r"\brunning late\b", r"\bin a hurry\b", r"\bhurry\b", r"\bin \d+ (minutes?|mins?|hours?)\b",
               r"\bright now\b", r"\basap\b"],
    "stuck": [r"\bstuck\b", r"\bi (really |just )?don'?t (really )?know\b", r"\bno idea\b", r"\bblank\b", r"\bcan'?t figure\b",
              r"\blost\b", r"\bnot sure\b", r"\bconfused\b", r"\bnothing comes\b"],
    "overwhelmed": [r"\btoo much\b", r"\boverwhelm", r"\beverything at once\b", r"\bso many\b", r"\bdrowning\b"],
    "show_me": [r"\bshow me\b", r"\bdemonstrate\b", r"\blike what\b", r"\bfor example\b",
                r"\bhow would you (do|say|play)\b", r"\bcan you do it\b"],
    "self_discovery": [r"\bwho am i\b", r"\bwho i (really )?am\b", r"\bwho i'?m (supposed|meant) to be\b", r"\bwhat do i want\b", r"\bfind myself\b", r"\bmy purpose\b",
                       r"\bdon'?t know what i want\b", r"\bwhat i really want\b",
                       r"\bwhat am i (supposed|meant) to\b", r"\bwhat kind of (person|life)\b"],
    "tone_hot": [r"\bangry\b", r"\bfurious\b", r"\brage\b", r"\bshouting\b", r"\bshouted\b", r"\byelled\b",
                 r"\byelling\b", r"\bscreaming\b", r"\btoo loud\b", r"\btoo intense\b", r"\bover the top\b",
                 r"\baggressive\b", r"\branting\b"],
    "tone_flat": [r"\bflat\b", r"\bmonotone\b", r"\bbored\b", r"\bboring\b", r"\bdull\b", r"\blifeless\b",
                  r"\bno energy\b", r"\bno feeling\b", r"\bwooden\b", r"\bmumbling\b"],
    "too_fast": [r"\btoo fast\b", r"\brushing\b", r"\bracing\b", r"\brushed through\b", r"\bblurt",
                 r"\bpause\b", r"\bslow(ed)? (it )?down\b"],
    "still_wrong": [r"\bstill\b", r"\bagain\b", r"\bsame\b", r"\bdidn'?t work\b", r"\bnot working\b",
                    r"\btried that\b", r"\bnothing changed\b"],
}
_COMPILED = {k: [re.compile(p, re.I) for p in v] for k, v in _PATTERNS.items()}
TONE = frozenset({"tone_hot", "tone_flat", "too_fast"})
_QUOTE = re.compile(r'["\u201c]([^"\u201d]{4,300})["\u201d]')
_TAKE = re.compile(r"\b(another|one more|next|last|that|this|the) take\b|\btake (one|two|three|\d+)\b|\bretake\b", re.I)

REGISTER_CUE = {
    "theatrical": "(sing-song, a little grand)",
    "plain": "(drops the accent: blunt, matter-of-fact)",
    "whisper": "(a shouting whisper)",
}

QUESTIONS = {
    "default": [
        "What are you actually trying to get across?",
        "Who is it for, and what should they feel when it lands?",
        "What have you tried so far, and what happened?",
        "If this went perfectly, what would it look like?",
    ],
    "stuck": [
        "Where exactly does it stop: the first step, the middle, or the finish?",
        "What is the smallest piece of this that you do know?",
        "If you had to choose in the next ten seconds, which way would you lean?",
    ],
    "self_discovery": [
        "If nobody were watching, truly nobody, what would you do next?",
        "When did you last lose track of time, and what were you doing?",
        "What would you keep doing even if it never paid you?",
        "What did you want at ten years old that you still catch yourself wanting?",
    ],
}

_VOCATIVES = ["darling", "dear heart", "my friend"]
_BEAT = " [beat] "
_INTENSIFIERS = re.compile(r"\b(very|really|so|absolutely|totally|completely|extremely)\b\s*", re.I)


# --- demonstrations of a person's own line ---------------------------------------------
def _clauses(line: str) -> list[str]:
    return [p.strip() for p in re.split(r"(?<=[,;:.!?])\s+|\s+[\u2014\u2013-]+\s+", line.strip()) if p.strip()]


def slow(line: str) -> str:
    """Insert beats between clauses (or mid-line if it is one run-on) so the pause is audible."""
    parts = _clauses(line)
    if len(parts) < 2:
        words = line.split()
        if len(words) < 3:
            return line.strip()
        best_i, best_n = 1, 0
        for i, w in enumerate(words[1:], start=1):
            n = len(re.sub(r"\W", "", w))
            if n > best_n:
                best_i, best_n = i, n
        parts = [" ".join(words[:best_i]), " ".join(words[best_i:])]
    return _BEAT.join(parts)


def underplay(line: str) -> str:
    """Take the heat out: no exclamation marks, no intensifiers, no shouted words, then slow it."""
    t = line.replace("!", ".")
    t = _INTENSIFIERS.sub("", t)
    t = re.sub(r"\b[A-Z]{2,}\b", lambda m: m.group(0).lower(), t)
    return slow(re.sub(r"\s{2,}", " ", t).strip())


def stress(line: str) -> str:
    """Land one word: the longest content word is capitalised, with a beat in front of it."""
    words = line.split()
    best_i, best_n = -1, 0
    for i, w in enumerate(words):
        n = len(re.sub(r"\W", "", w))
        if n > best_n:
            best_i, best_n = i, n
    if best_n < 4:
        return line.strip()
    core = re.sub(r"^\W+|\W+$", "", words[best_i])
    words[best_i] = words[best_i].replace(core, core.upper(), 1)
    if best_i > 0:
        words[best_i - 1] += " [beat]"
    return " ".join(words)


_DEMOS = {"slow": slow, "underplay": underplay, "stress": stress}


def demonstrate(line: str, kind: str) -> str:
    if kind not in _DEMOS:
        raise ValueError(f"unknown demonstration kind: {kind}")
    return _DEMOS[kind](line)


# --- reading the person -----------------------------------------------------------------
@dataclass(frozen=True)
class Reading:
    signals: frozenset
    craft: str | None = None
    attempt: str | None = None

    @property
    def has_need(self) -> bool:
        return bool(self.signals or self.craft or self.attempt)


def read_person(message: str) -> Reading:
    text = message or ""
    signals = {name for name, pats in _COMPILED.items() if any(p.search(text) for p in pats)}
    words = set(re.findall(r"[a-z]+", text.lower()))
    craft = next((k for k in DIRECTOR if k != "take" and k in words), None)
    if craft is None and _TAKE.search(text):
        craft = "take"
    quotes = _QUOTE.findall(text)
    attempt = max(quotes, key=len).strip() if quotes else None
    return Reading(frozenset(signals), craft, attempt)


@dataclass
class DirectorSession:
    turns: int = 0
    questions_in_a_row: int = 0
    last_move: str | None = None
    last_register: str | None = None
    last_attempt: str | None = None
    last_tone: str | None = None
    asked: set = field(default_factory=set)


def choose_move(r: Reading, s: DirectorSession) -> tuple[str, str]:
    sig = r.signals
    if "self_discovery" in sig:
        return "question", "self_discovery"          # never hands anyone an identity
    if "show_me" in sig:
        return "demo", "asked_to_see"
    if "direct_ask" in sig or "rushed" in sig:
        return "tell", "direct_or_rushed"
    if s.last_move == "note" and "still_wrong" in sig:
        return "demo", "note_did_not_land"
    if "stuck" in sig:
        if s.questions_in_a_row >= 2:
            return "tell", "stuck_after_questions"
        return "question", "stuck"
    if "overwhelmed" in sig and not (sig & TONE):
        return "note", "one_thing"
    if sig & TONE or r.craft:
        return "note", "tone_or_craft"
    return "question", "default"


class Director:
    def __init__(self, seed=None):
        self.rng = random.Random(seed)
        self.session = DirectorSession()

    # -- helpers
    def _voc(self) -> str:
        return "Sancho" if self.session.turns == 0 else self.rng.choice(_VOCATIVES)

    def _pick(self, pool: str) -> str:
        asked = self.session.asked
        fresh = [q for q in QUESTIONS[pool] if q not in asked]
        if not fresh:
            asked.difference_update(QUESTIONS[pool])
            fresh = list(QUESTIONS[pool])
        q = self.rng.choice(fresh)
        asked.add(q)
        return q

    @staticmethod
    def _tone(sig) -> str | None:
        return next((t for t in ("tone_hot", "tone_flat", "too_fast") if t in sig), None)

    @staticmethod
    def _proposal(topic: str, note: str) -> dict:
        return {"type": "director_note", "topic": topic, "note": note, "executed": False}

    # -- moves
    def _question(self, r: Reading, reason: str) -> dict:
        if reason == "self_discovery":
            lead = "I can't hand you that one; it isn't mine to give. " if "direct_ask" in r.signals else ""
            return {"text": f"{lead}Come closer, {self._voc()}. {self._pick('self_discovery')}",
                    "register": "whisper", "proposal": None}
        if reason == "stuck":
            return {"text": f"Right. {self._pick('stuck')}", "register": "plain", "proposal": None}
        return {"text": f"Tell me, {self._voc()}. {self._pick('default')}", "register": "theatrical", "proposal": None}

    def _note(self, r: Reading, reason: str) -> dict:
        tone = self._tone(r.signals)
        voc = self._voc()
        if tone == "tone_hot":
            note = f"Too hot, {voc}. You are shouting at the back of the house. Bring it down, let the line land by itself, and take it again."
            return {"text": note, "register": "theatrical", "proposal": self._proposal(tone, note)}
        if tone == "tone_flat":
            note = f"Too flat, {voc}. There is no want in it. Decide what you are after, let it cost you something, and take it again."
            return {"text": note, "register": "theatrical", "proposal": self._proposal(tone, note)}
        if tone == "too_fast":
            note = f"You are racing, {voc}. Find the pause: stop, breathe, let the silence do some of the work, then give me the line."
            return {"text": note, "register": "theatrical", "proposal": self._proposal(tone, note)}
        if reason == "one_thing":
            note = "One thing at a time. Name the single biggest problem and we fix only that one. Which is it?"
            return {"text": note, "register": "plain", "proposal": self._proposal("one_thing", note)}
        title, advice = DIRECTOR[r.craft]
        note = f"{voc.capitalize()}, {title.lower()}! {advice} The next cue is yours."
        return {"text": note, "register": "theatrical", "proposal": self._proposal(r.craft, advice)}

    def _tell(self, r: Reading, reason: str) -> dict:
        if r.craft:
            advice = DIRECTOR[r.craft][1]
            return {"text": f"Short version, no theatrics: {advice}", "register": "plain",
                    "proposal": self._proposal(r.craft, advice)}
        if reason == "stuck_after_questions":
            text = ("Look, I have asked enough questions. Here is the call: stop weighing it, pick the option "
                    "you would regret not trying, do it once even badly, and we adjust from what happens.")
        else:
            text = "No time for riddles. Take the first workable option, commit to it, and we fix it on the next take."
        return {"text": text, "register": "plain", "proposal": self._proposal("decision", text)}

    def _demo(self, r: Reading, reason: str) -> dict:
        line = r.attempt or self.session.last_attempt
        cue = "(rises from his chair and takes the opposite chair)"
        if not line:
            return {"text": "Hand me your line in quotation marks and I will take the other chair. Do not be insulted, "
                            "darling; I need to show you, not tell you.",
                    "register": "theatrical", "proposal": None, "cue": cue, "demo": None}
        tone = self._tone(r.signals) or self.session.last_tone
        kind = {"tone_hot": "underplay", "tone_flat": "stress", "too_fast": "slow"}.get(tone, "slow")
        shown = demonstrate(line, kind)
        text = (f"Do not be insulted; watch. Yours, as written: \"{line}\" Mine: \"{shown}\" "
                "Hear the difference? Now you, same line, my way.")
        return {"text": text, "register": "theatrical", "proposal": None, "cue": cue,
                "demo": {"kind": kind, "original": line, "shown": shown}}

    # -- public
    def respond(self, message: str) -> dict:
        s = self.session
        reading = read_person(message)
        if reading.attempt:
            s.last_attempt = reading.attempt
        tone = self._tone(reading.signals)
        if tone:
            s.last_tone = tone
        move, reason = choose_move(reading, s)
        out = getattr(self, "_" + move)(reading, reason)
        out.setdefault("demo", None)
        reg = out["register"]
        if s.turns == 0 and reg == "theatrical":
            out["text"] = "Sir Purfluous, at your service! " + out["text"]
        elif s.last_register == "plain" and reg == "theatrical":
            out["text"] = "And now, back to the theatre! " + out["text"]
        out["cue"] = out.get("cue") or REGISTER_CUE[reg]
        out["move"], out["reason"] = move, reason
        s.turns += 1
        s.questions_in_a_row = s.questions_in_a_row + 1 if move == "question" else 0
        s.last_move, s.last_register = move, reg
        return out
