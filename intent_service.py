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


@dataclass
class IntentResult:
    intent: str
    summary: str
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
            summary=payload.get("summary", ""),
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
        "summarise it in a single sentence, estimate a confidence score between 0 and 1, "
        "and extract key entities as a JSON dictionary.\n\n"
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
            "IMPORTANT: If the user's message is a short response (like 'yes', 'no', 'change', "
            "or a single word/number), it's likely an answer to a question within the current flow. "
            "Do NOT interpret it as a request to switch to a different flow. "
            "Extract the intent based on the conversation context.\n\n"
        )
    
    prompt += (
        "Return your answer as compact JSON with exactly the keys: intent (string), "
        "summary (string), confidence (float between 0 and 1), entities (object mapping).\n\n"
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


def is_car_related(intent_result: IntentResult, original_message: str) -> bool:
    """Determine if the intent is car-related or out-of-context.
    
    Args:
        intent_result: The extracted intent result.
        original_message: The original user message.
    
    Returns:
        True if car-related, False if out-of-context.
    """
    # Car-related keywords
    car_keywords = [
        "car", "vehicle", "automobile", "auto", "truck", "suv", "sedan",
        "engine", "transmission", "brake", "tire", "wheel", "battery",
        "oil", "maintenance", "repair", "service", "mechanic", "garage",
        "mileage", "fuel", "gas", "petrol", "diesel", "electric", "hybrid",
        "insurance", "registration", "license", "driving", "road", "highway",
        "accident", "collision", "claim", "quote", "price", "cost", "buy",
        "sell", "trade", "lease", "finance", "loan", "warranty", "recall"
    ]
    
    # Check intent name
    intent_lower = intent_result.intent.lower()
    if any(keyword in intent_lower for keyword in car_keywords):
        return True
    
    # Check summary
    summary_lower = intent_result.summary.lower()
    if any(keyword in summary_lower for keyword in car_keywords):
        return True
    
    # Check original message
    message_lower = original_message.lower()
    if any(keyword in message_lower for keyword in car_keywords):
        return True
    
    # Check entities
    entities_str = str(intent_result.entities).lower()
    if any(keyword in entities_str for keyword in car_keywords):
        return True
    
    return False


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
            "Keep responses concise (2-3 sentences max)."
        )
    else:
        system_prompt = (
            "You are a helpful and friendly car service assistant. "
            "The user has asked a question that is NOT related to cars. "
            "Politely redirect them back to car-related topics in a warm, "
            "understanding manner. Acknowledge their question but gently guide "
            "them to how you can help with car-related queries. "
            "Be empathetic and friendly, not robotic. Keep it brief (2-3 sentences max)."
        )
    
    prompt = (
        f"{system_prompt}\n\n"
        f"User's message: {original_message}\n"
        f"Detected intent: {intent_result.intent}\n"
        f"Intent summary: {intent_result.summary}\n"
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
