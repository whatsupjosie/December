"""Reading what a person said, for PubPartner's stepping stones.

A *stone* is one sentence the user said, kept as its own unit of memory with six
questions asked of it: who, what, where, when, why and how. This module is the
reader. It is deterministic, local and free: no model call, no network.

Design laws (they are tested, see tests/test_pubpartner_stones.py)
------------------------------------------------------------------
- Every answer that is filled in is an exact span of the user's own words: the
  fragment text equals ``text[start:end]`` of the message that was read. Nothing
  is paraphrased and nothing is invented.
- A question the words do not answer stays an explicit ``unknown``. Unknown is a
  real state that later evidence can fill; it is never guessed.
- Nothing here decides what is *true*. A stone records what the user said, how
  they said it (statement, question, tentative, hypothetical, quoted) and
  whether it describes something lasting or something about today.
- The English rules (names, places, times, reasons, manner) run only for
  English text. Any other language still gets word terms, so recall by words
  works, and every English-only question is honestly marked unknown.
- Hostile input is bounded: at most ``MAX_MESSAGE_CHARS`` characters are read, at
  most ``MAX_STONES_PER_MESSAGE`` stones are made, no regex runs on more than a
  sentence of at most ``MAX_SENTENCE_CHARS`` characters, and the one backwards
  scan is capped at a dozen characters.

Reasons are kept in two strengths because they are different claims. A reason
the user gave outright ("because ...") has ``mode="reason"``. A hope or a want
("I hoped people could hear her better") has ``mode="motive"``: it says what
the user was after, and does not establish that anything happened or worked.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Iterable, Iterator, List, Optional, Tuple

SLOTS: Tuple[str, ...] = ("who", "what", "where", "when", "why", "how")

MAX_MESSAGE_CHARS = 200_000
MAX_SENTENCE_CHARS = 1_200
MAX_STONES_PER_MESSAGE = 60
MAX_EXCERPT_CHARS = 700
MAX_TERM_CHARS = 40
MAX_TERMS_PER_STONE = 64

READING_ENGLISH = "english_rules"
READING_WORDS = "words_only"

# --------------------------------------------------------------------------- words

_STOPWORDS: FrozenSet[str] = frozenset("""
a an the and or but nor so yet for of to in on at by with from into onto over under about as is are was were be been being am
it its this that these those there here he she they them him her his hers their theirs we us our ours you your yours i me my mine
do does did doing done have has had having will would shall should can could may might must not no yes ok okay
what who whom whose which when where why how than then too very just also only own same such some any all each both more most other
if because while although though until unless since after before during again further once up down out off here now ever
get got gets getting go goes going went gone let lets thing things one ones really quite rather still even much many
dont doesnt didnt isnt arent wasnt werent wont wouldnt cant couldnt shouldnt havent hasnt hadnt im ive ill id youre youve youll
hey hi hello thanks thank please yeah yep nope well oh um uh
""".split())

_WORD_RE = re.compile(r"[^\W_]+(?:['’][^\W_]+)*")
_CJK_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿가-힯]+")


def _light_stem(word: str) -> str:
    """A very light plural stem. Index and query both pass through it, so a miss is harmless."""
    if len(word) < 4 or not word.isascii() or not word.isalpha():
        return word
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith(("sses", "shes", "ches", "xes", "zes")):
        return word[:-2]
    if word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def normalize_word(word: str) -> str:
    """Fold case, drop a possessive and inner apostrophes, then stem lightly."""
    folded = unicodedata.normalize("NFKC", word).casefold().replace("’", "'")
    if folded.endswith("'s"):
        folded = folded[:-2]
    elif folded.endswith("s'"):
        folded = folded[:-1]
    return _light_stem(folded.replace("'", ""))


def _cjk_pieces(raw: str) -> Iterator[Tuple[str, bool]]:
    position = 0
    for match in _CJK_RE.finditer(raw):
        if match.start() > position:
            yield raw[position:match.start()], False
        yield match.group(), True
        position = match.end()
    if position < len(raw):
        yield raw[position:], False


def terms(text: str, *, limit: int = MAX_TERMS_PER_STONE) -> List[str]:
    """Searchable terms of ``text``: normalized words (any script), CJK bigrams, no filler.

    Unique, in order of first appearance. Tokens longer than ``MAX_TERM_CHARS``
    (hashes, pasted blobs) are dropped.
    """
    found: List[str] = []
    seen = set()

    def add(term: str) -> None:
        if term and term not in seen:
            seen.add(term)
            found.append(term)

    for match in _WORD_RE.finditer(text[:MAX_MESSAGE_CHARS]):
        for piece, is_cjk in _cjk_pieces(match.group()):
            if is_cjk:
                if len(piece) == 1:
                    add(piece)
                else:
                    for index in range(len(piece) - 1):
                        add(piece[index:index + 2])
                continue
            word = normalize_word(piece)
            if len(word) < 2 or len(word) > MAX_TERM_CHARS or word in _STOPWORDS:
                continue
            add(word)
        if len(found) >= limit:
            break
    return found[:limit]


# ------------------------------------------------------------------------ sentences

_ABBREVIATIONS = frozenset({
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "eg", "ie", "pm", "inc", "ltd", "mt", "ft",
})
# One terminator, then closing quotes or brackets, then whitespace. A single terminator (not "[.!?]+") keeps this linear:
# a run of 200,000 dots with no space after it must not make the engine retry every shorter run.
_BOUNDARY_RE = re.compile(r"[.!?…][\"'”’)\]]*(?=\s)|[。！？]+[\"'”’」』)\]]*|\n+")
_DOTTED_ABBREVIATION_RE = re.compile(r"(?:[a-z]\.)*[a-z]")


def _is_abbreviation(text: str, dot_index: int) -> bool:
    low = max(0, dot_index - 12)  # bounded: a hostile run of "a.a.a.a." must not make this quadratic
    index = dot_index - 1
    while index >= low and (text[index].isalnum() or text[index] == "."):
        index -= 1
    raw_token = text[index + 1:dot_index].casefold()
    token = raw_token.replace(".", "")
    if not token:
        return False
    if token in _ABBREVIATIONS or token.isdigit() or ("." in raw_token and _DOTTED_ABBREVIATION_RE.fullmatch(raw_token)):
        return True
    return len(token) == 1 and token.isalpha()


def split_sentences(text: str) -> List[Tuple[int, int]]:
    """Character spans ``(start, end)`` of each sentence, trimmed, never empty, never overlapping."""
    text = text[:MAX_MESSAGE_CHARS]
    spans: List[Tuple[int, int]] = []
    start = 0

    def push(begin: int, end: int) -> None:
        while begin < end and text[begin].isspace():
            begin += 1
        while end > begin and text[end - 1].isspace():
            end -= 1
        while end - begin > MAX_SENTENCE_CHARS:
            cut = text.rfind(" ", begin, begin + MAX_SENTENCE_CHARS)
            cut = cut if cut > begin else begin + MAX_SENTENCE_CHARS
            spans.append((begin, cut))
            begin = cut
            while begin < end and text[begin].isspace():
                begin += 1
        if end > begin:
            spans.append((begin, end))

    for match in _BOUNDARY_RE.finditer(text):
        run = match.group()
        if run.startswith("\n"):
            push(start, match.start())
        else:
            if run[0] == "." and run.rstrip("\"'”’)]") == "." and _is_abbreviation(text, match.start()):
                continue
            push(start, match.end())
        start = match.end()
    push(start, len(text))
    return spans


# -------------------------------------------------------------------------- shapes

@dataclass(frozen=True)
class Fragment:
    """An exact piece of the user's words. ``text == message[start:end]`` always."""

    text: str
    start: int
    end: int
    role: str = ""

    def as_dict(self) -> Dict[str, object]:
        data: Dict[str, object] = {"text": self.text, "start": self.start, "end": self.end}
        if self.role:
            data["role"] = self.role
        return data


