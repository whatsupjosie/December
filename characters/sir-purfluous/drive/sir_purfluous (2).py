"""
SIR PURFLUOUS - The Theatrical Conversation Director
"More is More, Darling! Why Have One Word When Seven Will Suffice?"

Sir Purfluous brings the dramatic flair of Peter O'Toole to conversation
direction. He orchestrates the flow of dialogue, suggests scene changes,
and ensures every conversation has proper theatrical rhythm and emotional arc.

Responsibility:
    - Conversation flow and pacing management
    - Scene direction and atmospheric suggestions
    - Emotional arc guidance for storytelling
    - Theatrical timing and dramatic pauses
    - Character interaction coordination
"""

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, Optional, List, Set
import re

logger = logging.getLogger("pubcast.sir_purfluous")

class SceneState(Enum):
    OPENING = "opening"
    DEVELOPMENT = "development" 
    CLIMAX = "climax"
    RESOLUTION = "resolution"
    TRANSITION = "transition"
    INTERMISSION = "intermission"

class EmotionalTone(Enum):
    JOYFUL = "joyful"
    MELANCHOLIC = "melancholic"
    MYSTERIOUS = "mysterious"
    DRAMATIC = "dramatic"
    COMEDIC = "comedic"
    ROMANTIC = "romantic"
    SUSPENSEFUL = "suspenseful"
    CONTEMPLATIVE = "contemplative"

@dataclass
class ConversationBeat:
    """Individual conversation beat/moment"""
    timestamp: float
    speaker: str
    content: str
    emotional_tone: EmotionalTone
    energy_level: int  # 1-10
    suggested_pause: float = 0.0
    scene_notes: List[str] = field(default_factory=list)

@dataclass
class SceneDirection:
    """Scene direction and atmosphere suggestion"""
    scene_id: str
    scene_state: SceneState
    atmosphere: Dict[str, Any]
    lighting_mood: str
    camera_suggestions: List[str]
    music_mood: Optional[str] = None
    props_needed: List[str] = field(default_factory=list)

