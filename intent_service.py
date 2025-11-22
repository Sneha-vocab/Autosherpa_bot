"""Utility for extracting user intent using Google's Gemini LLM."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx

DEFAULT_GEMINI_MODEL = "gemini-2.0-flash"
_API_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)


class IntentExtractionError(RuntimeError):
    """Raised when the Gemini API call fails or returns an unexpected response."""


class ResponseGenerationError(RuntimeError):
    """Raised when response generation fails."""


class FlowRoutingError(RuntimeError):
    """Raised when flow routing fails."""


@dataclass
class IntentResult:
    intent: str
    confidence: float
    entities: Dict[str, Any]

    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> "IntentResult":
        raw_confidence = payload.get("confidence", 0.0)
        try:
            numeric_confidence = float(raw_confidence)
        except (TypeError, ValueError):
            numeric_confidence = 0.0

        clamped_confidence = max(0.0, min(1.0, numeric_confidence))

        return cls(
            intent=payload.get("intent", "unknown"),
            confidence=clamped_confidence,
            entities=payload.get("entities", {}) or {},
        )


async def extract_intent(
    message_text: str,
    *,
    conversation_context: Optional[str] = None,
    current_flow: Optional[str] = None,
    current_step: Optional[str] = None,
    model: Optional[str] = None,
    timeout: float = 12.0,
    client: Optional[httpx.AsyncClient] = None,
) -> IntentResult:
    """Extract intent for the provided message text using Gemini.

    Args:
        message_text: The raw user message.
        model: Optional override for the Gemini model name.
        timeout: Request timeout in seconds.
        client: Optional shared ``httpx.AsyncClient``.

    Returns:
        IntentResult describing the detected intent.

    Raises:
        ValueError: If ``message_text`` is empty.
        IntentExtractionError: If the Gemini API call fails.
    """

    if not message_text or not message_text.strip():
        raise ValueError("Message text must be a non-empty string")

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise IntentExtractionError("GOOGLE_API_KEY is not configured")

    resolved_model = model or os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    url = _API_URL_TEMPLATE.format(model=resolved_model)

    # Build prompt with context if available
    prompt_text = _build_prompt(
        message_text.strip(),
        conversation_context=conversation_context,
        current_flow=current_flow,
        current_step=current_step
    )

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": prompt_text,
                    }
                ],
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "topP": 0.9,
            "topK": 32,
            "responseMimeType": "application/json",
        },
    }

    request_context = {
        "method": "POST",
        "url": url,
        "params": {"key": api_key},
        "headers": {"Content-Type": "application/json"},
        "json": payload,
        "timeout": timeout,
    }

    try:
        if client:
            response = await client.request(**request_context)
        else:
            async with httpx.AsyncClient() as local_client:
                response = await local_client.request(**request_context)
    except httpx.RequestError as exc:
        raise IntentExtractionError("Failed to reach Gemini API") from exc

    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise IntentExtractionError(
            f"Gemini API request failed with status {exc.response.status_code}"
        ) from exc

    payload = response.json()
    try:
        candidate_text = (
            payload["candidates"][0]["content"]["parts"][0]["text"]
        )
    except (KeyError, IndexError, TypeError) as exc:
        raise IntentExtractionError(
            "Gemini API returned an unexpected response structure"
        ) from exc

    try:
        parsed = json.loads(candidate_text)
    except json.JSONDecodeError as exc:
        raise IntentExtractionError("Failed to parse Gemini response as JSON") from exc

    return IntentResult.from_payload(parsed)


def _build_prompt(
    message: str,
    conversation_context: Optional[str] = None,
    current_flow: Optional[str] = None,
    current_step: Optional[str] = None
) -> str:
    prompt = (
        "You are a precise intent extraction service. "
        "Given the following user message, identify the user's intent, "
        "estimate a confidence score between 0 and 1, "
        "and extract key entities as a JSON dictionary.\n\n"
        "IMPORTANT - Confidence Guidelines:\n"
        "- If you are CERTAIN about the intent (clear request like 'browse cars', 'calculate EMI'), set confidence >= 0.8\n"
        "- If you are SOMEWHAT CERTAIN but not 100% sure, set confidence 0.6-0.79\n"
        "- If you are UNCERTAIN or CONFUSED (unclear message, ambiguous request), set confidence < 0.6\n"
        "- If the message is completely unclear or doesn't match any known intent, set intent='unknown' and confidence < 0.5\n\n"
    )
    
    # Add conversation context if available
    if conversation_context:
        prompt += f"Recent conversation context:\n{conversation_context}\n\n"
    
    # Add current flow/step context
    if current_flow:
        prompt += f"Current flow: {current_flow}"
        if current_step:
            prompt += f", Step: {current_step}"
        prompt += "\n\n"
        prompt += (
            "CRITICAL: The user is currently in an active flow. "
            "Their message should be interpreted within the context of this flow. "
            "If the user's message is a short response (like 'yes', 'no', 'change', 'ok', "
            "or a single word/number), it is DEFINITELY an answer to a question within the current flow. "
            "Do NOT interpret it as a request to switch to a different flow. "
            "Only interpret it as a flow switch if the user EXPLICITLY requests a different flow "
            "(e.g., 'I want to browse cars' while in service booking flow). "
            "Extract the intent based on the conversation context and current flow.\n\n"
        )
    
    prompt += (
        "Return your answer as compact JSON with exactly the keys: intent (string), "
        "confidence (float between 0 and 1), entities (object mapping).\n\n"
        f"User message: {message}"
    )
    
    return prompt


def extract_intent_sync(message_text: str, **kwargs: Any) -> IntentResult:
    """Convenience wrapper for synchronous contexts."""

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(extract_intent(message_text, **kwargs))
    else:
        if loop.is_running():
            raise IntentExtractionError(
                "Cannot call extract_intent_sync from a running event loop"
            )
        return loop.run_until_complete(extract_intent(message_text, **kwargs))


async def is_car_related_llm(
    message: str,
    intent_result: IntentResult,
    *,
    model: Optional[str] = None,
    timeout: float = 8.0,
    client: Optional[httpx.AsyncClient] = None,
) -> bool:
    """Determine if the intent is car-related using LLM for better context understanding.
    
    Args:
        message: The original user message.
        intent_result: The extracted intent result.
        model: Optional override for the Gemini model name.
        timeout: Request timeout in seconds.
        client: Optional shared httpx.AsyncClient.
    
    Returns:
        True if car-related, False if out-of-context.
    
    Raises:
        FlowRoutingError: If the API call fails.
    """
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        # Fallback to keyword-based if API key not available
        return _is_car_related_keywords(intent_result, message)
    
    resolved_model = model or os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    url = _API_URL_TEMPLATE.format(model=resolved_model)
    
    prompt = f"""You are a context analyzer for a car dealership chatbot. Determine if the user's message is related to cars, vehicles, or car dealership services.