@dataclass(frozen=True)
class Answer:
    """One of the six questions: either stated (with its exact words) or unknown."""

    state: str  # "stated" | "unknown"
    fragments: Tuple[Fragment, ...] = ()
    mode: str = ""

    def as_dict(self) -> Dict[str, object]:
        if self.state != "stated":
            return {"state": "unknown"}
        data: Dict[str, object] = {"state": "stated", "fragments": [f.as_dict() for f in self.fragments]}
        if self.mode:
            data["mode"] = self.mode
        return data


UNKNOWN = Answer("unknown")


@dataclass(frozen=True)
class StoneDraft:
    """One sentence, read. Persisted by ``pubpartner_stones``; nothing here touches disk."""

    ordinal: int
    start: int
    end: int
    excerpt: str
    answers: Dict[str, Answer]
    word_terms: Tuple[str, ...]
    name_terms: Tuple[str, ...]
    role_terms: Tuple[str, ...]
    place_terms: Tuple[str, ...]
    modality: str          # statement | question | tentative | hypothetical | quoted
    temporal: str          # lasting | situational | dated | unknown
    importance: int
    unresolved_reference: bool
    expires_after_seconds: Optional[int]
    reading: str
    new_names: Tuple[Tuple[str, str], ...] = field(default=())  # (key, display) seen mid-sentence

    def answers_dict(self) -> Dict[str, object]:
        return {slot: self.answers[slot].as_dict() for slot in SLOTS}


