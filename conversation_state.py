"""Conversation state management for multi-turn dialogues."""

from typing import Dict, Optional, Any, List
from dataclasses import dataclass, field
from datetime import datetime
import json


@dataclass
class ConversationState:
    """Represents the current state of a conversation."""
    user_id: str
    flow_name: Optional[str] = None
    step: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    last_updated: datetime = field(default_factory=datetime.now)
    conversation_history: List[Dict[str, str]] = field(default_factory=list)  # Store recent messages for context
    
    def to_dict(self) -> dict:
        """Convert state to dictionary for storage."""
        return {
            "user_id": self.user_id,
            "flow_name": self.flow_name,
            "step": self.step,
            "data": self.data,
            "last_updated": self.last_updated.isoformat(),
            "conversation_history": self.conversation_history,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "ConversationState":
        """Create state from dictionary."""
        state = cls(
            user_id=data["user_id"],
            flow_name=data.get("flow_name"),
            step=data.get("step"),
            data=data.get("data", {}),
            conversation_history=data.get("conversation_history", []),
        )
        if "last_updated" in data:
            state.last_updated = datetime.fromisoformat(data["last_updated"])
        return state


class ConversationManager:
    """Manages conversation states in memory (can be extended to use database)."""
    
    def __init__(self):
        self._states: Dict[str, ConversationState] = {}
    
    def get_state(self, user_id: str) -> Optional[ConversationState]:
        """Get conversation state for a user."""
        return self._states.get(user_id)
    
    def set_state(self, user_id: str, state: ConversationState) -> None:
        """Set conversation state for a user."""
        state.last_updated = datetime.now()
        self._states[user_id] = state
    
    def update_state(self, user_id: str, **kwargs) -> ConversationState:
        """Update conversation state fields."""
        state = self.get_state(user_id)
        if state is None:
            state = ConversationState(user_id=user_id)
        
        for key, value in kwargs.items():
            if hasattr(state, key):
                setattr(state, key, value)
        
        self.set_state(user_id, state)
        return state
    
    def clear_state(self, user_id: str) -> None:
        """Clear conversation state for a user."""
        if user_id in self._states:
            del self._states[user_id]
    
    def update_data(self, user_id: str, **data) -> ConversationState:
        """Update data dictionary in conversation state."""
        state = self.get_state(user_id)
        if state is None:
            state = ConversationState(user_id=user_id)
        
        state.data.update(data)
        self.set_state(user_id, state)
        return state
    
    def add_message_to_history(self, user_id: str, user_message: str, bot_response: str, max_history: int = 5) -> None:
        """Add a message exchange to conversation history for context.
        
        Args:
            user_id: User identifier
            user_message: User's message
            bot_response: Bot's response
            max_history: Maximum number of recent exchanges to keep
        """
        state = self.get_state(user_id)
        if state is None:
            state = ConversationState(user_id=user_id)
        
        # Add new exchange
        state.conversation_history.append({
            "user": user_message,
            "bot": bot_response
        })
        
        # Keep only recent history
        if len(state.conversation_history) > max_history:
            state.conversation_history = state.conversation_history[-max_history:]
        
        self.set_state(user_id, state)
    
    def get_recent_context(self, user_id: str, max_exchanges: int = 3) -> str:
        """Get recent conversation context as a string for LLM prompts.
        
        Args:
            user_id: User identifier
            max_exchanges: Maximum number of recent exchanges to include
        
        Returns:
            Formatted context string
        """
        state = self.get_state(user_id)
        if not state or not state.conversation_history:
            return ""
        
        recent = state.conversation_history[-max_exchanges:]
        context_parts = []
        for exchange in recent:
            context_parts.append(f"User: {exchange['user']}")
            context_parts.append(f"Bot: {exchange['bot']}")
        
        return "\n".join(context_parts)


# Global conversation manager instance
conversation_manager = ConversationManager()


# Exit keywords for flow termination
EXIT_KEYWORDS = ["back", "menu", "main menu", "exit", "cancel", "quit", "stop", "done"]


def is_exit_request(message: str) -> bool:
    """Check if the message contains exit keywords.
    
    Args:
        message: The user's message
    
    Returns:
        True if message contains exit keywords, False otherwise
    """
    message_lower = message.lower().strip()
    return any(keyword in message_lower for keyword in EXIT_KEYWORDS)


def get_main_menu_message() -> str:
    """Get the standard main menu message.
    
    Returns:
        Standardized main menu message
    """
    return (
        "Sure! How can I help you today? 😊\n\n"
        "You can:\n"
        "• Browse used cars\n"
        "• Get car valuation\n"
        "• Calculate EMI\n"
        "• Book a service\n\n"
        "What would you like to do?"
    )


def is_short_response(message: str) -> bool:
    """Check if message is a short response that should be handled within current flow.
    
    Args:
        message: The user's message
    
    Returns:
        True if message is a short response (like "no", "yes", "change", etc.)
    """
    message_lower = message.lower().strip()
    short_responses = [
        "no", "n", "yes", "y", "ok", "okay", "sure", "fine", "alright",
        "change", "modify", "different", "new", "restart", "back",
        "1", "2", "3", "4", "5",  # Single digit responses
    ]
    return message_lower in short_responses or len(message_lower) <= 3


def detect_flow_switch(intent_result: Any, message: str, current_flow: Optional[str] = None, current_step: Optional[str] = None) -> Optional[str]:
    """Detect if user wants to switch to a different flow based on intent and message.
    
    Args:
        intent_result: The intent extraction result
        message: The user's message
        current_flow: The current flow name (if any)
        current_step: The current step in the flow (if any)
    
    Returns:
        Target flow name if switch detected, None otherwise
    """
    if not intent_result:
        return None
    
    # Don't switch flows on short responses if we're in an active flow
    # Short responses are likely answers to questions within the current flow
    if current_flow and is_short_response(message):
        return None
    
    intent_lower = intent_result.intent.lower() if hasattr(intent_result, 'intent') else ""
    text_lower = message.lower()
    
    # Detect which flow the user wants based on intent
    # Use more specific keywords to avoid false positives
    service_keywords = ["book service", "service booking", "book a service", "servicing", "repair", "maintenance"]
    is_service_intent = (
        ("service" in intent_lower and "booking" in intent_lower) or
        ("book" in intent_lower and "service" in text_lower) or
        any(keyword in text_lower for keyword in service_keywords)
    )
    
    emi_keywords = ["emi", "loan", "installment", "finance", "down payment", "monthly payment", "calculate emi"]
    is_emi_intent = (
        "emi" in intent_lower or
        ("loan" in intent_lower and "calculate" in text_lower) or
        ("finance" in intent_lower and "calculate" in text_lower) or
        any(keyword in text_lower for keyword in emi_keywords)
    )
    
    valuation_keywords = ["value", "valuation", "price", "worth", "resale", "sell", "how much", "estimate", "appraise"]
    is_valuation_intent = (
        ("value" in intent_lower or "valuation" in intent_lower) or
        ("price" in intent_lower and "car" in text_lower) or
        any(keyword in text_lower for keyword in valuation_keywords)
    )
    
    browse_keywords = ["browse", "buy", "purchase", "looking for", "want to buy", "want a", "want", "search", "find car", "used car", "used cars", "show me", "i want"]
    is_browse_intent = (
        "browse" in intent_lower or
        ("buy" in intent_lower and "car" in text_lower) or
        ("purchase" in intent_lower and "car" in text_lower) or
        any(keyword in text_lower for keyword in browse_keywords) or
        # Also check if user mentioned a car type (sedan, suv, etc.) with "want" or "looking for"
        (("want" in text_lower or "looking" in text_lower) and 
         any(car_type in text_lower for car_type in ["sedan", "suv", "hatchback", "coupe", "convertible", "car", "vehicle"])) or
        # Check if intent has car-related entities
        (intent_result.entities and any(key in intent_result.entities for key in ["car_type", "vehicle_type", "product"]))
    )
    
    # Determine target flow
    target_flow = None
    if is_service_intent:
        target_flow = "service_booking"
    elif is_emi_intent:
        target_flow = "emi"
    elif is_valuation_intent:
        target_flow = "car_valuation"
    elif is_browse_intent:
        target_flow = "browse_car"
    
    # Only return target flow if it's different from current flow
    # And require stronger signals when in an active flow
    if target_flow and target_flow != current_flow:
        # If we're in an active flow, require more explicit intent to switch
        if current_flow:
            # Check if the message is explicitly requesting the new flow
            explicit_keywords = {
                "service_booking": ["book service", "service booking", "book a service"],
                "emi": ["calculate emi", "emi calculation", "loan calculation"],
                "car_valuation": ["car valuation", "value my car", "appraise"],
                "browse_car": ["browse cars", "show me cars", "find cars"]
            }
            if target_flow in explicit_keywords:
                if not any(keyword in text_lower for keyword in explicit_keywords[target_flow]):
                    # Not explicit enough, don't switch
                    return None
        return target_flow
    
    return None

