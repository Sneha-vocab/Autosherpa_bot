"""Conversation state management for multi-turn dialogues."""

from typing import Dict, Optional, Any
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
    
    def to_dict(self) -> dict:
        """Convert state to dictionary for storage."""
        return {
            "user_id": self.user_id,
            "flow_name": self.flow_name,
            "step": self.step,
            "data": self.data,
            "last_updated": self.last_updated.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "ConversationState":
        """Create state from dictionary."""
        state = cls(
            user_id=data["user_id"],
            flow_name=data.get("flow_name"),
            step=data.get("step"),
            data=data.get("data", {}),
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
    
    def ensure_flow(self, user_id: str, flow_name: str, step: str = "start") -> ConversationState:
        """
        Ensure the user has a state for the given flow.
        If state exists, only update flow_name and step, keep existing data.
        """
        state = self.get_state(user_id)
        if not state:
            state = ConversationState(user_id=user_id, flow_name=flow_name, step=step)
        else:
            state.flow_name = flow_name
            state.step = step
        self.set_state(user_id, state)
        return state


# Global conversation manager instance
conversation_manager = ConversationManager()