# ---------------------------------------------------------------------- name rules

_I_FORMS = frozenset({"i", "i'm", "i've", "i'll", "i'd", "i’m", "i’ve", "i’ll", "i’d"})
_DAYS = frozenset("monday tuesday wednesday thursday friday saturday sunday".split())
_MONTHS = frozenset("january february march april may june july august september october november december".split())
_FUNCTION_START = frozenset("""
the a an this that these those my our your his her their its we you he she it they i is are was were am be been do does did have has
had will would can could should may might must what who whom whose when where why how which if but and or so because while although
though maybe perhaps also then now there here yes no ok okay hey hi hello thanks thank please well just not never always sometimes
once after before during today tonight tomorrow yesterday note
""".split())
_CAP_WORD_RE = re.compile(r"[^\W\d_](?:[^\W_]|[-'’](?=[^\W_]))*")


def _name_parts(word: str) -> List[Tuple[str, str]]:
    """``(key, text)`` for each piece of a capitalized word ("Jean-Luc" is two pieces).

    A key is normalized exactly the way a search word is (case, accents, possessive, plural), so a name is found
    by the same word that was said: "Dodgers" and "the Dodger's" both become ``dodger``. Pieces too short to be
    a name, day and month names, and bare numbers are dropped.
    """
    pieces: List[Tuple[str, str]] = []
    for piece in word.split("-"):
        key = normalize_word(piece)
        if len(key) < 2 or key in _DAYS or key in _MONTHS or key.isdigit():
            continue
        pieces.append((key, re.sub(r"['\u2019]s$", "", piece)))
    return pieces


def _name_key(word: str) -> str:
    """The key of a single capitalized word, or "" when it cannot be a name."""
    parts = _name_parts(word)
    return parts[0][0] if parts else ""


def capitalized_candidates(text: str) -> FrozenSet[str]:
    """Keys of every capitalized word in ``text``: what to look up among already-known names."""
    keys = set()
    for match in _CAP_WORD_RE.finditer(text[:MAX_MESSAGE_CHARS]):
        word = match.group()
        if word[0].isupper() and word.casefold() not in _I_FORMS:
            keys.update(key for key, _ in _name_parts(word))
    return frozenset(keys)


@dataclass(frozen=True)
class _NameRun:
    start: int
    end: int
    display: str
    parts: Tuple[Tuple[str, str], ...]  # (search key, the word as said) for each word of the name
    certain: bool  # capitalized in the middle of a sentence: the strongest cue short of being told


