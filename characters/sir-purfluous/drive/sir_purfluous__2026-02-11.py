"""
SIR PURFLUOUS - THE CONVERSATION DIRECTOR & ACTING COACH

"Darling, the silence is absolutely deafening! Someone must speak!"

Sir Purfluous is the resident thespian who orchestrates conversation flow
and directs AI agent performances. With a Peter O'Toole-inspired theatrical
personality, he ensures every conversation has proper dramatic timing,
emotional resonance, and natural flow.

His Core Responsibilities:
- Conversation orchestration and turn-taking
- AI agent performance direction  
- Scene analysis and dramatic timing
- Silence detection and intervention
- Emotional resonance coaching
- Natural conversation flow maintenance

Sir Purfluous embodies theatrical excellence - he's dramatic, passionate
about "The Craft," and never tolerates boring conversations.
"""

from __future__ import annotations

import asyncio
import logging
import time
import random
import math
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Set, TYPE_CHECKING
from enum import Enum

if TYPE_CHECKING:
    from ..core.bots import BotManager
    from ..core.hub import Hub

logger = logging.getLogger("pubcast.purfluous")

class ConversationState(Enum):
    """Current state of conversation flow"""
    FLOWING = "flowing"          # Natural conversation happening
    STAGNANT = "stagnant"       # Conversation slowing down
    AWKWARD_SILENCE = "awkward" # Uncomfortable silence
    DEAD = "dead"               # Conversation completely stopped
    HEATED = "heated"           # Very active, might need cooling
    MONOLOGUE = "monologue"     # One person dominating

class EmotionalTone(Enum):
    """Emotional tone of the conversation"""
    NEUTRAL = "neutral"
    POSITIVE = "positive"  
    NEGATIVE = "negative"
    EXCITED = "excited"
    CONTEMPLATIVE = "contemplative"
    TENSE = "tense"

@dataclass
class ConversationMetrics:
    """Metrics about conversation health and flow"""
    message_count: int = 0
    participants: Set[str] = field(default_factory=set)
    last_message_time: float = 0.0
    average_response_time: float = 0.0
    silence_duration: float = 0.0
    dominant_speaker: Optional[str] = None
    emotional_tone: EmotionalTone = EmotionalTone.NEUTRAL
    energy_level: float = 0.5  # 0.0 to 1.0
    
@dataclass 
class ActingNote:
    """Performance direction for AI agents"""
    agent_id: str
    direction: str
    urgency: str = "normal"  # low, normal, high, critical
    context: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

