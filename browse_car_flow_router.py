"""Dynamic Step Router for Browse Car Flow - Systematic Call Flow.

This module provides a systematic, dynamic routing system for the browse car flow.
Instead of nested if/elif statements, we use a step-based router that maps
step names to handler functions.
"""

from typing import Dict, Callable, Any, Optional, Awaitable
from conversation_state import ConversationState, conversation_manager
from intent_service import FlowRoutingError


class BrowseCarFlowError(Exception):
    """Base exception for browse car flow errors."""
    pass


class StepRouter:
    """Dynamic router for browse car flow steps.
    
    This router provides a systematic way to handle different steps in the flow.
    Steps are registered with handler functions, and the router automatically
    routes messages to the appropriate handler based on the current step.
    
    Example:
        router = StepRouter()
        router.register_step("collecting_criteria", handle_collecting_criteria)
        router.register_step("showing_cars", handle_showing_cars)
        
        # Later, route a message:
        response = await router.route(user_id, message, state, intent_result)
    """
    
    def __init__(self):
        # Map step names to handler functions
        self._handlers: Dict[str, Callable[[str, str, ConversationState, Any], Awaitable[str]]] = {}
        # Map step names to confirmation handlers
        self._confirmation_handlers: Dict[str, Callable[[str, str, ConversationState, Any], Awaitable[str]]] = {}
        # Map step names to initialization handlers (for first-time setup)
        self._init_handlers: Dict[str, Callable[[str, str, ConversationState, Any], Awaitable[str]]] = {}
    
    def register_step(
        self,
        step_name: str,
        handler: Callable[[str, str, ConversationState, Any], Awaitable[str]],
        confirmation_handler: Optional[Callable] = None,
        init_handler: Optional[Callable] = None
    ):
        """Register a step handler.
        
        Args:
            step_name: Name of the step (e.g., "collecting_criteria", "showing_cars")
            handler: Async function that handles the step
            confirmation_handler: Optional handler for confirmation responses
            init_handler: Optional handler for step initialization
        """
        self._handlers[step_name] = handler
        if confirmation_handler:
            self._confirmation_handlers[step_name] = confirmation_handler
        if init_handler:
            self._init_handlers[step_name] = init_handler
    
    async def route(
        self,
        user_id: str,
        message: str,
        state: ConversationState,
        intent_result: Any,
        **kwargs
    ) -> str:
        """Route to the appropriate step handler.
        
        This is the main routing function. It:
        1. Checks if we're in a confirmation state and routes to confirmation handler
        2. Checks if step needs initialization and calls init handler
        3. Routes to the step handler based on current step
        
        Args:
            user_id: User ID
            message: User's message
            state: Current conversation state
            intent_result: Intent extraction result
            **kwargs: Additional context (e.g., available_brands, available_types)
        
        Returns:
            Response string to send to user
        
        Raises:
            FlowRoutingError: If no handler is found for the current step
            BrowseCarFlowError: If handler execution fails
        """
        current_step = state.step
        
        # Step 1: Check if we're in a confirmation state
        if state.data.get("awaiting_confirmation", False):
            confirmation_handler = self._confirmation_handlers.get(current_step)
            if confirmation_handler:
                try:
                    return await confirmation_handler(user_id, message, state, intent_result, **kwargs)
                except Exception as e:
                    raise BrowseCarFlowError(
                        f"Error in confirmation handler for step '{current_step}': {str(e)}"
                    ) from e
            else:
                # No confirmation handler, clear the flag and proceed
                conversation_manager.update_data(user_id, awaiting_confirmation=False)
        
        # Step 2: Check if step needs initialization
        init_handler = self._init_handlers.get(current_step)
        if init_handler:
            try:
                result = await init_handler(user_id, message, state, intent_result, **kwargs)
                if result:
                    return result
            except Exception as e:
                print(f"Warning: Init handler for '{current_step}' failed: {e}")
                # Continue to normal handler
        
        # Step 3: Route to step handler
        handler = self._handlers.get(current_step)
        if handler:
            try:
                return await handler(user_id, message, state, intent_result, **kwargs)
            except Exception as e:
                raise BrowseCarFlowError(
                    f"Error in step handler '{current_step}': {str(e)}"
                ) from e
        
        # No handler found - this is a routing error
        raise FlowRoutingError(
            f"No handler registered for step '{current_step}' in browse_car flow. "
            f"Available steps: {list(self._handlers.keys())}"
        )
    
    def has_handler(self, step_name: str) -> bool:
        """Check if a handler exists for a step."""
        return step_name in self._handlers
    
    def get_registered_steps(self) -> list:
        """Get list of all registered step names."""
        return list(self._handlers.keys())


# Global router instance - will be initialized by browse_car_flow.py
_browse_car_router: Optional[StepRouter] = None


def get_router() -> StepRouter:
    """Get the global browse car flow router.
    
    Creates a new router if one doesn't exist.
    """
    global _browse_car_router
    if _browse_car_router is None:
        _browse_car_router = StepRouter()
    return _browse_car_router


def register_step(
    step_name: str,
    handler: Callable,
    confirmation_handler: Optional[Callable] = None,
    init_handler: Optional[Callable] = None
):
    """Register a step handler (convenience function)."""
    get_router().register_step(step_name, handler, confirmation_handler, init_handler)