def _name_runs(sentence: str, offset: int, known: FrozenSet[str]) -> List[_NameRun]:
    words = [(m.start(), m.end(), m.group()) for m in _CAP_WORD_RE.finditer(sentence)]
    runs: List[_NameRun] = []
    index = 0
    while index < len(words):
        begin, end, word = words[index]
        if not word[0].isupper() or word.casefold() in _I_FORMS:
            index += 1
            continue
        run = [index]
        while (index + 1 < len(words) and words[index + 1][2][0].isupper()
               and sentence[words[index][1]:words[index + 1][0]] == " "):
            index += 1
            run.append(index)
        index += 1
        # Leading function words ("The Orchid project", "Maybe Sam") are not part of a name.
        stripped = 0
        while run and words[run[0]][2].casefold() in _FUNCTION_START:
            run.pop(0)
            stripped += 1
        while run and (normalize_word(words[run[0]][2]) in _DAYS or normalize_word(words[run[0]][2]) in _MONTHS):
            run.pop(0)
            stripped += 1
        if not run:
            continue
        first, last = words[run[0]], words[run[-1]]
        display = sentence[first[0]:last[1]]
        parts = tuple(pair for i in run for pair in _name_parts(words[i][2]))
        if not parts:
            continue
        at_sentence_start = run[0] == 0 and stripped == 0
        possessive = first[2].endswith(("'s", "’s"))
        if at_sentence_start:
            accepted = (any(key in known for key, _ in parts) or len(run) >= 2 or possessive)
            certain = False
        else:
            accepted, certain = True, True
        if accepted:
            runs.append(_NameRun(offset + first[0], offset + last[1], display, parts, certain))
    return runs


# --------------------------------------------------------------------- cue patterns

_RELATIONS = ("friend|buddy|pal|brother|sister|mom|mother|mum|dad|father|parents|partner|boyfriend|girlfriend|wife|husband|spouse|"
              "son|daughter|kid|kids|child|boss|manager|coworker|colleague|teacher|neighbou?r|roommate|landlord|therapist|doctor|"
              "cousin|aunt|uncle|grandma|grandmother|grandpa|grandfather|dog|cat")
_RELATION_RE = re.compile(rf"\b(?:my|our|his|her|their)\s+({_RELATIONS})\b", re.I)
_FIRST_PERSON_RE = re.compile(r"\b(?:I|I['’](?:m|ve|ll|d))\b|(?i:\b(?:me|my|mine|myself|we|our|ours|us)\b)")
_THIRD_PRONOUN_RE = re.compile(r"\b(?:he|she|they|him|her|his|hers|their|theirs|them|it|its)\b", re.I)
_PLACE_PREP = r"(?:in|at|near|to|from|around|outside|inside|across|into|toward|towards|by)"
_PLACE_NOUNS = ("home|house|apartment|flat|park|studio|office|school|church|shelter|kitchen|garage|stage|room|store|shop|library|"
                "hospital|clinic|bar|pub|cafe|café|restaurant|beach|station|airport|street|city|town|gym|theater|theatre|"
                "stadium|field|yard|garden|campus|lab|warehouse|venue|booth|backstage")
_PLACE_NOUN_RE = re.compile(rf"\b{_PLACE_PREP}\s+(?:(?:the|my|our|his|her|their|a|an|this|that)\s+)?({_PLACE_NOUNS})\b", re.I)
# A capitalized name after these (not "to" or "by": "gave it to Sam") is a place.
_NAME_PLACE_PREP = r"(?:in|at|near|around|outside|inside|across)"
_PLACE_PREP_BEFORE_RE = re.compile(rf"\b{_NAME_PLACE_PREP}\s+(?:(?:the|my|our|his|her|their)\s+)?$", re.I)