CAR-RELATED topics include:
- Buying, selling, or browsing cars/vehicles
- Car valuation or pricing
- Car loans, EMI, financing
- Car service, maintenance, repairs
- Car insurance, registration
- Car parts, accessories for vehicles
- Test drives, car bookings
- Car-related questions and queries

NOT car-related (out-of-context):
- Phone cases, phone accessories
- General shopping (clothes, electronics, etc.)
- Non-vehicle related questions
- Random topics unrelated to cars

User message: "{message}"
Intent: {intent_result.intent}
Entities: {intent_result.entities}

Analyze if this is car-related. Return ONLY a JSON object with this structure:
{{"is_car_related": true or false, "reasoning": "brief explanation"}}
"""
    
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}]
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "topP": 0.8,
            "topK": 20,
            "responseMimeType": "application/json",
        },
    }
    
    request_context = {
        "method": "POST",
        "url": url,
        "params": {"key": api_key},
        "headers": {"Content-Type": "application/json"},
        "json": payload,
        "timeout": timeout,
    }
    
    try:
        if client:
            response = await client.request(**request_context)
        else:
            async with httpx.AsyncClient() as local_client:
                response = await local_client.request(**request_context)
        
        response.raise_for_status()
        payload = response.json()
        candidate_text = payload["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(candidate_text)
        return parsed.get("is_car_related", False)
        
    except Exception as exc:
        print(f"LLM car-related check failed: {exc}, falling back to keyword-based")
        return _is_car_related_keywords(intent_result, message)


def _is_car_related_keywords(intent_result: IntentResult, original_message: str) -> bool:
    """Fallback keyword-based car-related check."""
    # Car-related keywords (excluding ambiguous words that might match non-car items)
    car_keywords = [
        "vehicle", "automobile", "auto", "truck", "suv", "sedan", "hatchback",
        "engine", "transmission", "brake", "tire", "wheel", "battery",
        "oil", "maintenance", "repair", "service", "mechanic", "garage",
        "mileage", "fuel", "gas", "petrol", "diesel", "electric", "hybrid",
        "insurance", "registration", "license", "driving", "road", "highway",
        "accident", "collision", "claim", "quote", "price", "cost",
        "sell", "trade", "lease", "finance", "loan", "warranty", "recall",
        "test drive", "valuation", "emi", "appraise"
    ]
    
    # More specific car context keywords
    message_lower = original_message.lower()
    
    # Check for explicit car context phrases
    car_phrases = [
        "car", "buy car", "sell car", "car service", "car repair",
        "car loan", "car insurance", "car valuation", "car price"
    ]
    
    # If message contains standalone "car" or car phrases, it's car-related
    if any(phrase in message_lower for phrase in car_phrases):
        return True
    
    # Check intent for car keywords (but be more careful)
    intent_lower = intent_result.intent.lower()
    
    # Only match if it's clearly car-related, not just containing the word
    if any(keyword in intent_lower for keyword in car_keywords):
        return True
    
    return False


def is_car_related(intent_result: IntentResult, original_message: str) -> bool:
    """Synchronous wrapper for car-related check (uses keyword-based for compatibility).
    
    For async contexts, use is_car_related_llm() instead.
    """
    return _is_car_related_keywords(intent_result, original_message)


async def generate_response(
    original_message: str,
    intent_result: IntentResult,
    is_car_related: bool,
    *,
    model: Optional[str] = None,
    timeout: float = 12.0,
    client: Optional[httpx.AsyncClient] = None,
) -> str:
    """Generate a human-like response based on intent and context.
    
    Args:
        original_message: The original user message.
        intent_result: The extracted intent result.
        is_car_related: Whether the query is car-related.
        model: Optional override for the Gemini model name.
        timeout: Request timeout in seconds.
        client: Optional shared httpx.AsyncClient.
    
    Returns:
        A human-like response string.
    
    Raises:
        ResponseGenerationError: If response generation fails.
    """
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ResponseGenerationError("GOOGLE_API_KEY is not configured")
    
    resolved_model = model or os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    url = _API_URL_TEMPLATE.format(model=resolved_model)
    
    # Build context-aware prompt
    if is_car_related:
        system_prompt = (
            "You are a helpful and friendly car service assistant. "
            "The user has asked a car-related question. Provide a warm, "
            "professional, and helpful response. Be conversational and human-like. "
            "If you need more information, ask follow-up questions naturally. "
            "Keep responses concise (10-15 words max)."
        )
    else:
        system_prompt = (
            "You are a helpful and friendly car service assistant. "
            "The user has asked a question that is NOT related to cars or vehicles. "
            "CRITICAL: You MUST acknowledge that their question is out of your scope and "
            "politely redirect them back to car-related topics. "
            "Do NOT try to answer their non-car question. Do NOT ask follow-up questions about their non-car topic. "
            "Instead, acknowledge their question briefly and redirect them to how you can help with car-related queries. "
            "Be warm, empathetic, and friendly, but clear that you specialize in car-related assistance. "
            "Keep it brief (15-20 words max). "
            "Example: 'I understand, but I specialize in car-related help. How can I assist you with cars today?'"
        )
    
    prompt = (
        f"{system_prompt}\n\n"
        f"User's message: {original_message}\n"
        f"Detected intent: {intent_result.intent}\n"
        f"Confidence: {intent_result.confidence:.2f}\n"
    )
    
    if intent_result.entities:
        prompt += f"Extracted entities: {intent_result.entities}\n"
    
    prompt += "\nGenerate a natural, human-like response:"
    
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}]
            }
        ],
        "generationConfig": {
            "temperature": 0.7,  # More creative for natural responses
            "topP": 0.95,
            "topK": 40,
            "maxOutputTokens": 200,  # Keep responses concise
        },
    }
    
    request_context = {
        "method": "POST",
        "url": url,
        "params": {"key": api_key},
        "headers": {"Content-Type": "application/json"},
        "json": payload,
        "timeout": timeout,
    }
    
    try:
        if client:
            response = await client.request(**request_context)
        else:
            async with httpx.AsyncClient() as local_client:
                response = await local_client.request(**request_context)
    except httpx.RequestError as exc:
        raise ResponseGenerationError("Failed to reach Gemini API") from exc
    
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise ResponseGenerationError(
            f"Gemini API request failed with status {exc.response.status_code}"
        ) from exc
    
    payload = response.json()
    try:
        generated_text = (
            payload["candidates"][0]["content"]["parts"][0]["text"]
        ).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise ResponseGenerationError(
            "Gemini API returned an unexpected response structure"
        ) from exc
    
    return generated_text


@dataclass
class FlowRoutingResult:
    """Result of flow routing decision."""
    target_flow: Optional[str]  # "browse_car", "car_valuation", "emi", "service_booking", or None
    confidence: float  # Confidence score between 0 and 1
    reasoning: str  # Explanation of the routing decision
    should_switch: bool  # Whether to switch flows (True) or continue current flow (False)
    
    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> "FlowRoutingResult":
        raw_confidence = payload.get("confidence", 0.0)
        try:
            numeric_confidence = float(raw_confidence)
        except (TypeError, ValueError):
            numeric_confidence = 0.0
        
        clamped_confidence = max(0.0, min(1.0, numeric_confidence))
        
        target_flow = payload.get("target_flow")
        # Validate target flow
        valid_flows = ["browse_car", "car_valuation", "emi", "service_booking", None]
        if target_flow not in valid_flows:
            target_flow = None
        
        return cls(
            target_flow=target_flow,
            confidence=clamped_confidence,
            reasoning=payload.get("reasoning", ""),
            should_switch=payload.get("should_switch", False)
        )


def _build_flow_routing_prompt(
    message: str,
    conversation_context: Optional[str] = None,
    current_flow: Optional[str] = None,
    current_step: Optional[str] = None,
    intent_result: Optional[IntentResult] = None
) -> str:
    """Build a detailed system prompt for flow routing."""
    
    system_prompt = """You are an intelligent flow router for a car dealership chatbot. Your job is to determine which conversational flow the user should be routed to based on their message.

