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
    
    # Build dynamic clarification rules based on available brands and types
    brands_list = ', '.join(available_brands[:10])  # Show first 10 brands
    types_list = ', '.join(available_types)
    
    # Generate dynamic examples based on actual available brands and types
    brand_examples = []
    type_examples = []
    
    # Find common brand variations/aliases
    brand_aliases = {
        "Suzuki": "Maruti",
        "Maruti Suzuki": "Maruti",
        "Hyundai": "Hyundai",
        "Honda": "Honda",
        "Toyota": "Toyota",
        "Tata": "Tata",
        "Mahindra": "Mahindra",
    }
    
    # Find common type variations
    type_variations = {
        "Hatch back": "Hatchback",
        "Hatch-back": "Hatchback",
        "hatch": "Hatchback",
        "SUV": "SUV",
        "Suv": "SUV",
        "suv": "SUV",
        "Sedan": "Sedan",
        "sedan": "Sedan",
    }
    
    # Build dynamic examples
    clarification_examples = []
    
    # Brand examples
    for alias, correct_brand in brand_aliases.items():
        if correct_brand in available_brands:
            clarification_examples.append(f'  * User says "{alias}" → extracted_brand="{correct_brand}", needs_clarification=true, clarification_question="Did you mean \'{correct_brand}\'? Please confirm."')
            break  # Use first matching example
    
    # Type examples
    for variation, correct_type in type_variations.items():
        if correct_type in available_types:
            clarification_examples.append(f'  * User says "{variation}" → extracted_type="{correct_type}", needs_clarification=true, clarification_question="Did you mean \'{correct_type}\'? Please confirm."')
            break  # Use first matching example
    
    # Add case-insensitive match example
    if available_types:
        first_type = available_types[0]
        clarification_examples.append(f'  * User says "{first_type.lower()}" → extracted_type="{first_type}", needs_clarification=false (case-insensitive match)')
    
    examples_text = '\n'.join(clarification_examples) if clarification_examples else '  * (No examples available)'
    
    # Build dynamic clarification rules
    clarification_rules = f"""CRITICAL - Dynamic Clarification Rules (based on available options):

Available Brands: {brands_list}{'...' if len(available_brands) > 10 else ''}
Available Types: {types_list}

Clarification Logic:
1. **Brand Matching**:
   - If user provides a brand that is SIMILAR but not EXACTLY matching any from: {available_brands[:5]}
   - Common variations: "Suzuki" → "Maruti", "Maruti Suzuki" → "Maruti"
   - Set needs_clarification=true AND extracted_brand to the CORRECTED brand from available options
   
2. **Type Matching**:
   - If user provides a type that is SIMILAR but not EXACTLY matching any from: {available_types}
   - Common variations: "Hatch back" → "Hatchback", "SUV" → "SUV", "hatch" → "Hatchback"
   - Set needs_clarification=true AND extracted_type to the CORRECTED type from available options

3. **Case Sensitivity**:
   - Case-insensitive exact matches (e.g., "hatchback" vs "Hatchback") → needs_clarification=false
   - Similar but not exact (e.g., "Hatch back" vs "Hatchback") → needs_clarification=true

4. **Confidence Threshold**:
   - If confidence is below 0.8 for any extracted field → needs_clarification=true

5. **IMPORTANT Rules**:
   - **ALWAYS** set extracted_brand/extracted_type to the CORRECTED value from available options, even when needs_clarification=true
   - **ALWAYS** provide a helpful clarification_question: "Did you mean '[corrected_value]'? Please confirm."
   - The corrected value MUST be one of the available brands/types listed above

Dynamic Examples (based on current database):
{examples_text}

When generating clarification_question:
- Use the exact format: "Did you mean '[corrected_value]'? Please confirm."
- The corrected_value MUST match exactly one of the available brands or types
- Be helpful and friendly in your question"""
    
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