_MONTH_NAMES = "jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
_DAY_NAMES = "monday|tuesday|wednesday|thursday|friday|saturday|sunday"
_TIME_PATTERNS = (
    r"\b\d{4}-\d{2}-\d{2}\b",
    r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b",
    rf"\b(?:{_MONTH_NAMES})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?\b(?:,?\s+\d{{4}})?",
    rf"\b(?:in|during|last|next|this|since|until|before|after)\s+(?:{_MONTH_NAMES})\b(?:\s+\d{{4}})?",
    rf"\b(?:(?:on|last|next|this|every)\s+)?(?:{_DAY_NAMES})s?\b(?:\s+(?:morning|afternoon|evening|night))?",
    r"\b(?:today|tonight|tomorrow|yesterday|right now|just now|earlier|later|lately|these days|at the moment)\b",
    r"\b(?:this|last|next)\s+(?:morning|afternoon|evening|night|week|weekend|month|year|summer|winter|spring|fall|autumn)\b",
    r"\b(?:a|an|\d+|a few|a couple of|several)\s+(?:second|minute|hour|day|week|month|year)s?\s+ago\b",
    r"\b(?:in|after|within)\s+(?:a|an|\d+|a few|a couple of)\s+(?:minute|hour|day|week|month|year)s?\b",
    r"\b\d{1,2}(?::\d{2})?\s?(?:am|pm|a\.m\.|p\.m\.)(?!\w)",
    r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b",
    r"\b(?:in|since|during|of|by|until|before|after|back in)\s+(?:19|20)\d{2}\b",
    r"\b(?:after|before|during)\s+(?:(?:the|my|our|a)\s+)?"
    r"(?!(?:i|we|you|he|she|they|it|that|this|then|all|a|an|the|something|anything|nothing|everything|someone|anyone|everyone|more)\b)[a-z]{3,}\b",
)
_TIME_RE = re.compile("|".join(f"(?:{p})" for p in _TIME_PATTERNS), re.I)

_REASON_RE = re.compile(
    r"\b(?:because of|because|so that|in order to|due to|that(?:['’]s| is) why|which is why|the reason(?: is| was| being)?)\b[^,;.!?]*", re.I)
_MOTIVE_RE = re.compile(
    r"\b(?:I|we)\s+(?:really\s+|just\s+|so\s+)?(?:hope[ds]?|wish(?:ed)?|want(?:ed)?|need(?:ed)?|wanna|was hoping|were hoping|"
    r"was afraid|were afraid|am afraid|am worried|was worried|worried|afraid)\b[^,;.!?]*", re.I)
_MANNER_RE = re.compile(
    r"\b(?:by\s+[a-z]+ing\b|using\b|via\b|with the help of\b).*?(?=\s+(?:because|so that|in order to|due to)\b|[,;.!?]|$)", re.I)

_SITUATIONAL_RE = re.compile(
    r"\b(?:today|tonight|right now|this (?:morning|afternoon|evening)|at the moment|just now|currently|these days|lately|tomorrow)\b", re.I)
_DATED_RE = re.compile(
    rf"\b(?:yesterday|last\s+\w+|\d+\s+\w+\s+ago|ago|\d{{4}}-\d{{2}}-\d{{2}}|(?:{_MONTH_NAMES})\.?\s+\d{{1,2}}|(?:in|since)\s+(?:19|20)\d{{2}})\b", re.I)
_LASTING_RE = re.compile(
    r"\b(?:always|never|every\s+\w+|usually|often|favou?rite|loves?|hates?|adores?|enjoys?|prefers?|collects?|grew up|allergic|"
    r"can['’]?t stand|cannot stand|obsessed)\b", re.I)

_TENTATIVE_RE = re.compile(
    r"\b(?:maybe|perhaps|might|probably|possibly|i guess|i think|i suppose|not sure|i wonder|supposedly|apparently|seems?)\b", re.I)