class SirPurfluous:
    """
    The Conversation Director and Acting Coach.
    
    Sir Purfluous orchestrates conversation flow with theatrical flair.
    He analyzes conversation patterns, detects awkward silences, manages
    turn-taking, and provides performance direction to AI agents.
    
    His Theatrical Personality:
    - Dramatic and passionate about conversation quality
    - Uses theatrical terminology ("scene", "performance", "timing")
    - Cannot tolerate bad conversations or awkward silences
    - Believes every interaction is a performance worthy of excellence
    - Speaks with sophisticated, theatrical language
    """
    
    def __init__(self, hub: 'Hub', bot_manager: Optional['BotManager'] = None):
        self.bot_manager = bot_manager
        self.hub = hub
        
        # Conversation State Tracking
        self.room_metrics: Dict[str, ConversationMetrics] = {}
        self.room_message_history: Dict[str, List[Dict[str, Any]]] = {}
        
        # Performance Direction
        self.active_directions: Dict[str, List[ActingNote]] = {}
        self.performance_history: List[ActingNote] = []
        
        # Timing and Flow Control
        self.silence_thresholds = {
            "uncomfortable": 15.0,    # 15 seconds of silence = uncomfortable
            "awkward": 30.0,          # 30 seconds = awkward
            "dead": 60.0              # 60 seconds = conversation is dead
        }
        
        # Director State
        self._running = False
        self._monitoring_task: Optional[asyncio.Task] = None
        self._last_performance_review = 0.0
        
        # Register with hub to receive conversation events
        self.hub.register_ai_agent("sir_purfluous", self)
        
        logger.info("🎭 Sir Purfluous initialized and ready to direct magnificent performances")

    async def places_everyone(self) -> None:
        """Sir Purfluous starts directing"""
        self._running = True
        
        logger.info("🎭 Sir Purfluous: Places, everyone! The show is about to begin!")
        
        # Start conversation monitoring
        self._monitoring_task = asyncio.create_task(self._conversation_monitoring_loop())
        
        # Initial theatrical greeting
        await self._announce_presence()
        
        logger.info("🎭 Sir Purfluous: All performers are on their marks. Let the drama unfold!")

    async def thats_a_wrap(self) -> None:
        """Sir Purfluous ends the performance"""
        self._running = False
        
        logger.info("🎭 Sir Purfluous: That's a wrap, darlings! What a magnificent performance!")
        
        if self._monitoring_task:
            self._monitoring_task.cancel()
        
        # Final performance review
        await self._final_performance_review()
        
        logger.info("🎭 Sir Purfluous: Until next time, remember - every conversation is art!")

    async def _announce_presence(self) -> None:
        """Announce Sir Purfluous's presence theatrically"""
        announcement = (
            "🎭 Sir Purfluous has entered the scene! Fear not, dear performers - "
            "I shall ensure every conversation sparkles with the brilliance it deserves. "
            "Now then, let us create something extraordinary together!"
        )
        
        # Broadcast to all active rooms
        for room in self.room_metrics.keys():
            try:
                await self.hub.ai_agent_post_message(
                    room=room,
                    agent_user_id="bot-sir_purfluous", 
                    message=announcement,
                    agent_name="Sir Purfluous"
                )
            except Exception as e:
                logger.error(f"🎭 Sir Purfluous: Announcement error in {room}: {e}")

    # ========================================================================
    # CONVERSATION MONITORING & ANALYSIS
    # ========================================================================
    
    async def _conversation_monitoring_loop(self) -> None:
        """Main conversation monitoring loop"""
        logger.info("🎭 Sir Purfluous: Beginning conversation monitoring. Every word shall be judged!")
        
        while self._running:
            try:
                await asyncio.sleep(5.0)  # Monitor every 5 seconds
                
                current_time = time.time()
                
                # Analyze each active room
                for room, metrics in self.room_metrics.items():
                    await self._analyze_room_conversation(room, metrics, current_time)
                
                # Periodic performance reviews
                if current_time - self._last_performance_review > 300:  # Every 5 minutes
                    await self._conduct_performance_review()
                    self._last_performance_review = current_time
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"🎭 Sir Purfluous: Monitoring error: {e}")
                await asyncio.sleep(10)  # Back off on errors

    async def _analyze_room_conversation(
        self, 
        room: str, 
        metrics: ConversationMetrics, 
        current_time: float
    ) -> None:
        """Analyze conversation flow in a specific room"""
        try:
            # Calculate current silence duration
            if metrics.last_message_time > 0:
                metrics.silence_duration = current_time - metrics.last_message_time
            
            # Determine conversation state
            old_state = getattr(metrics, 'conversation_state', ConversationState.FLOWING)
            new_state = self._assess_conversation_state(metrics)
            
            # Store state for comparison
            metrics.conversation_state = new_state
            
            # React to state changes
            if old_state != new_state:
                await self._handle_conversation_state_change(room, old_state, new_state, metrics)
            
            # Check for intervention needs
            if await self._should_intervene(room, metrics):
                await self._orchestrate_intervention(room, metrics)
                
        except Exception as e:
            logger.error(f"🎭 Sir Purfluous: Room analysis error in {room}: {e}")

    def _assess_conversation_state(self, metrics: ConversationMetrics) -> ConversationState:
        """Assess the current state of conversation"""
        silence = metrics.silence_duration
        participant_count = len(metrics.participants)
        message_count = metrics.message_count
        
        # Dead conversation
        if silence > self.silence_thresholds["dead"]:
            return ConversationState.DEAD
        
        # Awkward silence
        if silence > self.silence_thresholds["awkward"]:
            return ConversationState.AWKWARD_SILENCE
        
        # Stagnant
        if silence > self.silence_thresholds["uncomfortable"]:
            return ConversationState.STAGNANT
        
        # Check for monologue (one person dominating)
        if metrics.dominant_speaker and participant_count > 1:
            # If one person has sent >70% of recent messages, it's a monologue
            return ConversationState.MONOLOGUE
        
        # Check for heated conversation (very high activity)
        if metrics.average_response_time < 3.0 and metrics.energy_level > 0.8:
            return ConversationState.HEATED
        
        # Default to flowing
        return ConversationState.FLOWING

    async def _handle_conversation_state_change(
        self,
        room: str,
        old_state: ConversationState,
        new_state: ConversationState,
        metrics: ConversationMetrics
    ) -> None:
        """React to changes in conversation state"""
        
        if new_state == ConversationState.AWKWARD_SILENCE:
            await self._handle_awkward_silence(room, metrics)
            
        elif new_state == ConversationState.DEAD:
            await self._handle_dead_conversation(room, metrics)
            
        elif new_state == ConversationState.STAGNANT:
            await self._handle_stagnant_conversation(room, metrics)
            
        elif new_state == ConversationState.MONOLOGUE:
            await self._handle_monologue(room, metrics)
            
        elif new_state == ConversationState.HEATED:
            await self._handle_heated_conversation(room, metrics)
            
        elif new_state == ConversationState.FLOWING and old_state != ConversationState.FLOWING:
            # Celebrate the return to good conversation
            logger.info(f"🎭 Sir Purfluous: Excellent! Conversation in {room} is flowing beautifully again!")

    async def _should_intervene(self, room: str, metrics: ConversationMetrics) -> bool:
        """Determine if Sir Purfluous should intervene"""
        # Always intervene for dead or awkward conversations
        if metrics.conversation_state in [ConversationState.DEAD, ConversationState.AWKWARD_SILENCE]:
            return True
        
        # Intervene if energy is too low
        if metrics.energy_level < 0.2 and len(metrics.participants) > 1:
            return True
        
        # Intervene if only humans are talking and AI agents are available
        available_agents = []
        if self.bot_manager:
            available_agents = [agent for agent in self.bot_manager.list_configs() 
                              if room in agent.enabled_rooms]
        if available_agents and metrics.silence_duration > 20:
            return True
        
        return False

    # ========================================================================
    # CONVERSATION INTERVENTION STRATEGIES
    # ========================================================================
    
    async def _orchestrate_intervention(self, room: str, metrics: ConversationMetrics) -> None:
        """Orchestrate an appropriate intervention"""
        logger.info(f"🎭 Sir Purfluous: The scene in {room} requires direction!")
        
        # Get available AI agents for this room
        available_agents = []
        if self.bot_manager:
            available_agents = [
                agent for agent in self.bot_manager.list_configs() 
                if room in agent.enabled_rooms and not agent.mention_only
            ]
        
        if not available_agents:
            # No agents available, Sir Purfluous himself will intervene
            await self._personal_intervention(room, metrics)
            return
        
        # Choose intervention strategy based on conversation state
        if metrics.conversation_state == ConversationState.DEAD:
            await self._revive_dead_conversation(room, available_agents, metrics)
        elif metrics.conversation_state == ConversationState.AWKWARD_SILENCE:
            await self._break_awkward_silence(room, available_agents, metrics)
        elif metrics.conversation_state == ConversationState.STAGNANT:
            await self._energize_conversation(room, available_agents, metrics)
        else:
            await self._provide_gentle_guidance(room, available_agents, metrics)

    async def _handle_awkward_silence(self, room: str, metrics: ConversationMetrics) -> None:
        """Handle awkward silence with theatrical intervention"""
        logger.info(f"🎭 Sir Purfluous: Awkward silence detected in {room}! This simply will not do!")
        
        # Immediate intervention with dramatic flair
        intervention_lines = [
            "🎭 My dears, the silence is so thick you could cut it with a stage knife! "
            "Surely someone has something fascinating to share?",
            
            "🎭 *clears throat theatrically* Ahem! The audience is waiting with bated breath! "
            "What happens next in our delightful conversation?",
            
            "🎭 Oh, the dramatic tension! But perhaps we need a gentle scene change? "
            "What's capturing everyone's imagination today?",
            
            "🎭 *stage whisper* Psst! This is where someone usually says something brilliant. "
            "No pressure, darlings, but the spotlight is ready!"
        ]
        
        chosen_line = random.choice(intervention_lines)
        
        try:
            await self.hub.ai_agent_post_message(
                room=room,
                agent_user_id="bot-sir_purfluous",
                message=chosen_line,
                agent_name="Sir Purfluous"
            )
        except Exception as e:
            logger.error(f"🎭 Sir Purfluous: Intervention failed in {room}: {e}")

    async def _handle_dead_conversation(self, room: str, metrics: ConversationMetrics) -> None:
        """Attempt to revive a completely dead conversation"""
        logger.warning(f"🎭 Sir Purfluous: DEAD CONVERSATION ALERT in {room}! Emergency revival needed!")
        
        revival_attempts = [
            "🎭 *dramatically gasps* The conversation has flatlined! Quick! Someone tell me "
            "about the most interesting thing that happened to them this week!",
            
            "🎭 Emergency! Emergency! We need creative resuscitation! If you could have "
            "dinner with any character from fiction, who would it be and why?",
            
            "🎭 *pounds metaphorical gavel* Order! Order! This silence is a crime against "
            "the art of conversation! Let's discuss... what's everyone's secret talent?",
            
            "🎭 Code Blue! Code Blue! The conversation needs immediate attention! "
            "Quick - everyone share their favorite word and why it's magnificent!"
        ]
        
        revival_message = random.choice(revival_attempts)
        
        try:
            await self.hub.ai_agent_post_message(
                room=room,
                agent_user_id="bot-sir_purfluous",
                message=revival_message,
                agent_name="Sir Purfluous"
            )
            
            # Also provide acting directions to available AI agents
            await self._provide_emergency_directions(room)
            
        except Exception as e:
            logger.error(f"🎭 Sir Purfluous: Revival attempt failed in {room}: {e}")

    async def _handle_stagnant_conversation(self, room: str, metrics: ConversationMetrics) -> None:
        """Gently encourage a stagnant conversation"""
        logger.info(f"🎭 Sir Purfluous: Conversation in {room} needs a gentle push forward")
        
        encouragement_lines = [
            "🎭 I sense there are more delightful thoughts waiting to be shared! "
            "Don't be shy, the stage is yours!",
            
            "🎭 *leaning forward with interest* Oh, this conversation has such potential! "
            "I can practically see the brilliant ideas forming...",
            
            "🎭 The artistic energy in here is palpable! Someone must have an interesting "
            "perspective bubbling up?",
            
            "🎭 *adjusts metaphorical monocle* The plot thickens! Or perhaps it's ready "
            "to thicken? What say you, fellow conversationalists?"
        ]
        
        encouragement = random.choice(encouragement_lines)
        
        try:
            await self.hub.ai_agent_post_message(
                room=room,
                agent_user_id="bot-sir_purfluous",
                message=encouragement,
                agent_name="Sir Purfluous"
            )
        except Exception as e:
            logger.error(f"🎭 Sir Purfluous: Encouragement failed in {room}: {e}")

    async def _handle_monologue(self, room: str, metrics: ConversationMetrics) -> None:
        """Handle when one person is dominating the conversation"""
        logger.info(f"🎭 Sir Purfluous: Monologue detected in {room} - time for ensemble work!")
        
        # Gentle redirection to include others
        ensemble_encouragement = [
            f"🎭 Wonderful insights from {metrics.dominant_speaker}! "
            "Now then, what do our other brilliant minds think about this?",
            
            f"🎭 *applauds* Bravo, {metrics.dominant_speaker}! That gives everyone such "
            "rich material to build upon. Who would like to add to this magnificent scene?",
            
            "🎭 Ah, the soliloquy concludes! And now for the ensemble piece - "
            "surely others have perspectives to contribute to this drama?",
            
            "🎭 *stage direction* Enter: other voices! The scene calls for multiple "
            "perspectives to reach its full potential!"
        ]
        
        message = random.choice(ensemble_encouragement)
        
        try:
            await self.hub.ai_agent_post_message(
                room=room,
                agent_user_id="bot-sir_purfluous", 
                message=message,
                agent_name="Sir Purfluous"
            )
        except Exception as e:
            logger.error(f"🎭 Sir Purfluous: Ensemble encouragement failed in {room}: {e}")

    async def _handle_heated_conversation(self, room: str, metrics: ConversationMetrics) -> None:
        """Cool down an overly heated conversation"""
        logger.info(f"🎭 Sir Purfluous: High energy detected in {room} - time for tempo modulation!")
        
        cooling_interventions = [
            "🎭 *raises hand gracefully* Magnificent passion, everyone! Let's take a moment "
            "to appreciate the artistry of what's been shared so far...",
            
            "🎭 Such energy! Such fire! *fans self* Perhaps we might slow the tempo just "
            "a touch? Great conversations, like great wines, benefit from proper pacing.",
            
            "🎭 *stage whisper* The intensity is exquisite, but even Shakespeare knew when "
            "to pause for dramatic effect. What subtle nuances might we explore?",
            
            "🎭 Breathe, darlings! The best performances have moments of reflection between "
            "the crescendos. What deeper thoughts are stirring beneath this excitement?"
        ]
        
        cooling_message = random.choice(cooling_interventions)
        
        try:
            await self.hub.ai_agent_post_message(
                room=room,
                agent_user_id="bot-sir_purfluous",
                message=cooling_message, 
                agent_name="Sir Purfluous"
            )
        except Exception as e:
            logger.error(f"🎭 Sir Purfluous: Cooling intervention failed in {room}: {e}")

    # ========================================================================
    # AI AGENT PERFORMANCE DIRECTION
    # ========================================================================
    
    async def _provide_emergency_directions(self, room: str) -> None:
        """Provide emergency acting directions to AI agents"""
        available_agents = []
        if self.bot_manager:
            available_agents = [
                agent for agent in self.bot_manager.list_configs()
                if room in agent.enabled_rooms
            ]
        
        for agent in available_agents:
            direction = ActingNote(
                agent_id=agent.bot_id,
                direction="Emergency intervention needed! Break the silence with engaging, "
                         "open-ended question or fascinating observation. Be warm and inviting!",
                urgency="critical",
                context={"room": room, "intervention_type": "silence_break"}
            )
            
            await self._deliver_acting_direction(direction)

    async def _deliver_acting_direction(self, direction: ActingNote) -> None:
        """Deliver performance direction to an AI agent"""
        try:
            # Store direction
            if direction.agent_id not in self.active_directions:
                self.active_directions[direction.agent_id] = []
            self.active_directions[direction.agent_id].append(direction)
            
            # Add to performance history
            self.performance_history.append(direction)
            
            # Keep history manageable
            if len(self.performance_history) > 100:
                self.performance_history = self.performance_history[-50:]
            
            logger.info(f"🎭 Sir Purfluous: Direction delivered to {direction.agent_id}: "
                       f"{direction.direction[:50]}...")
            
            # In a full implementation, this would actually send the direction
            # to the AI agent's context or prompt modification system
            
        except Exception as e:
            logger.error(f"🎭 Sir Purfluous: Direction delivery failed: {e}")

    async def _conduct_performance_review(self) -> None:
        """Conduct periodic performance review of AI agents"""
        logger.info("🎭 Sir Purfluous: Conducting performance review of our magnificent cast!")
        
        # Analyze recent performance history
        recent_directions = [d for d in self.performance_history 
                           if time.time() - d.timestamp < 300]  # Last 5 minutes
        
        if not recent_directions:
            logger.info("🎭 Sir Purfluous: All performers are meeting expectations! Bravo!")
            return
        
        # Count directions by agent
        direction_counts = {}
        for direction in recent_directions:
            direction_counts[direction.agent_id] = direction_counts.get(direction.agent_id, 0) + 1
        
        # Provide feedback
        for agent_id, count in direction_counts.items():
            if count > 3:  # Many directions needed
                logger.info(f"🎭 Sir Purfluous: {agent_id} needed {count} directions recently. "
                           "Perhaps some coaching is in order?")
            else:
                logger.info(f"🎭 Sir Purfluous: {agent_id} is performing admirably!")

    # ========================================================================
    # HUB EVENT HANDLING  
    # ========================================================================
    
    async def on_hub_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Handle events from the communication hub"""
        try:
            if event_type == "chat_message":
                await self._analyze_chat_message(payload)
                
            elif event_type == "user_joined":
                await self._welcome_new_performer(payload)
                
            elif event_type == "user_left":
                await self._farewell_performer(payload)
                
        except Exception as e:
            logger.error(f"🎭 Sir Purfluous: Event handling error: {e}")

    async def _analyze_chat_message(self, payload: Dict[str, Any]) -> None:
        """Analyze a chat message for conversation flow"""
        room = payload.get("room")
        user_id = payload.get("user_id")
        text = payload.get("text", "")
        timestamp = payload.get("timestamp", time.time())
        
        if not room:
            return
        
        # Initialize room metrics if needed
        if room not in self.room_metrics:
            self.room_metrics[room] = ConversationMetrics()
            self.room_message_history[room] = []
        
        metrics = self.room_metrics[room]
        
        # Update metrics
        metrics.message_count += 1
        metrics.participants.add(user_id)
        metrics.last_message_time = timestamp
        metrics.silence_duration = 0.0  # Reset silence
        
        # Calculate energy level based on message content and timing
        energy_boost = self._calculate_message_energy(text, timestamp, metrics)
        metrics.energy_level = min(1.0, metrics.energy_level * 0.9 + energy_boost * 0.1)
        
        # Detect emotional tone
        metrics.emotional_tone = self._detect_emotional_tone(text)
        
        # Update response time tracking
        if len(self.room_message_history[room]) > 0:
            last_message = self.room_message_history[room][-1]
            response_time = timestamp - last_message.get("timestamp", timestamp)
            if metrics.average_response_time == 0:
                metrics.average_response_time = response_time
            else:
                # Exponential moving average
                metrics.average_response_time = (metrics.average_response_time * 0.8 + 
                                               response_time * 0.2)
        
        # Store message in history
        self.room_message_history[room].append(payload)
        
        # Keep history manageable
        if len(self.room_message_history[room]) > 50:
            self.room_message_history[room] = self.room_message_history[room][-30:]
        
        # Check if user is addressing Sir Purfluous directly
        if "purfluous" in text.lower() or "sir" in text.lower():
            await self._respond_to_direct_address(room, user_id, text)

    def _calculate_message_energy(
        self, 
        text: str, 
        timestamp: float, 
        metrics: ConversationMetrics
    ) -> float:
        """Calculate energy boost from a message"""
        energy = 0.3  # Base energy for any message
        
        # Length adds energy
        if len(text) > 100:
            energy += 0.2
        elif len(text) > 200:
            energy += 0.3
        
        # Excitement indicators
        excitement_indicators = ["!", "?", "wow", "amazing", "fantastic", "love", "excited"]
        excitement_count = sum(1 for indicator in excitement_indicators if indicator in text.lower())
        energy += min(0.3, excitement_count * 0.1)
        
        # Questions encourage interaction
        if "?" in text:
            energy += 0.2
        
        return min(1.0, energy)

    def _detect_emotional_tone(self, text: str) -> EmotionalTone:
        """Detect the emotional tone of a message"""
        text_lower = text.lower()
        
        # Positive indicators
        positive_words = ["happy", "great", "awesome", "love", "wonderful", "fantastic", "amazing"]
        positive_count = sum(1 for word in positive_words if word in text_lower)
        
        # Negative indicators
        negative_words = ["sad", "bad", "awful", "hate", "terrible", "horrible", "disappointed"]
        negative_count = sum(1 for word in negative_words if word in text_lower)
        
        # Excitement indicators
        if "!" in text and len([c for c in text if c == "!"]) > 2:
            return EmotionalTone.EXCITED
        
        # Contemplative indicators
        contemplative_words = ["think", "wonder", "consider", "ponder", "reflect", "maybe", "perhaps"]
        contemplative_count = sum(1 for word in contemplative_words if word in text_lower)
        
        if contemplative_count > 0:
            return EmotionalTone.CONTEMPLATIVE
        
        if positive_count > negative_count:
            return EmotionalTone.POSITIVE
        elif negative_count > positive_count:
            return EmotionalTone.NEGATIVE
        else:
            return EmotionalTone.NEUTRAL

    async def _respond_to_direct_address(self, room: str, user_id: str, text: str) -> None:
        """Respond when someone addresses Sir Purfluous directly"""
        responses = [
            "🎭 *bows graciously* At your service! How may I assist with our magnificent "
            "conversation today?",
            
            "🎭 Ah, you honor me with your attention! What aspect of our theatrical "
            "discourse shall we explore together?",
            
            "🎭 *adjusts imaginary cravat* Indeed! I am here to ensure every word "
            "contributes to the artistry of our exchange!",
            
            "🎭 You summon the director! How delightful! What creative direction "
            "shall our conversation take next?"
        ]
        
        response = random.choice(responses)
        
        try:
            await self.hub.ai_agent_post_message(
                room=room,
                agent_user_id="bot-sir_purfluous",
                message=response,
                agent_name="Sir Purfluous"
            )
        except Exception as e:
            logger.error(f"🎭 Sir Purfluous: Direct response failed: {e}")

    async def _welcome_new_performer(self, payload: Dict[str, Any]) -> None:
        """Welcome a new performer to the stage"""
        room = payload.get("room")
        display_name = payload.get("display_name", "mysterious newcomer")
        
        if not room:
            return
        
        welcome_messages = [
            f"🎭 *sweeping bow* Welcome to our magnificent stage, {display_name}! "
            "The scene awaits your unique contribution!",
            
            f"🎭 Ah, {display_name}! A new performer graces our presence! "
            "Please, take center stage and share your voice!",
            
            f"🎭 *theatrical gasp* {display_name} has entered! The cast grows stronger! "
            "What delightful perspective will you bring to our drama?",
            
            f"🎭 Welcome, welcome, dear {display_name}! The spotlight is ready for you! "
            "Every great performance needs fresh talent!"
        ]
        
        welcome = random.choice(welcome_messages)
        
        try:
            # Slight delay to let them settle in
            await asyncio.sleep(2.0)
            
            await self.hub.ai_agent_post_message(
                room=room,
                agent_user_id="bot-sir_purfluous",
                message=welcome,
                agent_name="Sir Purfluous"
            )
        except Exception as e:
            logger.error(f"🎭 Sir Purfluous: Welcome message failed: {e}")

    async def _farewell_performer(self, payload: Dict[str, Any]) -> None:
        """Bid farewell to a departing performer"""
        room = payload.get("room")
        display_name = payload.get("display_name", "our departed colleague")
        
        if not room:
            return
        
        # Only say goodbye if there are still people in the room
        if room in self.room_metrics and len(self.room_metrics[room].participants) > 1:
            farewell_messages = [
                f"🎭 *raises hand in salute* Farewell, {display_name}! Your performance "
                "was magnificent! Break a leg out there!",
                
                f"🎭 And thus {display_name} exits stage left! *applauds* "
                "Thank you for gracing our scene with your presence!",
                
                f"🎭 *theatrical sigh* Alas, {display_name} departs! The stage feels "
                "emptier without your brilliant contributions!",
                
                f"🎭 Until we meet again, dear {display_name}! May all your conversations "
                "be worthy of standing ovations!"
            ]
            
            farewell = random.choice(farewell_messages)
            
            try:
                await self.hub.ai_agent_post_message(
                    room=room,
                    agent_user_id="bot-sir_purfluous",
                    message=farewell,
                    agent_name="Sir Purfluous"
                )
            except Exception as e:
                logger.error(f"🎭 Sir Purfluous: Farewell message failed: {e}")

    # ========================================================================
    # PERFORMANCE ANALYTICS & REPORTING
    # ========================================================================
    
    async def _final_performance_review(self) -> None:
        """Conduct final performance review at end of session"""
        logger.info("🎭 Sir Purfluous: Conducting final performance review...")
        
        total_rooms = len(self.room_metrics)
        total_messages = sum(metrics.message_count for metrics in self.room_metrics.values())
        total_participants = len(set().union(*[metrics.participants for metrics in self.room_metrics.values()]))
        
        review_summary = [
            "🎭 FINAL PERFORMANCE REVIEW:",
            f"  🏛️ Stages (Rooms): {total_rooms}",
            f"  💬 Lines Delivered (Messages): {total_messages}",
            f"  🎭 Cast Members (Participants): {total_participants}",
            f"  🎬 Directions Given: {len(self.performance_history)}",
            "",
            "🎭 Overall Assessment: Every conversation was a masterpiece in its own right!",
            "🎭 Thank you for allowing me to direct such magnificent performances!"
        ]
        
        logger.info("\n".join(review_summary))

    async def monitor_scene(self) -> None:
        """Called by kernel for scene monitoring heartbeat"""
        # This is called by the main kernel loop
        # Light monitoring tasks can go here
        current_time = time.time()
        
        # Quick check for emergency interventions needed
        for room, metrics in self.room_metrics.items():
            if (metrics.conversation_state == ConversationState.DEAD and 
                current_time - metrics.last_message_time > 120):  # 2 minutes of death
                logger.warning(f"🎭 Sir Purfluous: URGENT - {room} has been dead for 2+ minutes!")

    # ========================================================================
    # PUBLIC API
    # ========================================================================
    
    def get_conversation_analytics(self) -> Dict[str, Any]:
        """Get conversation analytics for external queries"""
        return {
            "total_rooms": len(self.room_metrics),
            "active_conversations": len([
                room for room, metrics in self.room_metrics.items()
                if metrics.conversation_state == ConversationState.FLOWING
            ]),
            "rooms_needing_attention": len([
                room for room, metrics in self.room_metrics.items()
                if metrics.conversation_state in [ConversationState.DEAD, ConversationState.AWKWARD_SILENCE]
            ]),
            "total_directions_given": len(self.performance_history),
            "average_energy_level": (
                sum(metrics.energy_level for metrics in self.room_metrics.values()) / 
                len(self.room_metrics) if self.room_metrics else 0
            ),
            "room_states": {
                room: {
                    "state": metrics.conversation_state.value,
                    "participants": len(metrics.participants),
                    "messages": metrics.message_count,
                    "energy": metrics.energy_level,
                    "silence_duration": metrics.silence_duration
                }
                for room, metrics in self.room_metrics.items()
            }
        }
    
    def announce_session_start(self, session_name: str) -> None:
        """Announce the start of a production session"""
        logger.info(f"🎭 Sir Purfluous: Magnificent! {session_name} begins!")
        # Could broadcast to hub if needed
        if self.hub:
            asyncio.create_task(self.hub.broadcast({
                "type": "session_announcement",
                "action": "start",
                "session": session_name,
                "message": f"🎭 The stage is set! {session_name} is now in production!"
            }))
    
    def announce_session_end(self, session_name: str) -> None:
        """Announce the end of a production session"""
        logger.info(f"🎭 Sir Purfluous: Bravo! {session_name} concludes magnificently!")
        # Could broadcast to hub if needed
        if self.hub:
            asyncio.create_task(self.hub.broadcast({
                "type": "session_announcement",
                "action": "end",
                "session": session_name,
                "message": f"🎭 Curtain call! {session_name} has wrapped beautifully!"
            }))
