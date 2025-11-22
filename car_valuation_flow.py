"""Car Valuation Flow Handler."""

import re
from typing import Optional, List, Dict, Any
from datetime import datetime
from conversation_state import (
    conversation_manager, 
    ConversationState, 
    detect_flow_switch,
    is_exit_request,
    get_main_menu_message
)
from database import car_db
from intent_service import generate_response
from car_valuation_analyzer import (
    analyze_valuation_message,
    generate_valuation_response,
    CarValuationAnalysisError,
)


# Cache for brands and fuel types (fetched from database)
_brands_cache: Optional[List[str]] = None
_fuel_types_cache: Optional[List[str]] = None

# Condition multipliers for valuation
CONDITION_MULTIPLIERS = {
    "excellent": 1.0,
    "very good": 0.9,
    "good": 0.8,
    "average": 0.7,
    "fair": 0.6,
    "poor": 0.5,
}


async def get_brands_from_db() -> List[str]:
    """Get available brands from database."""
    global _brands_cache
    if _brands_cache is None and car_db:
        try:
            _brands_cache = await car_db.get_available_brands()
        except Exception as e:
            print(f"Error fetching brands from database: {e}")
            _brands_cache = []
    return _brands_cache or []


async def get_fuel_types_from_db() -> List[str]:
    """Get available fuel types from database."""
    global _fuel_types_cache
    if _fuel_types_cache is None and car_db:
        try:
            # Get fuel types from database or use defaults
            # Search for cars with no filters to get a sample
            cars = await car_db.search_cars(
                brand=None,
                car_type=None,
                min_price=None,
                max_price=None,
                limit=1000
            )
            fuel_types = set()
            for car in cars:
                if car.fuel_type:
                    fuel_types.add(car.fuel_type)
            _fuel_types_cache = sorted(list(fuel_types)) if fuel_types else ["Petrol", "Diesel", "Electric", "CNG", "Hybrid"]
        except Exception as e:
            print(f"Error fetching fuel types from database: {e}")
            _fuel_types_cache = ["Petrol", "Diesel", "Electric", "CNG", "Hybrid"]
    return _fuel_types_cache or ["Petrol", "Diesel", "Electric", "CNG", "Hybrid"]


def clear_brands_cache():
    """Clear brands cache to force refresh from database."""
    global _brands_cache
    _brands_cache = None


def clear_fuel_types_cache():
    """Clear fuel types cache to force refresh from database."""
    global _fuel_types_cache
    _fuel_types_cache = None


async def extract_brand_from_message(message: str) -> Optional[str]:
    """Extract car brand from user message by checking against database brands."""
    message_lower = message.lower()
    brands = await get_brands_from_db()
    
    # Check for exact or partial matches
    for brand in brands:
        brand_lower = brand.lower()
        if brand_lower in message_lower or message_lower in brand_lower:
            return brand
    
    return None


def extract_year_from_message(message: str) -> Optional[int]:
    """Extract year from message. Returns 4-digit year."""
    # Look for 4-digit years (1990-2030)
    patterns = [
        r'\b(19[9]\d|20[0-3]\d)\b',  # 1990-2039
        r'year\s*[:\-]?\s*(\d{4})',
        r'(\d{4})\s*year',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, message)
        if match:
            year = int(match.group(1))
            current_year = datetime.now().year
            if 1990 <= year <= current_year:
                return year
    
    return None


def extract_condition_from_message(message: str) -> Optional[str]:
    """Extract car condition from message."""
    message_lower = message.lower()
    
    condition_keywords = {
        "excellent": ["excellent", "perfect", "mint", "like new", "showroom"],
        "very good": ["very good", "verygood", "great condition", "almost new"],
        "good": ["good", "well maintained", "decent"],
        "average": ["average", "okay", "ok", "normal", "regular"],
        "fair": ["fair", "decent condition", "usable"],
        "poor": ["poor", "bad", "damaged", "needs repair", "rough"]
    }
    
    for condition, keywords in condition_keywords.items():
        if any(keyword in message_lower for keyword in keywords):
            return condition
    
    return None