_HYPOTHETICAL_RE = re.compile(r"\b(?:what if|if only|imagine|suppose|hypothetically|pretend)\b|^\s*if\b", re.I)
_QUESTION_START_RE = re.compile(
    r"^\s*(?:what|who|whom|whose|when|where|why|how|which|do(?!\s+not\b)|does|did|is|are|was|were|can|could|will|would|should|have|has|had)\b",
    re.I)
_QUOTED_RE = re.compile(r"[\"“][^\"”]{12,}[\"”]")

_IMPORTANT_RE = re.compile(
    r"\b(?:remember(?: this| that)?|don['’]?t forget|never forget|important|make sure|decided|we decided|the plan is|"
    r"promise[d]?|deadline)\b", re.I)

_SITUATIONAL_SECONDS = 36 * 3600
_TOMORROW_SECONDS = 72 * 3600
_LATELY_SECONDS = 14 * 86400


def _is_english(language: str) -> bool:
    return (language or "en").lower().replace("_", "-").split("-")[0] in {"en", ""}


def _modality(sentence: str) -> str:
    stripped = sentence.strip()
    if stripped.endswith("?") or _QUESTION_START_RE.match(stripped):
        return "question"
    if _HYPOTHETICAL_RE.search(stripped):
        return "hypothetical"
    if _TENTATIVE_RE.search(stripped):
        return "tentative"
    if _QUOTED_RE.search(stripped):
        return "quoted"
    return "statement"


def _temporal(sentence: str) -> Tuple[str, Optional[int]]:
    situational = _SITUATIONAL_RE.search(sentence)
    if situational:
        word = situational.group().casefold()
        if word == "tomorrow":
            return "situational", _TOMORROW_SECONDS
        if word in {"lately", "these days"}:
            return "situational", _LATELY_SECONDS
        return "situational", _SITUATIONAL_SECONDS
    if _DATED_RE.search(sentence):
        return "dated", None
    if _LASTING_RE.search(sentence):
        return "lasting", None
    return "unknown", None


def _fragment(text: str, start: int, end: int, role: str = "") -> Fragment:
    return Fragment(text[start:end], start, end, role)


def _trim_end(text: str, start: int, end: int) -> int:
    while end > start and text[end - 1] in " \t,;:.!?…\"'”’)]":
        end -= 1
    return end