AVAILABLE FLOWS:

1. **browse_car** - For users who want to:
   - Browse, search, or look for cars to buy
   - Find cars by brand, type (sedan, SUV, hatchback), or budget
   - View car listings and details
   - Book test drives
   Examples: "I want a sedan", "show me cars", "looking for a car under 20 lakhs", "browse cars", "find me a car", "I want to buy a car"

2. **car_valuation** - For users who want to:
   - Get the value/price of their existing car
   - Know how much their car is worth
   - Get a car appraisal or estimate
   - Sell their car and need valuation
   Examples: "value my car", "how much is my car worth", "car valuation", "what's the price of my car", "appraise my car"

3. **emi** - For users who want to:
   - Calculate EMI (Equated Monthly Installment) for car loans
   - Get loan options and financing details
   - Know monthly payment amounts
   - Calculate down payment and tenure options
   Examples: "calculate EMI", "loan options", "monthly payment", "I need a loan", "finance options", "EMI calculator"

4. **service_booking** - For users who want to:
   - Book car service or maintenance
   - Schedule repairs or servicing
   - Get their car serviced
   - Book maintenance appointments
   Examples: "book service", "service booking", "I need servicing", "car repair", "maintenance booking", "service my car"

ROUTING RULES:

1. **If user is in an active flow (current_flow is set):**
   - If the message is a SHORT RESPONSE (yes, no, ok, a number, single word), it's likely an answer within the current flow. Set should_switch to FALSE.
   - If the message EXPLICITLY requests a different flow (e.g., "I want to browse cars" while in service_booking), set should_switch to TRUE.
   - If the message is ambiguous or could be part of current flow, prefer staying in current flow (should_switch = FALSE).
   - Only switch flows if the user's intent is CLEAR and EXPLICIT about wanting a different flow.