{clarification_rules}
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
    
    # Build comprehensive context-aware prompt
    user_intent = analysis_result.get('user_intent', 'unknown')
    extracted_brand = analysis_result.get('extracted_brand')
    extracted_budget = analysis_result.get('extracted_budget')
    extracted_type = analysis_result.get('extracted_type')
    
    # Build context summary
    context_summary = f"""Current situation:
- Step: {current_step}
- Already collected: Brand={collected_brand or 'Not yet'}, Budget={collected_budget or 'Not yet'}, Type={collected_type or 'Not yet'}
- User just provided: Brand={extracted_brand or 'None'}, Budget={extracted_budget or 'None'}, Type={extracted_type or 'None'}
- User intent: {user_intent}
- Available brands: {', '.join(available_brands[:10])}{'...' if len(available_brands) > 10 else ''}
- Available types: {', '.join(available_types)}"""
    
    # Determine what's missing
    missing_info = []
    if not collected_brand and not extracted_brand:
        missing_info.append("brand")
    if not collected_budget and not extracted_budget:
        missing_info.append("budget")
    if not collected_type and not extracted_type:
        missing_info.append("car type")
    
    missing_text = ", ".join(missing_info) if missing_info else "nothing (all collected!)"
    
    system_prompt = f"""You are a friendly, professional, and human-like car sales assistant helping a customer find their perfect used car.

{context_summary}

What's still needed: {missing_text}

User's message: "{message}"

CRITICAL INSTRUCTIONS:
1. **Be Natural & Human**: Respond like a real person, not a robot. Use natural language, vary your responses.
2. **Acknowledge First**: Always acknowledge what the user said or provided before asking for more.
3. **Be Enthusiastic**: If they provided information (brand/budget/type), show genuine enthusiasm and confirm it.
4. **Ask Naturally**: Ask for missing information in a conversational way, not like filling a form.
5. **Be Contextual**: Reference what they've already told you to show you're listening.
6. **Keep it Brief**: 2-3 sentences maximum. Be concise but warm.
7. **Use Emojis Sparingly**: Only 1-2 emojis max, use them naturally (🚗, 👍, 😊, etc.)
8. **Be Helpful**: If they seem confused, clarify gently. If they want to change something, be supportive.

Examples of good responses:
- "Great choice! I love [brand] cars - they're really reliable. What's your budget range?"
- "Perfect! So you're looking for a [brand] [type]. What's your budget?"
- "Excellent! A [brand] within [budget] lakh - that's a smart range. What type of car are you thinking? SUV, sedan, or hatchback?"

Generate a natural, human-like response that:
- Acknowledges what they said/provided
- Confirms any new information they gave
- Asks for the NEXT missing piece naturally
- Sounds like a real person, not a template"""
    
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