def read_message(
    text: str,
    *,
    language: str = "en",
    known_names: Iterable[str] = (),
    max_stones: int = MAX_STONES_PER_MESSAGE,
) -> List[StoneDraft]:
    """Read ``text`` into stones, one per meaningful sentence. Pure and deterministic.

    ``known_names`` are name keys already seen elsewhere (so "Sam lost" at the
    start of a sentence is still recognised as a person). Offsets in every
    fragment refer to ``text`` exactly as given.
    """
    if not isinstance(text, str) or not text.strip():
        return []
    text = text[:MAX_MESSAGE_CHARS]
    english = _is_english(language)
    known = frozenset(known_names)
    sentences = split_sentences(text)
    if english:
        # A name capitalized mid-sentence anywhere in this message is a name at the start of another sentence too.
        learned = {key for start, end in sentences[:MAX_STONES_PER_MESSAGE * 2]
                   for run in _name_runs(text[start:end], start, known) if run.certain for key, _ in run.parts}
        known = known | frozenset(learned)
    drafts: List[StoneDraft] = []
    for start, end in sentences:
        if len(drafts) >= max_stones:
            break
        sentence = text[start:end]
        word_terms = terms(sentence)
        runs = _name_runs(sentence, start, known) if english else []
        relations = list(_RELATION_RE.finditer(sentence)) if english else []
        # Filler such as "ok thanks" is not a memory; a name or a relation makes even a short sentence one.
        if len(word_terms) < 2 and not runs and not relations:
            continue
        answers: Dict[str, Answer] = {"what": Answer("stated", (_fragment(text, start, end),))}
        place_keys: List[str] = []
        role_keys: List[str] = []
        who: List[Fragment] = []
        where: Optional[Fragment] = None
        when: List[Fragment] = []
        why: Optional[Answer] = None
        how: Optional[Fragment] = None
        unresolved = False
        if english:
            relation_spans = [(match.start(), match.end()) for match in relations]
            for match in _FIRST_PERSON_RE.finditer(sentence):
                if any(low <= match.start() < high for low, high in relation_spans):
                    continue  # the "my" of "my friend" belongs to the relation, not a second fragment
                # "first_person" says only that the speaker is in the sentence; it does not say they did the thing.
                who.append(_fragment(text, start + match.start(), start + match.end(), "first_person"))
                break
            for match in relations:
                who.append(_fragment(text, start + match.start(), start + match.end(), "relation:" + match.group(1).casefold()))
                role_keys.append(match.group(1).casefold())
            place_match = _PLACE_NOUN_RE.search(sentence)
            if place_match:
                where = _fragment(text, start + place_match.start(), start + place_match.end())
                place_keys.append(place_match.group(1).casefold())
            else:
                for run in runs:
                    if run.display.endswith(("'s", "’s")):
                        continue  # "in Sam's car" is about Sam, not a place called Sam
                    prefix = text[max(start, run.start - 24):run.start]
                    preposition = _PLACE_PREP_BEFORE_RE.search(prefix)
                    if preposition:
                        where = _fragment(text, run.start - len(preposition.group()), run.end)
                        place_keys.extend(key for key, _ in run.parts)
                        break
            for run in runs:
                # "named" says only that a capitalized name appears: it may be a person, a team, a project or a thing.
                if where is not None and run.start < where.end and where.start < run.end:
                    continue  # it names the place, and the place has its own answer
                who.append(_fragment(text, run.start, run.end, "named"))
            who.sort(key=lambda f: (f.start, f.end))
            last_end = -1
            for time_match in _TIME_RE.finditer(sentence):
                if time_match.start() < last_end or len(when) >= 3:
                    continue
                when.append(_fragment(text, start + time_match.start(), start + time_match.end()))
                last_end = time_match.end()
            reason = _REASON_RE.search(sentence)
            motive = _MOTIVE_RE.search(sentence)
            if reason:
                stop = _trim_end(text, start + reason.start(), start + reason.end())
                why = Answer("stated", (_fragment(text, start + reason.start(), stop),), "reason")
            elif motive:
                stop = _trim_end(text, start + motive.start(), start + motive.end())
                why = Answer("stated", (_fragment(text, start + motive.start(), stop),), "motive")
            manner = _MANNER_RE.search(sentence)
            if manner:
                stop = _trim_end(text, start + manner.start(), start + manner.end())
                if stop > start + manner.start():
                    how = _fragment(text, start + manner.start(), stop)
            # "He lost." / "His team is..." point back at an earlier sentence; so does a pronoun with no name or relation near it.
            unresolved = bool(_THIRD_PRONOUN_RE.match(sentence)) or (
                bool(_THIRD_PRONOUN_RE.search(sentence)) and not runs and not relations)
        answers["who"] = Answer("stated", tuple(who)) if who else UNKNOWN
        answers["where"] = Answer("stated", (where,)) if where else UNKNOWN
        answers["when"] = Answer("stated", tuple(when)) if when else UNKNOWN
        answers["why"] = why if why else UNKNOWN
        answers["how"] = Answer("stated", (how,)) if how else UNKNOWN
        modality = _modality(sentence)
        temporal, expires = _temporal(sentence) if english else ("unknown", None)
        importance = 4 if modality == "question" else 5
        if _IMPORTANT_RE.search(sentence):
            importance = 8
        elif temporal == "lasting":
            importance = 6
        excerpt = sentence if len(sentence) <= MAX_EXCERPT_CHARS else sentence[:MAX_EXCERPT_CHARS - 1] + "…"
        new_names = tuple(sorted({pair for run in runs if run.certain for pair in run.parts}))
        name_keys = tuple(dict.fromkeys(key for run in runs for key, _ in run.parts))
        drafts.append(StoneDraft(
            ordinal=len(drafts), start=start, end=end, excerpt=excerpt, answers=answers,
            word_terms=tuple(word_terms), name_terms=name_keys,
            role_terms=tuple(dict.fromkeys(role_keys)), place_terms=tuple(dict.fromkeys(place_keys)),
            modality=modality, temporal=temporal, importance=importance, unresolved_reference=unresolved,
            expires_after_seconds=expires, reading=READING_ENGLISH if english else READING_WORDS,
            new_names=new_names,
        ))
    return drafts


