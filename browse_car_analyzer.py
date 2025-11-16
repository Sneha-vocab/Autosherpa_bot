"""Intelligent message analysis for browse car flow using Gemini LLM."""

import os
import json
import httpx
from typing import Optional, Dict, Any
from intent_service import ResponseGenerationError, DEFAULT_GEMINI_MODEL

_API_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)


class BrowseCarAnalysisError(RuntimeError):
    """Raised when browse car analysis fails."""


async def analyze_browse_car_message(
    message: str,
    conversation_context: Dict[str, Any],
    available_brands: list,
    available_types: list,
    *,
    model: Optional[str] = None,
    timeout: float = 12.0,
    client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """Analyze user message in the context of browse car flow.
    
    Returns:
        {
            "extracted_brand": str or None,
            "extracted_budget": tuple(min, max) or None,
            "extracted_type": str or None,
            "user_intent": str,  # e.g., "providing_brand", "asking_question", "changing_criteria"
            "needs_clarification": bool,
            "clarification_question": str or None,
        }
    """
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise BrowseCarAnalysisError("GOOGLE_API_KEY is not configured")
    
    resolved_model = model or os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    url = _API_URL_TEMPLATE.format(model=resolved_model)
    
    # Build context
    current_step = conversation_context.get("step", "collecting_criteria")
    collected_brand = conversation_context.get("data", {}).get("brand")
    collected_budget = conversation_context.get("data", {}).get("budget")
    collected_type = conversation_context.get("data", {}).get("car_type")
    
    context_info = f"""
Current conversation state:
- Step: {current_step}
- Already collected: Brand={collected_brand}, Budget={collected_budget}, Type={collected_type}
- Available brands in database: {', '.join(available_brands)}
- Available car types in database: {', '.join(available_types)}
"""
    
    prompt = f"""You are an intelligent car sales assistant helping a customer browse used cars. Analyze the user's message and extract relevant information.

{context_info}

User's message: "{message}"

Analyze this message and extract:
1. Brand name (if mentioned) - must match one of the available brands exactly (case-insensitive)
2. Budget range (if mentioned) - extract as (min_price, max_price) in rupees. Look for patterns like "5-10 lakh", "under 8 lakh", "10 lakh", "5 to 10 lakh"
3. Car type (if mentioned) - must match one of the available types exactly (case-insensitive)
4. User's intent - what is the user trying to do? (e.g., "providing_brand", "providing_budget", "providing_type", "asking_question", "changing_criteria", "selecting_car", "booking_test_drive")
5. Whether clarification is needed
6. If clarification needed, what question to ask

Return your analysis as JSON with these exact keys:
{{
    "extracted_brand": "brand_name_or_null",
    "extracted_budget_min": number_or_null,
    "extracted_budget_max": number_or_null,
    "extracted_type": "type_name_or_null",
    "user_intent": "intent_string",
    "needs_clarification": true_or_false,
    "clarification_question": "question_or_null",
    "confidence": 0.0_to_1.0
}}

Important:
- Brand must exactly match one from: {available_brands}
- Type must exactly match one from: {available_types}
- Budget should be converted to rupees (1 lakh = 100000)
- If user says "change" or "different", intent is "changing_criteria"
- If user provides a number (1, 2, 3), intent is "selecting_car"
- Be smart about understanding user's intent even if they don't use exact words
"""
    
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}]
            }
        ],
        "generationConfig": {
            "temperature": 0.3,
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
        raise BrowseCarAnalysisError("Failed to reach Gemini API") from exc
    
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise BrowseCarAnalysisError(
            f"Gemini API request failed with status {exc.response.status_code}"
        ) from exc
    
    payload = response.json()
    try:
        candidate_text = (
            payload["candidates"][0]["content"]["parts"][0]["text"]
        ).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise BrowseCarAnalysisError(
            "Gemini API returned an unexpected response structure"
        ) from exc
    
    try:
        parsed = json.loads(candidate_text)
        
        # Convert budget to tuple format
        budget = None
        if parsed.get("extracted_budget_min") is not None or parsed.get("extracted_budget_max") is not None:
            budget = (
                parsed.get("extracted_budget_min"),
                parsed.get("extracted_budget_max")
            )
        
        return {
            "extracted_brand": parsed.get("extracted_brand"),
            "extracted_budget": budget,
            "extracted_type": parsed.get("extracted_type"),
            "user_intent": parsed.get("user_intent", "unknown"),
            "needs_clarification": parsed.get("needs_clarification", False),
            "clarification_question": parsed.get("clarification_question"),
            "confidence": parsed.get("confidence", 0.0),
        }
    except json.JSONDecodeError as exc:
        raise BrowseCarAnalysisError("Failed to parse Gemini response as JSON") from exc


async def generate_browse_car_response(
    message: str,
    conversation_context: Dict[str, Any],
    analysis_result: Dict[str, Any],
    available_brands: list,
    available_types: list,
    *,
    model: Optional[str] = None,
    timeout: float = 12.0,
    client: Optional[httpx.AsyncClient] = None,
) -> str:
    """Generate a human-like, contextual response for the browse car flow."""
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ResponseGenerationError("GOOGLE_API_KEY is not configured")
    
    resolved_model = model or os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    url = _API_URL_TEMPLATE.format(model=resolved_model)
    
    current_step = conversation_context.get("step", "collecting_criteria")
    collected_brand = conversation_context.get("data", {}).get("brand")
    collected_budget = conversation_context.get("data", {}).get("budget")
    collected_type = conversation_context.get("data", {}).get("car_type")
    
    # Build context-aware prompt
    if current_step == "collecting_criteria":
        system_prompt = f"""You are a friendly and professional car sales assistant helping a customer find their perfect used car. 

Current situation:
- You're collecting information: Brand, Budget, and Car Type
- Already collected: Brand={collected_brand or 'Not yet'}, Budget={collected_budget or 'Not yet'}, Type={collected_type or 'Not yet'}
- Available brands: {', '.join(available_brands)}
- Available types: {', '.join(available_types)}

User's message: "{message}"
Analysis: {analysis_result['user_intent']}

Your task:
1. Acknowledge what the user said in a warm, human way
2. If they provided information (brand/budget/type), confirm it enthusiastically
3. Ask for the NEXT missing piece of information naturally
4. Be conversational, friendly, and helpful - like a real car salesperson
5. Keep it brief (2-3 sentences max)
6. Use emojis sparingly but naturally

Generate a natural, human-like response:"""
    
    elif current_step == "showing_cars":
        system_prompt = f"""You are a friendly car sales assistant showing car options to a customer.

User's message: "{message}"
Analysis: {analysis_result['user_intent']}

Your task:
- If they selected a car number, acknowledge enthusiastically
- If they want to change criteria, be helpful and supportive
- If they're confused, clarify gently
- Be warm, professional, and human-like
- Keep it brief (2-3 sentences max)

Generate a natural response:"""
    
    elif current_step == "car_selected":
        system_prompt = f"""You are a friendly car sales assistant helping with next steps.

User's message: "{message}"
Analysis: {analysis_result['user_intent']}

Your task:
- If they want to book test drive, be enthusiastic and guide them
- If they want to change, be supportive
- Be warm and professional
- Keep it brief (2-3 sentences max)

Generate a natural response:"""
    
    else:
        system_prompt = f"""You are a friendly car sales assistant. User said: "{message}". Respond naturally and helpfully."""
    
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": system_prompt}]
            }
        ],
        "generationConfig": {
            "temperature": 0.7,
            "topP": 0.95,
            "topK": 40,
            "maxOutputTokens": 200,
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