async def calculate_car_valuation(
    brand: str,
    model: str,
    year: int,
    fuel_type: str,
    condition: str
) -> Dict[str, Any]:
    """Calculate approximate car valuation based on provided information."""
    try:
        # Try to get base price from database (average price for similar cars)
        base_price = None
        if car_db:
            try:
                # Search for similar cars to get base price
                current_year = datetime.now().year
                age = current_year - year
                
                # Get cars of same brand and model
                similar_cars = await car_db.search_cars(
                    brand=brand,
                    car_type=None,
                    min_price=None,
                    max_price=None,
                    limit=10
                )
                
                if similar_cars:
                    # Filter by model if possible
                    model_cars = [c for c in similar_cars if model.lower() in (c.model or "").lower()]
                    if model_cars:
                        prices = [float(c.price) for c in model_cars if c.price]
                        if prices:
                            base_price = sum(prices) / len(prices)
                    else:
                        prices = [float(c.price) for c in similar_cars if c.price]
                        if prices:
                            base_price = sum(prices) / len(prices)
            except Exception as e:
                print(f"Error getting base price from database: {e}")
        
        # If no base price from database, estimate based on brand and year
        if base_price is None:
            # Rough estimates (in rupees) - can be improved with actual market data
            brand_base_prices = {
                "Tata": 800000,
                "Hyundai": 900000,
                "Maruti": 700000,
                "Mahindra": 850000,
                "Honda": 1000000,
                "Toyota": 1100000,
                "Ford": 950000,
                "Renault": 800000,
                "Skoda": 1200000,
                "Nissan": 900000,
            }
            base_price = brand_base_prices.get(brand, 800000)
        
        # Apply depreciation based on age
        current_year = datetime.now().year
        age = current_year - year
        
        # Depreciation: ~10% per year for first 5 years, then ~5% per year
        if age <= 5:
            depreciation_factor = 1.0 - (age * 0.10)
        else:
            depreciation_factor = 0.5 - ((age - 5) * 0.05)
        
        depreciation_factor = max(0.2, depreciation_factor)  # Minimum 20% of original value
        
        # Apply condition multiplier
        condition_lower = condition.lower()
        condition_mult = CONDITION_MULTIPLIERS.get(condition_lower, 0.7)
        
        # Calculate final valuation (ensure base_price is float)
        base_price = float(base_price) if base_price else 800000.0
        depreciated_price = base_price * depreciation_factor
        final_valuation = depreciated_price * condition_mult
        
        # Round to nearest 1000
        final_valuation = round(final_valuation / 1000) * 1000
        
        return {
            "base_price": base_price,
            "depreciation_factor": depreciation_factor,
            "condition_multiplier": condition_mult,
            "final_valuation": final_valuation,
            "valuation_lakhs": final_valuation / 100000,
            "age_years": age
        }
        
    except Exception as e:
        print(f"Error calculating valuation: {e}")
        return {
            "error": str(e),
            "final_valuation": None
        }


def format_valuation_result(valuation_data: Dict[str, Any], brand: str, model: str, year: int, fuel_type: str, condition: str) -> str:
    """Format valuation result for display."""
    if valuation_data.get("error") or valuation_data.get("final_valuation") is None:
        return (
            "I encountered an issue calculating the valuation. "
            "Please try again or contact us for a detailed valuation."
        )
    
    valuation = valuation_data["final_valuation"]
    valuation_lakhs = valuation_data["valuation_lakhs"]
    age = valuation_data["age_years"]
    
    message = (
        f"📊 *Car Valuation Result*\n\n"
        f"*Car Details:*\n"
        f"• Brand: {brand}\n"
        f"• Model: {model}\n"
        f"• Year: {year} ({age} years old)\n"
        f"• Fuel Type: {fuel_type}\n"
        f"• Condition: {condition.title()}\n\n"
        f"*Approximate Valuation:*\n"
        f"💰 ₹{valuation:,.0f} ({valuation_lakhs:.2f} Lakh)\n\n"
        f"*Note:* This is an approximate valuation based on the information provided. "
        f"For a more accurate valuation, we recommend a physical inspection.\n\n"
        f"Would you like to:\n"
        f"1️⃣ Value another car\n"
        f"2️⃣ Get more details about this valuation\n"
        f"3️⃣ Back to main menu"
    )
    
    return message