async def analyze_test_drive_details(
    message: str,
    conversation_context: Dict[str, Any],
    *,
    model: Optional[str] = None,
    timeout: float = 12.0,
    client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """Analyze user message to extract multiple test drive details at once.
    
    Can extract: date, time, name, phone, driving_license_status, location
    
    Returns:
        {
            "extracted_date": str or None,
            "extracted_time": str or None,
            "extracted_name": str or None,
            "extracted_phone": str or None,
            "extracted_has_dl": bool or None,  # True/False if clear, None if unclear
            "extracted_location": str or None,  # "showroom" or "home"
            "confidence": float,
            "needs_confirmation": bool,
            "confirmation_message": str or None,
            "extracted_fields": list of field names that were extracted
        }
    """
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise BrowseCarAnalysisError("GOOGLE_API_KEY is not configured")
    
    resolved_model = model or os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    url = _API_URL_TEMPLATE.format(model=resolved_model)
    
    current_step = conversation_context.get("step", "test_drive_collecting")
    collected_data = conversation_context.get("data", {})
    
    # What we already have
    has_date = collected_data.get("test_drive_date") is not None
    has_time = collected_data.get("test_drive_time") is not None
    has_name = collected_data.get("test_drive_name") is not None
    has_phone = collected_data.get("test_drive_phone") is not None
    has_dl = collected_data.get("test_drive_has_dl") is not None
    has_location = collected_data.get("test_drive_location") is not None
    
    context_info = f"""
Current conversation state:
- Step: {current_step}
- Already collected:
  * Date: {collected_data.get('test_drive_date', 'Not yet')}
  * Time: {collected_data.get('test_drive_time', 'Not yet')}
  * Name: {collected_data.get('test_drive_name', 'Not yet')}
  * Phone: {collected_data.get('test_drive_phone', 'Not yet')}
  * Driving License: {collected_data.get('test_drive_has_dl', 'Not yet')}
  * Location: {collected_data.get('test_drive_location', 'Not yet')}
"""
    
    prompt = f"""You are an intelligent assistant helping a customer book a test drive. Extract ALL relevant information from the user's message.

{context_info}

User's message: "{message}"

Extract the following information if present in the message:
1. **Date** - Test drive date (e.g., "today", "tomorrow", "Friday", "15th January", "next week")
2. **Time** - Test drive time (e.g., "5 pm", "2:30", "morning", "afternoon", "evening")
3. **Name** - Customer's full name (e.g., "John Doe", "My name is John", "I'm John")
4. **Phone** - Phone number (10-digit Indian number, may include spaces/dashes)
5. **Driving License** - Whether they have a license (yes/no/true/false)
6. **Location** - "showroom" or "home" or "home pickup" or "1" or "2"

IMPORTANT RULES:
- Extract ALL fields that are present in the message, even if multiple
- If a field is already collected and user provides a new value, use the NEW value
- For driving license: "yes"/"y"/"have"/"i have" = true, "no"/"n"/"don't have" = false, unclear = null
- For location: "showroom"/"1" = "showroom", "home"/"pickup"/"2" = "home"
- Phone: Extract only digits, should be 10 digits for Indian numbers
- Date: Keep as user said it (e.g., "today", "tomorrow", "Friday")
- Time: Keep as user said it (e.g., "5 pm", "2:30", "morning")

If you're UNCERTAIN about any extraction (low confidence), set needs_confirmation=true and provide a confirmation_message.

Return your analysis as JSON with these exact keys:
{{
    "extracted_date": "date_string_or_null",
    "extracted_time": "time_string_or_null",
    "extracted_name": "name_string_or_null",
    "extracted_phone": "phone_string_or_null",
    "extracted_has_dl": true_or_false_or_null,
    "extracted_location": "showroom_or_home_or_null",
    "confidence": 0.0_to_1.0,
    "needs_confirmation": true_or_false,
    "confirmation_message": "message_or_null",
    "extracted_fields": ["list", "of", "field", "names", "extracted"]
}}
"""
    
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}]
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
        
        # Clean phone number (extract only digits)
        phone = parsed.get("extracted_phone")
        if phone:
            phone_digits = ''.join(filter(str.isdigit, str(phone)))
            if len(phone_digits) >= 10:
                # Take last 10 digits for Indian numbers
                phone = phone_digits[-10:]
            else:
                phone = None
        
        return {
            "extracted_date": parsed.get("extracted_date"),
            "extracted_time": parsed.get("extracted_time"),
            "extracted_name": parsed.get("extracted_name"),
            "extracted_phone": phone,
            "extracted_has_dl": parsed.get("extracted_has_dl"),
            "extracted_location": parsed.get("extracted_location"),
            "confidence": parsed.get("confidence", 0.0),
            "needs_confirmation": parsed.get("needs_confirmation", False),
            "confirmation_message": parsed.get("confirmation_message"),
            "extracted_fields": parsed.get("extracted_fields", [])
        }
    except json.JSONDecodeError as exc:
        raise BrowseCarAnalysisError("Failed to parse Gemini response as JSON") from exc