2. **If user is NOT in any flow (current_flow is None):**
   - Analyze the message to determine the most appropriate flow.
   - Consider the user's primary intent, not secondary mentions.
   - If the message mentions multiple things, prioritize the PRIMARY action the user wants to take.

3. **Confidence scoring:**
   - High confidence (0.8-1.0): Clear, explicit intent matching one flow
   - Medium confidence (0.5-0.79): Somewhat clear but may need clarification
   - Low confidence (0.0-0.49): Ambiguous or unclear intent

4. **Special cases:**
   - Greetings or general questions: target_flow = None, should_switch = False
   - Out-of-context questions (not car-related): target_flow = None, should_switch = False
   - If user is asking about a flow they're already in: should_switch = False

OUTPUT FORMAT:
Return a JSON object with exactly these keys:
- target_flow: string or null (one of: "browse_car", "car_valuation", "emi", "service_booking", or null)
- confidence: float between 0 and 1
- reasoning: string explaining your decision
- should_switch: boolean (true if should switch flows, false if should continue current flow)

"""
    
    # Add context information
    if conversation_context:
        system_prompt += f"\nRECENT CONVERSATION CONTEXT:\n{conversation_context}\n\n"
    
    if current_flow:
        system_prompt += f"CURRENT FLOW: {current_flow}"
        if current_step:
            system_prompt += f", Current Step: {current_step}"
        system_prompt += "\n\n"
        system_prompt += (
            "IMPORTANT: The user is currently in an active flow. "
            "Only switch flows if they EXPLICITLY request a different flow. "
            "Short responses (yes, no, numbers, single words) should stay in current flow.\n\n"
        )
    
    # Add intent information if available
    if intent_result:
        system_prompt += f"EXTRACTED INTENT:\n"
        system_prompt += f"  Intent: {intent_result.intent}\n"
        system_prompt += f"  Confidence: {intent_result.confidence:.2f}\n"
        if intent_result.entities:
            system_prompt += f"  Entities: {intent_result.entities}\n"
        system_prompt += "\n"
    
    system_prompt += f"USER MESSAGE: {message}\n\n"
    system_prompt += "Analyze the message and determine the appropriate flow routing. Return your response as JSON."
    
    return system_prompt


async def route_to_flow(
    message: str,
    *,
    conversation_context: Optional[str] = None,
    current_flow: Optional[str] = None,
    current_step: Optional[str] = None,
    intent_result: Optional[IntentResult] = None,
    model: Optional[str] = None,
    timeout: float = 12.0,
    client: Optional[httpx.AsyncClient] = None,
) -> FlowRoutingResult:
    """Route user message to appropriate flow using LLM.
    
    Args:
        message: The user's message text.
        conversation_context: Recent conversation history for context.
        current_flow: Current active flow name (if any).
        current_step: Current step in the flow (if any).
        intent_result: Optional intent extraction result for additional context.
        model: Optional override for the Gemini model name.
        timeout: Request timeout in seconds.
        client: Optional shared httpx.AsyncClient.
    
    Returns:
        FlowRoutingResult with routing decision.
    
    Raises:
        ValueError: If message is empty.
        FlowRoutingError: If the routing API call fails.
    """
    if not message or not message.strip():
        raise ValueError("Message text must be a non-empty string")
    
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise FlowRoutingError("GOOGLE_API_KEY is not configured")
    
    resolved_model = model or os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    url = _API_URL_TEMPLATE.format(model=resolved_model)
    
    # Build routing prompt
    prompt_text = _build_flow_routing_prompt(
        message.strip(),
        conversation_context=conversation_context,
        current_flow=current_flow,
        current_step=current_step,
        intent_result=intent_result
    )
    
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": prompt_text,
                    }
                ],
            }
        ],
        "generationConfig": {
            "temperature": 0.1,  # Low temperature for consistent routing
            "topP": 0.8,
            "topK": 20,
            "responseMimeType": "application/json",
        },
    }
    
    request_context = {
        "method": "POST",
        "url": url,
        "params": {"key": api_key},
        "headers": {"Content-Type": "application/json"},
        "json": payload,
        "timeout": timeout,
    }
    
    try:
        if client:
            response = await client.request(**request_context)
        else:
            async with httpx.AsyncClient() as local_client:
                response = await local_client.request(**request_context)
    except httpx.RequestError as exc:
        raise FlowRoutingError("Failed to reach Gemini API for flow routing") from exc
    
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise FlowRoutingError(
            f"Gemini API request failed with status {exc.response.status_code}"
        ) from exc
    
    payload = response.json()
    try:
        candidate_text = (
            payload["candidates"][0]["content"]["parts"][0]["text"]
        )
    except (KeyError, IndexError, TypeError) as exc:
        raise FlowRoutingError(
            "Gemini API returned an unexpected response structure"
        ) from exc
    
    try:
        parsed = json.loads(candidate_text)
    except json.JSONDecodeError as exc:
        raise FlowRoutingError("Failed to parse Gemini routing response as JSON") from exc
    
    return FlowRoutingResult.from_payload(parsed)