async def handle_car_valuation_flow(
    user_id: str,
    message: str,
    intent_result: Any
) -> str:
    """Handle the car valuation flow with intelligent message analysis."""
    state = conversation_manager.get_state(user_id)
    
    # Check for flow switch first
    if intent_result:
        current_step = state.step if state else None
        target_flow = detect_flow_switch(intent_result, message, "car_valuation", current_step)
        if target_flow:
            print(f"Flow switch detected in car_valuation_flow: car_valuation -> {target_flow}")
            conversation_manager.clear_state(user_id)
            # Return special marker that main.py will handle
            return f"__FLOW_SWITCH__:{target_flow}"
    
    # Check for exit/back to main menu
    if is_exit_request(message):
        conversation_manager.clear_state(user_id)
        return get_main_menu_message()
    
    # Get available brands and fuel types from database
    available_brands = await get_brands_from_db()
    available_fuel_types = await get_fuel_types_from_db()
    
    # Initialize flow if not already started
    if state is None or state.flow_name != "car_valuation":
        # Use intelligent analysis to extract information
        try:
            analysis = await analyze_valuation_message(
                message=message,
                conversation_context={"step": "collecting_info", "data": {}},
                available_brands=available_brands,
                available_fuel_types=available_fuel_types,
            )
            
            # Extract information from analysis
            brand = analysis.get("extracted_brand")
            model = analysis.get("extracted_model")
            year = analysis.get("extracted_year")
            fuel_type = analysis.get("extracted_fuel_type")
            condition = analysis.get("extracted_condition")
            
            # Initialize state
            conversation_manager.set_state(
                user_id,
                ConversationState(
                    user_id=user_id,
                    flow_name="car_valuation",
                    step="collecting_info",
                    data={
                        "brand": brand,
                        "model": model,
                        "year": year,
                        "fuel_type": fuel_type,
                        "condition": condition,
                    }
                )
            )
            
            # Generate intelligent response based on analysis
            try:
                response = await generate_valuation_response(
                    message=message,
                    conversation_context={"step": "collecting_info", "data": {"brand": brand, "model": model, "year": year, "fuel_type": fuel_type, "condition": condition}},
                    analysis_result=analysis,
                    available_brands=available_brands,
                    available_fuel_types=available_fuel_types,
                )
                return response
            except Exception as e:
                print(f"Error generating response: {e}")
                # Fallback to simple response
                if not brand:
                    return "Great! I'd be happy to help you get your car valued! 🚗💰\n\nWhich brand is your car?"
                elif not model:
                    return f"Perfect! I see you have a {brand} car. That's great! 👍\n\nWhat's the model name?"
                elif not year:
                    return f"Excellent! So it's a {brand} {model}. 🎯\n\nWhat year was it manufactured?"
                elif not fuel_type:
                    return f"Got it! A {year} {brand} {model}. 📅\n\nWhat's the fuel type? (Petrol, Diesel, Electric, CNG, or Hybrid)"
                elif not condition:
                    return f"Perfect! So it's a {fuel_type} {brand} {model} from {year}. ⛽\n\nHow would you describe the condition? (Excellent, Very Good, Good, Average, Fair, or Poor)"
        
        except CarValuationAnalysisError as e:
            print(f"Analysis error: {e}")
            # Fallback to simple extraction
            brand = await extract_brand_from_message(message)
            year = extract_year_from_message(message)
            condition = extract_condition_from_message(message)
            
            conversation_manager.set_state(
                user_id,
                ConversationState(
                    user_id=user_id,
                    flow_name="car_valuation",
                    step="collecting_info",
                    data={"brand": brand, "model": None, "year": year, "fuel_type": None, "condition": condition}
                )
            )
            
            if not brand:
                return "Great! I'd be happy to help you get your car valued! 🚗💰\n\nWhich brand is your car?"
            elif not year:
                return f"Perfect! I see you have a {brand} car. What year was it manufactured?"
            elif not condition:
                return f"Got it! A {year} {brand}. How would you describe the condition?"
    
    # Continue based on current step
    state = conversation_manager.get_state(user_id)
    
    # Safety check: state should exist after initialization, but verify to prevent AttributeError
    if not state:
        # Re-initialize if state is somehow None
        conversation_manager.set_state(
            user_id,
            ConversationState(
                user_id=user_id,
                flow_name="car_valuation",
                step="collecting_info",
                data={}
            )
        )
        state = conversation_manager.get_state(user_id)
    
    if state.step == "collecting_info":
        # Use intelligent analysis to understand user's message
        try:
            analysis = await analyze_valuation_message(
                message=message,
                conversation_context={
                    "step": state.step,
                    "data": state.data
                },
                available_brands=available_brands,
                available_fuel_types=available_fuel_types,
            )
            
            # Update criteria based on analysis
            brand = analysis.get("extracted_brand") or state.data.get("brand")
            model = analysis.get("extracted_model") or state.data.get("model")
            year = analysis.get("extracted_year") or state.data.get("year")
            fuel_type = analysis.get("extracted_fuel_type") or state.data.get("fuel_type")
            condition = analysis.get("extracted_condition") or state.data.get("condition")
            
            # Handle special intents
            user_intent = analysis.get("user_intent", "")
            
            if "changing_criteria" in user_intent.lower() or "change" in message.lower():
                # User wants to change criteria
                conversation_manager.update_state(user_id, step="collecting_info")
                conversation_manager.update_data(user_id, brand=None, model=None, year=None, fuel_type=None, condition=None)
                try:
                    response = await generate_valuation_response(
                        message=message,
                        conversation_context={"step": "collecting_info", "data": {}},
                        analysis_result=analysis,
                        available_brands=available_brands,
                        available_fuel_types=available_fuel_types,
                    )
                    return response
                except Exception as e:
                    print(f"Error generating response: {e}")
                    return "No problem! Let's start fresh. What brand is your car?"
            
            # Update state with extracted information
            conversation_manager.update_data(
                user_id,
                brand=brand,
                model=model,
                year=year,
                fuel_type=fuel_type,
                condition=condition
            )
            
            # Ensure values are not empty strings - validate and normalize
            if brand and isinstance(brand, str):
                brand = brand.strip()
            elif brand and not isinstance(brand, str):
                brand = str(brand).strip() if brand else None
            
            if model and isinstance(model, str):
                model = model.strip()
            elif model and not isinstance(model, str):
                model = str(model).strip() if model else None
            
            if fuel_type and isinstance(fuel_type, str):
                fuel_type = fuel_type.strip()
            elif fuel_type and not isinstance(fuel_type, str):
                fuel_type = str(fuel_type).strip() if fuel_type else None
            
            if condition and isinstance(condition, str):
                condition = condition.strip()
            elif condition and not isinstance(condition, str):
                condition = str(condition).strip() if condition else None
            
            # Check what's missing
            if not brand or (isinstance(brand, str) and brand == ""):
                try:
                    response = await generate_valuation_response(
                        message=message,
                        conversation_context={
                            "step": state.step,
                            "data": {"brand": None, "model": model, "year": year, "fuel_type": fuel_type, "condition": condition}
                        },
                        analysis_result=analysis,
                        available_brands=available_brands,
                        available_fuel_types=available_fuel_types,
                    )
                    return response
                except Exception as e:
                    print(f"Error generating response: {e}")
                    brands_list = ", ".join(available_brands[:5]) if available_brands else ""
                    return f"Which brand is your car? (e.g., {brands_list})" if brands_list else "Which brand is your car?"
            
            elif not model or (isinstance(model, str) and model == ""):
                try:
                    response = await generate_valuation_response(
                        message=message,
                        conversation_context={
                            "step": state.step,
                            "data": {"brand": brand, "model": None, "year": year, "fuel_type": fuel_type, "condition": condition}
                        },
                        analysis_result=analysis,
                        available_brands=available_brands,
                        available_fuel_types=available_fuel_types,
                    )
                    return response
                except Exception as e:
                    print(f"Error generating response: {e}")
                    return f"What's the model of your {brand} car?"
            
            elif not year or year == 0:
                try:
                    response = await generate_valuation_response(
                        message=message,
                        conversation_context={
                            "step": state.step,
                            "data": {"brand": brand, "model": model, "year": None, "fuel_type": fuel_type, "condition": condition}
                        },
                        analysis_result=analysis,
                        available_brands=available_brands,
                        available_fuel_types=available_fuel_types,
                    )
                    return response
                except Exception as e:
                    print(f"Error generating response: {e}")
                    return f"What year was your {brand} {model} manufactured?"
            
            elif not fuel_type or (isinstance(fuel_type, str) and fuel_type == ""):
                try:
                    response = await generate_valuation_response(
                        message=message,
                        conversation_context={
                            "step": state.step,
                            "data": {"brand": brand, "model": model, "year": year, "fuel_type": None, "condition": condition}
                        },
                        analysis_result=analysis,
                        available_brands=available_brands,
                        available_fuel_types=available_fuel_types,
                    )
                    return response
                except Exception as e:
                    print(f"Error generating response: {e}")
                    fuel_list = ", ".join(available_fuel_types)
                    return f"What's the fuel type? (e.g., {fuel_list})"
            
            elif not condition or (isinstance(condition, str) and condition == ""):
                try:
                    response = await generate_valuation_response(
                        message=message,
                        conversation_context={
                            "step": state.step,
                            "data": {"brand": brand, "model": model, "year": year, "fuel_type": fuel_type, "condition": None}
                        },
                        analysis_result=analysis,
                        available_brands=available_brands,
                        available_fuel_types=available_fuel_types,
                    )
                    return response
                except Exception as e:
                    print(f"Error generating response: {e}")
                    return "How would you describe the condition? (Excellent, Very Good, Good, Average, Fair, or Poor)"
            
            else:
                # All information collected, calculate valuation
                # Ensure we have valid values
                if not brand or not year or not fuel_type or not condition:
                    return "I need all the information to calculate the valuation. Please provide brand, year, fuel type, and condition."
                
                if not model or (isinstance(model, str) and model == ""):
                    model = "Unknown Model"  # Default if model not provided
                
                # Validate year is reasonable
                current_year = datetime.now().year
                if year < 1990 or year > current_year:
                    return f"Please provide a valid year between 1990 and {current_year}."
                
                try:
                    valuation_data = await calculate_car_valuation(
                        brand=brand,
                        model=model,
                        year=year,
                        fuel_type=fuel_type,
                        condition=condition
                    )
                    
                    # Verify valuation was calculated successfully
                    if not valuation_data or valuation_data.get("final_valuation") is None:
                        print(f"Valuation calculation returned None or error: {valuation_data}")
                        return (
                            "I encountered an issue calculating the valuation. "
                            "Please try again or contact us for a detailed valuation."
                        )
                    
                    # Store valuation in state
                    conversation_manager.update_data(user_id, valuation=valuation_data)
                    conversation_manager.update_state(user_id, step="showing_valuation")
                    
                    # Always return the formatted valuation result
                    result = format_valuation_result(valuation_data, brand, model, year, fuel_type, condition)
                    print(f"Valuation calculated successfully: ₹{valuation_data.get('final_valuation'):,.0f}")
                    return result
                    
                except Exception as e:
                    print(f"Error calculating valuation: {e}")
                    import traceback
                    traceback.print_exc()
                    return f"I encountered an issue calculating the valuation. Please try again later. Error: {str(e)}"
        
        except CarValuationAnalysisError as e:
            print(f"Analysis error in collecting_info: {e}")
            # Fallback to simple extraction
            brand = await extract_brand_from_message(message) or state.data.get("brand")
            model = state.data.get("model")  # Model extraction is complex, keep existing or ask
            year = extract_year_from_message(message) or state.data.get("year")
            fuel_type = state.data.get("fuel_type")
            condition = extract_condition_from_message(message) or state.data.get("condition")
            
            conversation_manager.update_data(user_id, brand=brand, model=model, year=year, fuel_type=fuel_type, condition=condition)
            
            if not brand:
                return "Which brand is your car?"
            elif not model:
                return f"What's the model of your {brand} car?"
            elif not year:
                return f"What year was your {brand} {model} manufactured?"
            elif not fuel_type:
                return "What's the fuel type?"
            elif not condition or (isinstance(condition, str) and condition == ""):
                return "How would you describe the condition?"
            else:
                # All information collected
                if not brand or not year or not fuel_type or not condition:
                    return "I need all the information to calculate the valuation. Please provide brand, year, fuel type, and condition."
                
                if not model or (isinstance(model, str) and model == ""):
                    model = "Unknown Model"
                
                # Validate year
                current_year = datetime.now().year
                if year < 1990 or year > current_year:
                    return f"Please provide a valid year between 1990 and {current_year}."
                
                try:
                    valuation_data = await calculate_car_valuation(brand, model, year, fuel_type, condition)
                    
                    # Verify valuation was calculated successfully
                    if not valuation_data or valuation_data.get("final_valuation") is None:
                        print(f"Valuation calculation returned None or error: {valuation_data}")
                        return (
                            "I encountered an issue calculating the valuation. "
                            "Please try again or contact us for a detailed valuation."
                        )
                    
                    conversation_manager.update_data(user_id, valuation=valuation_data)
                    conversation_manager.update_state(user_id, step="showing_valuation")
                    result = format_valuation_result(valuation_data, brand, model, year, fuel_type, condition)
                    print(f"Valuation calculated successfully (fallback): ₹{valuation_data.get('final_valuation'):,.0f}")
                    return result
                except Exception as e:
                    print(f"Error calculating valuation: {e}")
                    import traceback
                    traceback.print_exc()
                    return f"I encountered an issue calculating the valuation. Please try again later. Error: {str(e)}"
    
    elif state.step == "showing_valuation":
        # Handle post-valuation actions
        message_lower = message.lower().strip()
        
        if "1" in message_lower or "another" in message_lower or "new" in message_lower or "value another" in message_lower:
            # Value another car
            conversation_manager.update_state(user_id, step="collecting_info")
            conversation_manager.update_data(user_id, brand=None, model=None, year=None, fuel_type=None, condition=None, valuation=None)
            return "Great! Let's value another car! 🚗\n\nWhich brand is your car?"
        
        elif "3" in message_lower or "back" in message_lower or "menu" in message_lower or "main menu" in message_lower:
            # Back to main menu
            conversation_manager.clear_state(user_id)
            return (
                "Sure! How can I help you today? 😊\n\n"
                "You can:\n"
                "• Browse used cars\n"
                "• Get car valuation\n"
                "• Calculate EMI\n"
                "• Book a service\n\n"
                "What would you like to do?"
            )
        
        elif "2" in message_lower or "details" in message_lower or "more" in message_lower:
            # More details
            valuation_data = state.data.get("valuation", {})
            if valuation_data:
                return (
                    f"*Valuation Details:*\n\n"
                    f"Base Price: ₹{valuation_data.get('base_price', 0):,.0f}\n"
                    f"Depreciation Factor: {valuation_data.get('depreciation_factor', 0):.2f}\n"
                    f"Condition Multiplier: {valuation_data.get('condition_multiplier', 0):.2f}\n"
                    f"Car Age: {valuation_data.get('age_years', 0)} years\n\n"
                    f"For a detailed physical inspection and accurate valuation, please visit our showroom!"
                )
            else:
                return "I don't have the valuation details. Let's start a new valuation!"
        
        else:
            # Generate intelligent response
            try:
                analysis = await analyze_valuation_message(
                    message=message,
                    conversation_context={
                        "step": state.step,
                        "data": state.data
                    },
                    available_brands=available_brands,
                    available_fuel_types=available_fuel_types,
                )
                
                response = await generate_valuation_response(
                    message=message,
                    conversation_context={
                        "step": state.step,
                        "data": state.data
                    },
                    analysis_result=analysis,
                    available_brands=available_brands,
                    available_fuel_types=available_fuel_types,
                )
                return response
            except CarValuationAnalysisError as e:
                print(f"Analysis error in showing_valuation: {e}")
                return "Would you like to:\n1️⃣ Value another car\n2️⃣ Get more details about this valuation\n3️⃣ Back to main menu"
            except Exception as e:
                print(f"Error generating response: {e}")
                return "Would you like to:\n1️⃣ Value another car\n2️⃣ Get more details about this valuation\n3️⃣ Back to main menu"
    
    return "I'm not sure how to help with that. Could you please rephrase?"