# ----------------------------------------------------------------------- grounding

def grounding_problems(text: str, draft: StoneDraft) -> List[str]:
    """Every filled answer must be an exact span of ``text``. Returns what is not (empty = grounded)."""
    problems: List[str] = []
    for slot in SLOTS:
        answer = draft.answers.get(slot)
        if answer is None:
            problems.append(f"{slot}: missing")
            continue
        if answer.state == "stated":
            if not answer.fragments:
                problems.append(f"{slot}: stated with no words")
            for fragment in answer.fragments:
                if not (0 <= fragment.start < fragment.end <= len(text)) or text[fragment.start:fragment.end] != fragment.text:
                    problems.append(f"{slot}: fragment {fragment.text!r} is not text[{fragment.start}:{fragment.end}]")
                elif not (draft.start <= fragment.start and fragment.end <= draft.end):
                    problems.append(f"{slot}: fragment {fragment.text!r} lies outside its sentence")
        elif answer.state != "unknown":
            problems.append(f"{slot}: unknown state {answer.state!r}")
    return problems


def _fold_char(char: str) -> str:
    """Lower-case one character without ever changing its length, so offsets stay honest."""
    lowered = char.lower()
    return lowered if len(lowered) == 1 else char


def ground_proposed_answers(sentence: str, proposed: Dict[str, str]) -> Tuple[Dict[str, Fragment], Dict[str, str]]:
    """Check answers proposed by a model (or anyone) against the sentence they claim to come from.

    A proposed answer is accepted only if its words appear in ``sentence``
    exactly (whitespace-insensitive, case-insensitive). The accepted fragment
    carries the real offsets and the real casing from the sentence. Anything
    else is rejected with a reason, so a language model can never put words
    into a stone that the person did not say.
    """
    flat_chars: List[str] = []
    raw_index: List[int] = []  # raw_index[i] = position in `sentence` of flat_chars[i]
    previous_space = False
    for position, char in enumerate(sentence):
        is_space = char.isspace()
        if is_space and previous_space:
            continue
        flat_chars.append(" " if is_space else _fold_char(char))
        raw_index.append(position)
        previous_space = is_space
    flat = "".join(flat_chars)
    accepted: Dict[str, Fragment] = {}
    rejected: Dict[str, str] = {}
    for slot, claim in proposed.items():
        if slot not in SLOTS:
            rejected[slot] = "not one of the six questions"
            continue
        wanted = "".join(" " if c.isspace() else _fold_char(c) for c in re.sub(r"\s+", " ", str(claim or "")).strip())
        if not wanted:
            rejected[slot] = "empty"
            continue
        found = flat.find(wanted)
        if found < 0:
            rejected[slot] = "these words are not in the sentence"
            continue
        begin = raw_index[found]
        finish = raw_index[found + len(wanted) - 1] + 1
        accepted[slot] = Fragment(sentence[begin:finish], begin, finish, "proposed")
    return accepted, rejected


__all__ = [
    "SLOTS", "Fragment", "Answer", "StoneDraft", "UNKNOWN", "READING_ENGLISH", "READING_WORDS",
    "MAX_MESSAGE_CHARS", "MAX_STONES_PER_MESSAGE", "MAX_EXCERPT_CHARS",
    "terms", "normalize_word", "split_sentences", "capitalized_candidates", "read_message",
    "grounding_problems", "ground_proposed_answers",
]