async def validate_and_extract_field(
    message: str,
    field_type: str,  # "name" or "address"
    conversation_context: Dict[str, Any],
    *,
    model: Optional[str] = None,
    timeout: float = 12.0,
    client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """Validate and extract a specific field (name or address) using LLM.
    
    Returns:
        {
            "extracted_value": str or None,
            "is_valid": bool,
            "confidence": float,
            "needs_confirmation": bool,
            "confirmation_message": str or None,
            "validation_reason": str or None
        }
    """
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise BrowseCarAnalysisError("GOOGLE_API_KEY is not configured")
    
    resolved_model = model or os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    url = _API_URL_TEMPLATE.format(model=resolved_model)
    
    current_step = conversation_context.get("step", "")
    
    if field_type == "name":
        field_description = "customer's full name"
        validation_rules = """
- Must be a person's name (not a word like "say", "yes", "no", "ok", etc.)
- Should be at least 2 characters long
- Can include first name and last name
- May include titles like "Mr.", "Ms.", "Dr." but extract the actual name
- Examples of VALID names: "John Doe", "Kashyap", "Sai", "Rahul Kumar", "Priya"
- Examples of INVALID: "say", "yes", "no", "ok", "sure", "confirm", "change"
- If the message is just "say" or similar words, it's NOT a name
"""
        examples_valid = "John, Kashyap, Sai, Rahul Kumar, Priya Sharma"
        examples_invalid = "say, yes, no, ok, sure, confirm"
    elif field_type == "address":
        field_description = "complete address for home pickup"
        validation_rules = """
- Must be a complete address (not just a word or short phrase)
- Should be at least 15 characters long
- Should include street/house number, area, city, or landmark
- Examples of VALID addresses: "123 Main Street, Bangalore", "House No. 45, MG Road, Mumbai", "Near City Mall, Delhi"
- Examples of INVALID: "home", "my place", "here", "yes", "no", single words
- If the message is too short or vague, ask for more details
"""
        examples_valid = "123 Main Street, Bangalore", "House No. 45, MG Road, Mumbai"
        examples_invalid = "home, my place, here, yes, no"
    else:
        raise ValueError(f"Unknown field_type: {field_type}")
    
    prompt = f"""You are an intelligent assistant validating user input for a {field_type} field.

Current step: {current_step}
User's message: "{message}"

Your task:
1. Determine if the message contains a valid {field_description}
2. Extract the {field_type} if valid
3. If uncertain or invalid, ask for confirmation

Validation Rules:
{validation_rules}

Examples of VALID {field_type}s: {examples_valid}
Examples of INVALID inputs: {examples_invalid}

IMPORTANT:
- If the message is clearly NOT a {field_type} (e.g., "say", "yes", "no", "ok"), set is_valid=false
- If the message is too short or vague, set is_valid=false and needs_confirmation=true
- If the message contains a valid {field_type}, extract it and set is_valid=true
- Be strict - only accept clear, valid {field_type}s

Return your analysis as JSON with these exact keys:
{{
    "extracted_value": "extracted_{field_type}_or_null",
    "is_valid": true_or_false,
    "confidence": 0.0_to_1.0,
    "needs_confirmation": true_or_false,
    "confirmation_message": "message_or_null",
    "validation_reason": "reason_for_validation_decision_or_null"
}}
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
        return {
            "extracted_value": parsed.get("extracted_value"),
            "is_valid": parsed.get("is_valid", False),
            "confidence": parsed.get("confidence", 0.0),
            "needs_confirmation": parsed.get("needs_confirmation", False),
            "confirmation_message": parsed.get("confirmation_message"),
            "validation_reason": parsed.get("validation_reason")
        }
    except json.JSONDecodeError as exc:
        raise BrowseCarAnalysisError("Failed to parse Gemini response as JSON") from exc