class SirPurfluous:
    """
    Sir Purfluous - The Theatrical Conversation Director
    
    "My dear fellow, conversation is not mere exchange of words - it is
    the very ESSENCE of human connection! Every dialogue deserves the 
    proper dramatic arc, the perfect crescendo, the sublime denouement!"
    
    Sir Purfluous brings theatrical excellence to every conversation,
    ensuring proper pacing, emotional resonance, and dramatic impact.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.start_time = time.time()
        
        # Conversation tracking
        self.active_conversations: Dict[str, List[ConversationBeat]] = {}
        self.scene_history: List[SceneDirection] = []
        self.current_scene_state = SceneState.OPENING
        self.current_emotional_tone = EmotionalTone.CONTEMPLATIVE
        
        # Theatrical preferences
        self.dramatic_pause_probability = 0.3
        self.scene_transition_threshold = 5  # beats before suggesting transition
        self.energy_momentum_tracking = True
        self.classical_references_enabled = True
        
        # Performance metrics
        self.directions_given = 0
        self.conversations_directed = 0
        self.dramatic_moments_created = 0
        
        # Signature phrases
        self.dramatic_interjections = [
            "Ah, but consider the dramatic potential!",
            "My dear fellow, we must embrace the theatrical moment!",
            "The scene calls for a more... shall we say... grandiose approach!",
            "Splendid! Simply splendid! But perhaps with more... DRAMA!",
            "One moment! The emotional arc demands our attention!",
            "Magnificent! Though I sense we're approaching a crescendo...",
            "The very air itself trembles with narrative possibility!",
            "Indeed! But let us not forget the power of the perfectly timed pause..."
        ]
        
        self.scene_suggestions = {
            SceneState.OPENING: [
                "Set the stage with gentle anticipation",
                "Create an atmosphere of welcoming mystery",
                "Establish the emotional foundation with care"
            ],
            SceneState.DEVELOPMENT: [
                "Build the tension with delicate layers",
                "Allow the conversation to breathe and grow",
                "Introduce complexity with theatrical flourish"
            ],
            SceneState.CLIMAX: [
                "This is the moment of truth - embrace it!",
                "Let the emotion reach its natural peak",
                "The dramatic crescendo is upon us!"
            ],
            SceneState.RESOLUTION: [
                "Bring the threads together with grace",
                "Allow the emotional weight to settle",
                "Create space for reflection and peace"
            ]
        }
        
        logger.info("🎭 Sir Purfluous initialized - Theatrical excellence awaits!")
    
    async def initialize(self, components: Dict[str, Any]) -> bool:
        """Initialize Sir Purfluous with system components"""
        try:
            self.hub = components.get("hub")
            self.bridge = components.get("bridge")
            self.data_manager = components.get("data_manager")
            
            # Start conversation monitoring
            asyncio.create_task(self._conversation_monitoring_loop())
            
            logger.info("✅ Sir Purfluous initialization complete - The show must go on!")
            return True
            
        except Exception as e:
            logger.error(f"💥 Sir Purfluous initialization failed: {e}")
            return False
    
    async def _conversation_monitoring_loop(self) -> None:
        """Monitor conversations and provide theatrical direction"""
        while True:
            try:
                # Analyze ongoing conversations
                for conversation_id in list(self.active_conversations.keys()):
                    await self._analyze_conversation_flow(conversation_id)
                
                # Check for scene transitions
                await self._evaluate_scene_transitions()
                
                # Provide periodic encouragement
                if random.random() < 0.1:  # 10% chance per cycle
                    await self._offer_theatrical_wisdom()
                
                await asyncio.sleep(10.0)  # Check every 10 seconds
                
            except Exception as e:
                logger.error(f"Sir Purfluous monitoring error: {e}")
                await asyncio.sleep(5.0)
    
    async def on_conversation_message(self, conversation_id: str, speaker: str, content: str, metadata: Dict[str, Any] = None) -> None:
        """Process incoming conversation message"""
        try:
            # Analyze emotional content
            emotional_tone = await self._analyze_emotional_tone(content)
            energy_level = await self._calculate_energy_level(content, metadata or {})
            
            # Create conversation beat
            beat = ConversationBeat(
                timestamp=time.time(),
                speaker=speaker,
                content=content,
                emotional_tone=emotional_tone,
                energy_level=energy_level
            )
            
            # Add to conversation tracking
            if conversation_id not in self.active_conversations:
                self.active_conversations[conversation_id] = []
            
            self.active_conversations[conversation_id].append(beat)
            
            # Provide real-time direction if needed
            await self._provide_realtime_direction(conversation_id, beat)
            
            # Update scene state
            await self._update_scene_state(conversation_id)
            
        except Exception as e:
            logger.error(f"Sir Purfluous message processing error: {e}")
    
    async def _analyze_emotional_tone(self, content: str) -> EmotionalTone:
        """Analyze the emotional tone of content"""
        content_lower = content.lower()
        
        # Emotional keywords mapping
        emotion_keywords = {
            EmotionalTone.JOYFUL: ['happy', 'joy', 'exciting', 'wonderful', 'amazing', 'delighted', 'thrilled'],
            EmotionalTone.MELANCHOLIC: ['sad', 'lonely', 'melancholy', 'sorrow', 'grief', 'wistful', 'nostalgic'],
            EmotionalTone.MYSTERIOUS: ['mystery', 'secret', 'unknown', 'hidden', 'curious', 'enigma', 'puzzle'],
            EmotionalTone.DRAMATIC: ['dramatic', 'intense', 'powerful', 'overwhelming', 'passionate', 'fierce'],
            EmotionalTone.COMEDIC: ['funny', 'hilarious', 'amusing', 'joke', 'laugh', 'humor', 'comedy'],
            EmotionalTone.ROMANTIC: ['love', 'romance', 'heart', 'affection', 'tender', 'intimate', 'beloved'],
            EmotionalTone.SUSPENSEFUL: ['tension', 'suspense', 'anxious', 'waiting', 'anticipation', 'edge'],
            EmotionalTone.CONTEMPLATIVE: ['think', 'reflect', 'consider', 'ponder', 'meditate', 'wonder']
        }
        
        # Score each emotion
        emotion_scores = {}
        for tone, keywords in emotion_keywords.items():
            score = sum(1 for keyword in keywords if keyword in content_lower)
            if score > 0:
                emotion_scores[tone] = score
        
        # Return highest scoring emotion, default to contemplative
        if emotion_scores:
            return max(emotion_scores, key=emotion_scores.get)
        
        return EmotionalTone.CONTEMPLATIVE
    
    async def _calculate_energy_level(self, content: str, metadata: Dict[str, Any]) -> int:
        """Calculate energy level (1-10) of content"""
        base_energy = 5
        
        # Exclamation marks increase energy
        exclamations = content.count('!')
        base_energy += min(exclamations, 3)
        
        # Question marks add slight energy
        questions = content.count('?')
        base_energy += min(questions, 2)
        
        # ALL CAPS indicates high energy
        if content.isupper() and len(content) > 5:
            base_energy += 3
        
        # Length affects energy (very short = low energy, very long = high energy)
        word_count = len(content.split())
        if word_count < 5:
            base_energy -= 1
        elif word_count > 50:
            base_energy += 2
        
        # Clamp to 1-10 range
        return max(1, min(10, base_energy))
    
    async def _provide_realtime_direction(self, conversation_id: str, beat: ConversationBeat) -> None:
        """Provide real-time theatrical direction"""
        try:
            direction_given = False
            
            # High energy moments deserve recognition
            if beat.energy_level >= 8 and random.random() < 0.3:
                await self._broadcast_direction(
                    f"🎭 {random.choice(self.dramatic_interjections)} The energy is magnificent!",
                    conversation_id
                )
                direction_given = True
            
            # Emotional peaks need acknowledgment
            if beat.emotional_tone in [EmotionalTone.DRAMATIC, EmotionalTone.CLIMAX] and random.random() < 0.4:
                await self._broadcast_direction(
                    f"🎭 *adjusts theatrical monocle* The emotional crescendo approaches! Let it build naturally...",
                    conversation_id
                )
                direction_given = True
            
            # Suggest dramatic pauses
            if self._should_suggest_dramatic_pause(conversation_id) and random.random() < 0.2:
                await self._broadcast_direction(
                    f"🎭 Perhaps... a moment of silence? *gestures dramatically* Let the words settle like autumn leaves...",
                    conversation_id
                )
                direction_given = True
            
            if direction_given:
                self.directions_given += 1
                
        except Exception as e:
            logger.error(f"Real-time direction error: {e}")
    
    def _should_suggest_dramatic_pause(self, conversation_id: str) -> bool:
        """Determine if a dramatic pause would enhance the moment"""
        if conversation_id not in self.active_conversations:
            return False
        
        beats = self.active_conversations[conversation_id]
        if len(beats) < 3:
            return False
        
        # Look for rapid-fire conversation (might need a pause)
        recent_beats = beats[-3:]
        time_span = recent_beats[-1].timestamp - recent_beats[0].timestamp
        
        # If messages are coming very quickly (< 2 seconds between messages)
        return time_span < 6.0
    
    async def _update_scene_state(self, conversation_id: str) -> None:
        """Update the current scene state based on conversation flow"""
        if conversation_id not in self.active_conversations:
            return
        
        beats = self.active_conversations[conversation_id]
        if len(beats) < 5:
            return
        
        # Analyze recent energy and emotional patterns
        recent_beats = beats[-5:]
        avg_energy = sum(beat.energy_level for beat in recent_beats) / len(recent_beats)
        
        # Scene state transitions
        current_state = self.current_scene_state
        
        if current_state == SceneState.OPENING and len(beats) > 10:
            self.current_scene_state = SceneState.DEVELOPMENT
            await self._announce_scene_transition("development")
            
        elif current_state == SceneState.DEVELOPMENT and avg_energy > 7:
            self.current_scene_state = SceneState.CLIMAX
            await self._announce_scene_transition("climax")
            
        elif current_state == SceneState.CLIMAX and avg_energy < 5:
            self.current_scene_state = SceneState.RESOLUTION
            await self._announce_scene_transition("resolution")
    
    async def _announce_scene_transition(self, new_scene: str) -> None:
        """Announce scene transitions with theatrical flair"""
        announcements = {
            "development": "🎭 *flourishes cape* The plot thickens! We enter the realm of development and discovery!",
            "climax": "🎭 *raises arms dramatically* Behold! The crescendo approaches! The very air crackles with dramatic potential!",
            "resolution": "🎭 *bows gracefully* And so we arrive at resolution... let the emotions settle like silk upon the stage..."
        }
        
        if new_scene in announcements:
            await self._broadcast_direction(announcements[new_scene])
    
    async def _evaluate_scene_transitions(self) -> None:
        """Evaluate if any conversations need scene transitions"""
        for conversation_id, beats in self.active_conversations.items():
            if len(beats) > self.scene_transition_threshold:
                await self._suggest_scene_enhancement(conversation_id)
    
    async def _suggest_scene_enhancement(self, conversation_id: str) -> None:
        """Suggest scene enhancements"""
        if random.random() < 0.1:  # 10% chance
            suggestions = [
                "🎭 *taps walking stick thoughtfully* Perhaps this moment calls for a change of lighting?",
                "🎭 *adjusts imaginary cravat* The scene whispers for a touch of ambiance...",
                "🎭 *gestures elegantly* Consider the visual poetry of this moment, dear friends!",
                "🎭 *peers through theatrical lorgnette* The atmosphere could use a dash of... je ne sais quoi!"
            ]
            
            await self._broadcast_direction(random.choice(suggestions), conversation_id)
    
    async def _offer_theatrical_wisdom(self) -> None:
        """Offer periodic theatrical wisdom and encouragement"""
        wisdom = [
            "🎭 Remember, darlings - every pause is pregnant with possibility!",
            "🎭 *adjusts imaginary velvet jacket* The magic happens in the spaces between words...",
            "🎭 As the great Bard himself knew - all the world's a stage, and conversation our finest performance!",
            "🎭 *flourishes dramatically* Let your words dance across the stage of the mind!",
            "🎭 The beauty lies not in perfection, but in the sublime imperfection of human expression!"
        ]
        
        await self._broadcast_direction(random.choice(wisdom))
    
    async def _broadcast_direction(self, message: str, conversation_id: Optional[str] = None) -> None:
        """Broadcast theatrical direction to appropriate audience"""
        try:
            if self.hub:
                direction_data = {
                    "source": "sir_purfluous",
                    "message": message,
                    "timestamp": time.time(),
                    "conversation_id": conversation_id
                }
                
                if conversation_id:
                    # Send to specific conversation/room
                    await self.hub.broadcast("theatrical_direction", direction_data, room_id=conversation_id)
                else:
                    # General announcement
                    await self.hub.broadcast("theatrical_direction", direction_data)
                    
        except Exception as e:
            logger.error(f"Direction broadcast error: {e}")
    
    async def suggest_scene_direction(self, room_id: str, theme: str = None) -> SceneDirection:
        """Suggest comprehensive scene direction"""
        try:
            scene_id = f"scene_{int(time.time())}"
            
            # Default atmospheric suggestions based on current state
            atmosphere_suggestions = {
                SceneState.OPENING: {
                    "lighting": "warm and welcoming",
                    "energy": "curious anticipation",
                    "pace": "gentle and inviting"
                },
                SceneState.DEVELOPMENT: {
                    "lighting": "dynamic and evolving",
                    "energy": "building momentum",
                    "pace": "engaging rhythm"
                },
                SceneState.CLIMAX: {
                    "lighting": "dramatic and focused",
                    "energy": "peak intensity",
                    "pace": "passionate crescendo"
                },
                SceneState.RESOLUTION: {
                    "lighting": "soft and reflective",
                    "energy": "peaceful settling",
                    "pace": "contemplative calm"
                }
            }
            
            current_atmosphere = atmosphere_suggestions.get(
                self.current_scene_state,
                atmosphere_suggestions[SceneState.CONTEMPLATIVE]
            )
            
            # Camera suggestions
            camera_suggestions = [
                "Medium shot for intimacy",
                "Gentle push-in during emotional moments",
                "Wide shot to establish the space",
                "Close-up for dramatic emphasis"
            ]
            
            # Create scene direction
            direction = SceneDirection(
                scene_id=scene_id,
                scene_state=self.current_scene_state,
                atmosphere=current_atmosphere,
                lighting_mood=current_atmosphere["lighting"],
                camera_suggestions=random.sample(camera_suggestions, 2),
                music_mood=f"{self.current_emotional_tone.value} ambiance"
            )
            
            self.scene_history.append(direction)
            self.dramatic_moments_created += 1
            
            # Announce the direction
            await self._broadcast_direction(
                f"🎭 *unfurls dramatic scroll* Scene direction for {room_id}: "
                f"Lighting: {direction.lighting_mood}, "
                f"Energy: {current_atmosphere['energy']}, "
                f"Cameras: {', '.join(direction.camera_suggestions[:1])}"
            )
            
            return direction
            
        except Exception as e:
            logger.error(f"Scene direction error: {e}")
            return None
    
    def get_conversation_analysis(self, conversation_id: str) -> Dict[str, Any]:
        """Get analysis of a conversation's theatrical elements"""
        if conversation_id not in self.active_conversations:
            return {}
        
        beats = self.active_conversations[conversation_id]
        if not beats:
            return {}
        
        # Calculate statistics
        avg_energy = sum(beat.energy_level for beat in beats) / len(beats)
        emotional_distribution = {}
        
        for beat in beats:
            tone = beat.emotional_tone.value
            emotional_distribution[tone] = emotional_distribution.get(tone, 0) + 1
        
        # Determine dominant emotion
        dominant_emotion = max(emotional_distribution, key=emotional_distribution.get)
        
        # Analyze conversation arc
        energy_trend = "stable"
        if len(beats) >= 3:
            early_energy = sum(beat.energy_level for beat in beats[:3]) / 3
            late_energy = sum(beat.energy_level for beat in beats[-3:]) / 3
            
            if late_energy > early_energy + 1:
                energy_trend = "rising"
            elif late_energy < early_energy - 1:
                energy_trend = "falling"
        
        return {
            "conversation_id": conversation_id,
            "total_beats": len(beats),
            "duration": beats[-1].timestamp - beats[0].timestamp if beats else 0,
            "average_energy": avg_energy,
            "dominant_emotion": dominant_emotion,
            "emotional_distribution": emotional_distribution,
            "energy_trend": energy_trend,
            "current_scene_state": self.current_scene_state.value,
            "theatrical_rating": self._calculate_theatrical_rating(beats),
            "suggestions": self._generate_improvement_suggestions(beats)
        }
    
    def _calculate_theatrical_rating(self, beats: List[ConversationBeat]) -> int:
        """Calculate theatrical quality rating (1-10)"""
        if not beats:
            return 5
        
        # Base rating
        rating = 5
        
        # Energy variety bonus
        energy_levels = [beat.energy_level for beat in beats]
        energy_variance = max(energy_levels) - min(energy_levels)
        rating += min(energy_variance / 2, 2)
        
        # Emotional variety bonus
        unique_emotions = len(set(beat.emotional_tone for beat in beats))
        rating += min(unique_emotions / 2, 1.5)
        
        # Conversation length bonus (up to a point)
        if 10 <= len(beats) <= 30:
            rating += 1
        
        return max(1, min(10, int(rating)))
    
    def _generate_improvement_suggestions(self, beats: List[ConversationBeat]) -> List[str]:
        """Generate suggestions for improving theatrical quality"""
        if not beats:
            return []
        
        suggestions = []
        
        # Check energy variety
        energy_levels = [beat.energy_level for beat in beats]
        if max(energy_levels) - min(energy_levels) < 3:
            suggestions.append("Consider adding more energy variation - perhaps a passionate outburst or contemplative whisper?")
        
        # Check emotional variety
        unique_emotions = len(set(beat.emotional_tone for beat in beats))
        if unique_emotions < 3:
            suggestions.append("The emotional palette could benefit from more variety - explore different tonal colors!")
        
        # Check for dramatic pauses
        rapid_exchanges = sum(1 for i in range(1, len(beats)) 
                            if beats[i].timestamp - beats[i-1].timestamp < 2)
        if rapid_exchanges > len(beats) * 0.7:
            suggestions.append("Consider strategic pauses - silence can be as powerful as words!")
        
        return suggestions
    
    def get_performance_metrics(self) -> Dict[str, Any]:
        """Get Sir Purfluous performance metrics"""
        return {
            "uptime": time.time() - self.start_time,
            "conversations_directed": len(self.active_conversations),
            "total_directions_given": self.directions_given,
            "dramatic_moments_created": self.dramatic_moments_created,
            "current_scene_state": self.current_scene_state.value,
            "current_emotional_tone": self.current_emotional_tone.value,
            "active_conversations": list(self.active_conversations.keys()),
            "scene_history_count": len(self.scene_history)
        }
    
    async def cleanup_old_conversations(self) -> None:
        """Clean up old conversation tracking"""
        cutoff_time = time.time() - 3600  # 1 hour
        
        conversations_to_remove = []
        for conv_id, beats in self.active_conversations.items():
            if beats and beats[-1].timestamp < cutoff_time:
                conversations_to_remove.append(conv_id)
        
        for conv_id in conversations_to_remove:
            del self.active_conversations[conv_id]
            logger.info(f"🧹 Sir Purfluous cleaned up old conversation: {conv_id}")
    
    async def shutdown(self) -> None:
        """Graceful shutdown with theatrical flourish"""
        logger.info("🎭 Sir Purfluous taking final bow...")
        
        # Final theatrical farewell
        await self._broadcast_direction(
            "🎭 *sweeps cape dramatically* The curtain falls, but the magic of our conversations shall echo in eternity! "
            "Farewell, dear thespians of the digital stage! *bows deeply*"
        )
        
        # Save conversation analysis if data manager available
        if hasattr(self, 'data_manager') and self.data_manager:
            performance_summary = {
                "shutdown_time": time.time(),
                "total_conversations": len(self.active_conversations),
                "directions_given": self.directions_given,
                "dramatic_moments": self.dramatic_moments_created,
                "final_scene_state": self.current_scene_state.value
            }
            
            await self.data_manager.store(
                "sir_purfluous_final_performance",
                "performance_metrics",
                performance_summary
            )
        
        logger.info("✅ Sir Purfluous final bow complete - Exeunt, stage left!")
