"""Intelligent message analysis for service booking flow using Gemini LLM."""

import os
import json
import httpx
from typing import Optional, Dict, Any
from intent_service import ResponseGenerationError, DEFAULT_GEMINI_MODEL

_API_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)


class ServiceBookingAnalysisError(RuntimeError):
    """Raised when service booking analysis fails."""


# Available services
AVAILABLE_SERVICES = [
    "New Car Sales",
    "Certified Pre-Owned Cars",
    "Vehicle Servicing & Repairs",
    "Bodyshop & Insurance Claims",
    "Finance & Loan Assistance",
    "Car Insurance & Renewals",
    "RC Transfer & Documentation"
]

# Service types for vehicle servicing
SERVICE_TYPES = [
    "Regular Service",
    "Major Service",
    "Accident Repair",
    "Insurance Claim",
    "Other"
]


async def analyze_service_booking_message(
    message: str,
    conversation_context: Dict[str, Any],
    available_brands: list,
    *,
    model: Optional[str] = None,
    timeout: float = 12.0,
    client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """Analyze user message in the context of service booking flow.
    
    Returns:
        {
            "extracted_service": str or None,
            "extracted_make": str or None,
            "extracted_model": str or None,
            "extracted_year": int or None,
            "extracted_registration": str or None,
            "extracted_service_type": str or None,
            "user_intent": str,
            "needs_clarification": bool,
            "clarification_question": str or None,
        }
    """
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ServiceBookingAnalysisError("GOOGLE_API_KEY is not configured")
    
    resolved_model = model or os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    url = _API_URL_TEMPLATE.format(model=resolved_model)
    
    # Build context
    current_step = conversation_context.get("step", "showing_services")
    selected_service = conversation_context.get("data", {}).get("service")
    make = conversation_context.get("data", {}).get("make")
    car_model = conversation_context.get("data", {}).get("model")
    year = conversation_context.get("data", {}).get("year")
    registration = conversation_context.get("data", {}).get("registration_number")
    service_type = conversation_context.get("data", {}).get("service_type")
    
    context_info = f"""
Current conversation state:
- Step: {current_step}
- Selected service: {selected_service}
- Already collected: Make={make}, Model={car_model}, Year={year}, Registration={registration}, Service Type={service_type}
- Available services: {', '.join(AVAILABLE_SERVICES)}
- Available service types: {', '.join(SERVICE_TYPES)}
- Available brands: {', '.join(available_brands)}
"""
    
    prompt = f"""You are an intelligent service booking assistant helping a customer book a car service. Analyze the user's message and extract relevant information.

{context_info}

User's message: "{message}"

Analyze this message and extract:
1. Service selection (if mentioned as a number like 1, 2, 3, or service name)
2. Car make/brand (if mentioned) - must match one of the available brands
3. Car model (if mentioned)
4. Year of manufacturing (if mentioned) - extract as 4-digit year
5. Registration number (if mentioned) - format like KA01AB1234, MH12CD5678
6. Service type (if mentioned) - must match one of: {', '.join(SERVICE_TYPES)}
7. User's intent - what is the user trying to do? (e.g., "selecting_service", "providing_vehicle_details", "providing_service_type", "asking_question", "changing_criteria")
8. Whether clarification is needed
9. If clarification needed, what question to ask

Return your analysis as JSON with these exact keys:
{{
    "extracted_service": "service_name_or_null",
    "extracted_make": "brand_name_or_null",
    "extracted_model": "model_name_or_null",
    "extracted_year": number_or_null,
    "extracted_registration": "registration_number_or_null",
    "extracted_service_type": "service_type_or_null",
    "user_intent": "intent_string",
    "needs_clarification": true_or_false,
    "clarification_question": "question_or_null",
    "confidence": 0.0_to_1.0
}}

Important:
- Service must match one from: {AVAILABLE_SERVICES}
- Make must match one from: {available_brands}
- Service type must match one from: {SERVICE_TYPES}
- Year should be between 1990 and current year
- Registration number format: XX##XX#### (2 letters, 2 digits, 2 letters, 4 digits)
- If user says "change" or "different", intent is "changing_criteria"
- If user provides a number (1, 2, 3), it could be service selection - use context to determine
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
        raise ServiceBookingAnalysisError("Failed to reach Gemini API") from exc
    
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise ServiceBookingAnalysisError(
            f"Gemini API request failed with status {exc.response.status_code}"
        ) from exc
    
    payload = response.json()
    try:
        candidate_text = (
            payload["candidates"][0]["content"]["parts"][0]["text"]
        ).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise ServiceBookingAnalysisError(
            "Gemini API returned an unexpected response structure"
        ) from exc
    
    try:
        parsed = json.loads(candidate_text)
        
        return {
            "extracted_service": parsed.get("extracted_service"),
            "extracted_make": parsed.get("extracted_make"),
            "extracted_model": parsed.get("extracted_model"),
            "extracted_year": parsed.get("extracted_year"),
            "extracted_registration": parsed.get("extracted_registration"),
            "extracted_service_type": parsed.get("extracted_service_type"),
            "user_intent": parsed.get("user_intent", "unknown"),
            "needs_clarification": parsed.get("needs_clarification", False),
            "clarification_question": parsed.get("clarification_question"),
            "confidence": parsed.get("confidence", 0.0),
        }
    except json.JSONDecodeError as exc:
        raise ServiceBookingAnalysisError("Failed to parse Gemini response as JSON") from exc


async def generate_service_booking_response(
    message: str,
    conversation_context: Dict[str, Any],
    analysis_result: Dict[str, Any],
    available_brands: list,
    *,
    model: Optional[str] = None,
    timeout: float = 12.0,
    client: Optional[httpx.AsyncClient] = None,
) -> str:
    """Generate a human-like, contextual response for the service booking flow."""
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ResponseGenerationError("GOOGLE_API_KEY is not configured")
    
    resolved_model = model or os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    url = _API_URL_TEMPLATE.format(model=resolved_model)
    
    current_step = conversation_context.get("step", "showing_services")
    selected_service = conversation_context.get("data", {}).get("service")
    make = conversation_context.get("data", {}).get("make")
    car_model = conversation_context.get("data", {}).get("model")
    year = conversation_context.get("data", {}).get("year")
    registration = conversation_context.get("data", {}).get("registration_number")
    service_type = conversation_context.get("data", {}).get("service_type")
    
    # Build context-aware prompt
    if current_step == "showing_services":
        system_prompt = f"""You are a friendly and professional service booking assistant.

Current situation:
- You're showing available services to the customer
- Available services: {', '.join(AVAILABLE_SERVICES)}

User's message: "{message}"
Analysis: {analysis_result['user_intent']}

Your task:
1. Acknowledge what the user said in a warm, human way
2. If they selected a service, confirm it enthusiastically
3. Guide them naturally to the next step
4. Be conversational, friendly, and helpful
5. Keep it brief (2-3 sentences max)
6. Use emojis sparingly but naturally

Generate a natural, human-like response:"""
    
    elif current_step == "collecting_vehicle_details":
        system_prompt = f"""You are a friendly service booking assistant collecting vehicle details.

Current situation:
- Selected service: {selected_service}
- Already collected: Make={make or 'Not yet'}, Model={car_model or 'Not yet'}, Year={year or 'Not yet'}, Registration={registration or 'Not yet'}

User's message: "{message}"
Analysis: {analysis_result['user_intent']}

Your task:
- If they provided information, confirm it enthusiastically
- Ask for the NEXT missing piece of information naturally
- Be warm, professional, and human-like
- Keep it brief (2-3 sentences max)

Generate a natural response:"""
    
    elif current_step == "collecting_service_type":
        system_prompt = f"""You are a friendly service booking assistant collecting service type.

Current situation:
- Vehicle details collected: {make} {car_model} ({year})

User's message: "{message}"
Analysis: {analysis_result['user_intent']}

Your task:
- If they provided service type, confirm it
- If not, ask for service type naturally
- Be warm and professional
- Keep it brief (2-3 sentences max)

Generate a natural response:"""
    
    else:
        system_prompt = f"""You are a friendly service booking assistant. User said: "{message}". Respond naturally and helpfully."""
    
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


