"""Browse Used Car Flow Handler."""

import re
from typing import Optional, List, Dict, Any
from conversation_state import (
    conversation_manager, 
    ConversationState, 
    detect_flow_switch,
    is_exit_request,
    get_main_menu_message
)
from database import car_db, Car
from intent_service import generate_response
from browse_car_analyzer import (
    analyze_browse_car_message,
    generate_browse_car_response,
    BrowseCarAnalysisError,
)


# Cache for brands and car types (fetched from database)
_brands_cache: Optional[List[str]] = None
_car_types_cache: Optional[List[str]] = None


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


async def get_car_types_from_db() -> List[str]:
    """Get available car types from database."""
    global _car_types_cache
    if _car_types_cache is None and car_db:
        try:
            _car_types_cache = await car_db.get_available_car_types()
        except Exception as e:
            print(f"Error fetching car types from database: {e}")
            _car_types_cache = []
    return _car_types_cache or []


def clear_brands_cache():
    """Clear brands cache to force refresh from database."""
    global _brands_cache
    _brands_cache = None


def clear_car_types_cache():
    """Clear car types cache to force refresh from database."""
    global _car_types_cache
    _car_types_cache = None


async def extract_brand_from_message(message: str) -> Optional[str]:
    """Extract car brand from user message by checking against database brands."""
    message_lower = message.lower()
    brands = await get_brands_from_db()
    
    # Check for exact or partial matches
    for brand in brands:
        brand_lower = brand.lower()
        if brand_lower in message_lower or message_lower in brand_lower:
            return brand  # Return as stored in database
    
    return None


def extract_budget_from_message(message: str) -> Optional[tuple]:
    """Extract budget range from message. Returns (min, max) in lakhs."""
    message_lower = message.lower()
    
    # Look for patterns like "5 lakh", "5-10 lakh", "under 10 lakh"
    patterns = [
        r'(\d+)\s*-\s*(\d+)\s*lakh',
        r'(\d+)\s*to\s*(\d+)\s*lakh',
        r'between\s*(\d+)\s*and\s*(\d+)\s*lakh',
        r'under\s*(\d+)\s*lakh',
        r'upto\s*(\d+)\s*lakh',
        r'(\d+)\s*lakh',
        r'(\d+)\s*lac',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, message_lower)
        if match:
            if len(match.groups()) == 2:
                min_price = float(match.group(1)) * 100000  # Convert to rupees
                max_price = float(match.group(2)) * 100000
                return (min_price, max_price)
            elif len(match.groups()) == 1:
                max_price = float(match.group(1)) * 100000
                return (None, max_price)
    
    return None


async def extract_car_type_from_message(message: str) -> Optional[str]:
    """Extract car type from user message by checking against database car types."""
    message_lower = message.lower()
    car_types = await get_car_types_from_db()
    
    # Check for exact or partial matches
    for car_type in car_types:
        car_type_lower = car_type.lower()
        if car_type_lower in message_lower or message_lower in car_type_lower:
            return car_type  # Return as stored in database
    
    return None


def _transition_to_emi_flow(user_id: str, state: ConversationState) -> str:
    """Helper function to transition from browse_car flow to EMI flow.
    
    Args:
        user_id: User identifier
        state: Current conversation state
    
    Returns:
        Flow switch marker string
    """
    selected_car = state.data.get("selected_car")
    conversation_manager.clear_state(user_id)
    # Store selected car temporarily for EMI flow
    if selected_car:
        conversation_manager.set_state(
            user_id,
            ConversationState(
                user_id=user_id,
                flow_name="emi",
                step="down_payment",
                data={"selected_car": selected_car, "down_payment": None, "tenure": None}
            )
        )
    return "__FLOW_SWITCH__:emi"


def format_car_list(cars: List[Car]) -> str:
    """Format list of cars for display."""
    if not cars:
        return "Sorry, I couldn't find any cars matching your criteria. Would you like to adjust your search?"
    
    message = f"Great! I found {len(cars)} car(s) for you:\n\n"
    
    for idx, car in enumerate(cars, start=1):
        price_lakhs = (car.price or 0) / 100000
        year_str = f"({car.year})" if car.year else ""
        variant_str = f" {car.variant}" if car.variant else ""
        
        message += f"*{idx}. {car.brand or 'N/A'} {car.model or 'N/A'}{variant_str} {year_str}*\n"
        message += f"   💰 Price: ₹{price_lakhs:.2f} Lakh\n"
        if car.type:
            message += f"   🚗 Type: {car.type}\n"
        if car.fuel_type:
            message += f"   ⛽ Fuel: {car.fuel_type}\n"
        if car.transmission:
            message += f"   🔧 Transmission: {car.transmission}\n"
        if car.mileage:
            message += f"   📊 Mileage: {car.mileage:,} km\n"
        if car.registration_number:
            message += f"   🆔 Reg: {car.registration_number}\n"
        message += "\n"
    
    message += "Please reply with the *number* of the car you're interested in, or type 'change' to modify your search criteria."
    
    return message


async def handle_browse_car_flow(
    user_id: str,
    message: str,
    intent_result: Any
) -> str:
    """Handle the browse used car flow with intelligent message analysis."""
    state = conversation_manager.get_state(user_id)
    
    # Check for flow switch first
    if intent_result:
        current_step = state.step if state else None
        target_flow = detect_flow_switch(intent_result, message, "browse_car", current_step)
        if target_flow:
            print(f"Flow switch detected in browse_car_flow: browse_car -> {target_flow}")
            conversation_manager.clear_state(user_id)
            # Return special marker that main.py will handle
            return f"__FLOW_SWITCH__:{target_flow}"
    
    # Check for exit/back to main menu
    if is_exit_request(message):
        conversation_manager.clear_state(user_id)
        return get_main_menu_message()
    
    # Get available brands and types from database
    available_brands = await get_brands_from_db()
    available_types = await get_car_types_from_db()
    
    # Initialize flow if not already started
    if state is None or state.flow_name != "browse_car":
        # Use intelligent analysis to extract information
        try:
            analysis = await analyze_browse_car_message(
                message=message,
                conversation_context={"step": "collecting_criteria", "data": {}},
                available_brands=available_brands,
                available_types=available_types,
            )
            
            # Extract information from analysis
            brand = analysis.get("extracted_brand")
            budget = analysis.get("extracted_budget")
            car_type = analysis.get("extracted_type")
            
            # Initialize state
            conversation_manager.set_state(
                user_id,
                ConversationState(
                    user_id=user_id,
                    flow_name="browse_car",
                    step="collecting_criteria",
                    data={
                        "brand": brand,
                        "budget": budget,
                        "car_type": car_type,
                    }
                )
            )
            
            # Generate intelligent response based on analysis
            try:
                response = await generate_browse_car_response(
                    message=message,
                    conversation_context={"step": "collecting_criteria", "data": {"brand": brand, "budget": budget, "car_type": car_type}},
                    analysis_result=analysis,
                    available_brands=available_brands,
                    available_types=available_types,
                )
                return response
            except Exception as e:
                print(f"Error generating response: {e}")
                # Fallback to simple response
                if not brand:
                    return "Great! I'd be happy to help you find the perfect used car! 🚗\n\nWhich brand are you interested in?"
                elif not budget:
                    return f"Perfect! I see you're interested in {brand} cars. That's a great choice! 👍\n\nWhat's your budget range?"
                elif not car_type:
                    return f"Excellent! So you're looking for a {brand} car within your budget. 🎯\n\nWhat type of car are you looking for?"
        
        except BrowseCarAnalysisError as e:
            print(f"Analysis error: {e}")
            # Fallback to simple extraction
            brand = await extract_brand_from_message(message)
            budget = extract_budget_from_message(message)
            car_type = await extract_car_type_from_message(message)
            
            conversation_manager.set_state(
                user_id,
                ConversationState(
                    user_id=user_id,
                    flow_name="browse_car",
                    step="collecting_criteria",
                    data={"brand": brand, "budget": budget, "car_type": car_type}
                )
            )
            
            if not brand:
                return "Great! I'd be happy to help you find the perfect used car! 🚗\n\nWhich brand are you interested in?"
            elif not budget:
                return f"Perfect! I see you're interested in {brand} cars. That's a great choice! 👍\n\nWhat's your budget range?"
            elif not car_type:
                return f"Excellent! So you're looking for a {brand} car within your budget. 🎯\n\nWhat type of car are you looking for?"
    
    # Continue based on current step
    state = conversation_manager.get_state(user_id)
    
    # Safety check: state should exist after initialization, but verify to prevent AttributeError
    if not state:
        # Re-initialize if state is somehow None
        conversation_manager.set_state(
            user_id,
            ConversationState(
                user_id=user_id,
                flow_name="browse_car",
                step="collecting_criteria",
                data={}
            )
        )
        state = conversation_manager.get_state(user_id)
    
    if state.step == "collecting_criteria":
        # Use intelligent analysis to understand user's message
        try:
            analysis = await analyze_browse_car_message(
                message=message,
                conversation_context={
                    "step": state.step,
                    "data": state.data
                },
                available_brands=available_brands,
                available_types=available_types,
            )
            
            # Update criteria based on analysis
            brand = analysis.get("extracted_brand") or state.data.get("brand")
            budget = analysis.get("extracted_budget") or state.data.get("budget")
            car_type = analysis.get("extracted_type") or state.data.get("car_type")
            
            # Handle special intents
            user_intent = analysis.get("user_intent", "")
            
            if "changing_criteria" in user_intent.lower() or "change" in message.lower():
                # User wants to change criteria
                conversation_manager.update_state(user_id, step="collecting_criteria")
                conversation_manager.update_data(user_id, brand=None, budget=None, car_type=None)
                try:
                    response = await generate_browse_car_response(
                        message=message,
                        conversation_context={"step": "collecting_criteria", "data": {}},
                        analysis_result=analysis,
                        available_brands=available_brands,
                        available_types=available_types,
                    )
                    return response
                except:
                    return "No problem! Let's start fresh. What brand are you interested in?"
            
            # Update state with extracted information
            conversation_manager.update_data(
                user_id,
                brand=brand,
                budget=budget,
                car_type=car_type
            )
            
            # Check what's missing
            if not brand:
                try:
                    response = await generate_browse_car_response(
                        message=message,
                        conversation_context={
                            "step": state.step,
                            "data": {"brand": None, "budget": budget, "car_type": car_type}
                        },
                        analysis_result=analysis,
                        available_brands=available_brands,
                        available_types=available_types,
                    )
                    return response
                except:
                    brands_list = ", ".join(available_brands[:5]) if available_brands else ""
                    return f"Which brand are you interested in? (e.g., {brands_list})" if brands_list else "Which brand are you interested in?"
            
            elif not budget:
                try:
                    response = await generate_browse_car_response(
                        message=message,
                        conversation_context={
                            "step": state.step,
                            "data": {"brand": brand, "budget": None, "car_type": car_type}
                        },
                        analysis_result=analysis,
                        available_brands=available_brands,
                        available_types=available_types,
                    )
                    return response
                except:
                    return "What's your budget range?"
            
            elif not car_type:
                try:
                    response = await generate_browse_car_response(
                        message=message,
                        conversation_context={
                            "step": state.step,
                            "data": {"brand": brand, "budget": budget, "car_type": None}
                        },
                        analysis_result=analysis,
                        available_brands=available_brands,
                        available_types=available_types,
                    )
                    return response
                except:
                    types_list = ", ".join(available_types) if available_types else ""
                    return f"What type of car? (e.g., {types_list})" if types_list else "What type of car are you looking for?"
            
            else:
                # All criteria collected, search for cars
                # Safely unpack budget with type validation
                if budget and isinstance(budget, tuple) and len(budget) == 2:
                    min_price, max_price = budget
                else:
                    min_price, max_price = None, None
                
                try:
                    cars = await car_db.search_cars(
                        brand=brand,
                        car_type=car_type,
                        min_price=min_price,
                        max_price=max_price,
                        limit=10
                    )
                    
                    if not cars:
                        try:
                            # Generate intelligent response for no results
                            response = await generate_browse_car_response(
                                message=message,
                                conversation_context={
                                    "step": state.step,
                                    "data": {"brand": brand, "budget": budget, "car_type": car_type, "no_results": True}
                                },
                                analysis_result=analysis,
                                available_brands=available_brands,
                                available_types=available_types,
                            )
                            return response
                        except:
                            return (
                                "I couldn't find any cars matching your exact criteria. 😔\n\n"
                                "Would you like to:\n"
                                "1. Try a different brand\n"
                                "2. Adjust your budget\n"
                                "3. Change the car type\n\n"
                                "Just let me know what you'd like to change!"
                            )
                    
                    # Store cars in state
                    conversation_manager.update_data(user_id, cars=[c.to_dict() for c in cars])
                    conversation_manager.update_state(user_id, step="showing_cars")
                    
                    return format_car_list(cars)
                    
                except Exception as e:
                    print(f"Database error in browse_car_flow (collecting_criteria): {type(e).__name__}: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    return (
                        "I encountered an issue searching for cars. "
                        "Please try again in a moment, or contact us if the problem persists."
                    )
        
        except BrowseCarAnalysisError as e:
            print(f"Analysis error in collecting_criteria: {e}")
            # Fallback to simple extraction
            brand = await extract_brand_from_message(message) or state.data.get("brand")
            budget = extract_budget_from_message(message) or state.data.get("budget")
            car_type = await extract_car_type_from_message(message) or state.data.get("car_type")
            
            conversation_manager.update_data(user_id, brand=brand, budget=budget, car_type=car_type)
            
            if not brand:
                return "Which brand are you interested in?"
            elif not budget:
                return "What's your budget range?"
            elif not car_type:
                return "What type of car are you looking for?"
            else:
                # All criteria collected, search for cars
                # Safely unpack budget with type validation
                if budget and isinstance(budget, tuple) and len(budget) == 2:
                    min_price, max_price = budget
                else:
                    min_price, max_price = None, None
                
                try:
                    cars = await car_db.search_cars(
                        brand=brand,
                        car_type=car_type,
                        min_price=min_price,
                        max_price=max_price,
                        limit=10
                    )
                    
                    if not cars:
                        return (
                            "I couldn't find any cars matching your exact criteria. 😔\n\n"
                            "Would you like to try different criteria?"
                        )
                    
                    conversation_manager.update_data(user_id, cars=[c.to_dict() for c in cars])
                    conversation_manager.update_state(user_id, step="showing_cars")
                    
                    return format_car_list(cars)
                    
                except Exception as e:
                    print(f"Database error in browse_car_flow (fallback path): {type(e).__name__}: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    return (
                        "I encountered an issue searching for cars. "
                        "Please try again in a moment, or contact us if the problem persists."
                    )
    
    elif state.step == "showing_cars":
        # Use intelligent analysis to understand user's message
        try:
            analysis = await analyze_browse_car_message(
                message=message,
                conversation_context={
                    "step": state.step,
                    "data": state.data
                },
                available_brands=available_brands,
                available_types=available_types,
            )
            
            user_intent = analysis.get("user_intent", "").lower()
            message_lower = message.lower().strip()
            
            # Check if user wants to change criteria
            if "changing_criteria" in user_intent or "change" in message_lower or "modify" in message_lower or "different" in message_lower:
                conversation_manager.update_state(user_id, step="collecting_criteria")
                conversation_manager.update_data(user_id, cars=None)
                try:
                    response = await generate_browse_car_response(
                        message=message,
                        conversation_context={"step": "collecting_criteria", "data": {}},
                        analysis_result=analysis,
                        available_brands=available_brands,
                        available_types=available_types,
                    )
                    return response
                except:
                    return "No problem! Let's start fresh. 🔄\n\nWhat would you like to change? Brand, Budget, or Car type?"
            
            # Check if user is selecting a car
            if "selecting_car" in user_intent or any(char.isdigit() for char in message_lower):
                try:
                    car_number = int(message_lower)
                    cars_data = state.data.get("cars", [])
                    
                    if 1 <= car_number <= len(cars_data):
                        selected_car = cars_data[car_number - 1]
                        conversation_manager.update_data(user_id, selected_car=selected_car)
                        conversation_manager.update_state(user_id, step="car_selected")
                        
                        try:
                            response = await generate_browse_car_response(
                                message=message,
                                conversation_context={
                                    "step": "car_selected",
                                    "data": {"selected_car": selected_car}
                                },
                                analysis_result=analysis,
                                available_brands=available_brands,
                                available_types=available_types,
                            )
                            return response
                        except:
                            return (
                                f"Excellent choice! You've selected the *{selected_car.get('brand')} {selected_car.get('model')}* 🎉\n\n"
                                "What would you like to do next?\n\n"
                                "1️⃣ Book a test drive\n"
                                "2️⃣ Calculate EMI\n"
                                "3️⃣ Change search criteria\n\n"
                                "Just reply with '1', '2', or '3'!"
                            )
                    else:
                        return (
                            f"Please select a number between 1 and {len(cars_data)}. "
                            "Or type 'change' to modify your search criteria."
                        )
                except ValueError:
                    # Not a number, generate intelligent response
                    try:
                        response = await generate_browse_car_response(
                            message=message,
                            conversation_context={
                                "step": state.step,
                                "data": state.data
                            },
                            analysis_result=analysis,
                            available_brands=available_brands,
                            available_types=available_types,
                        )
                        return response
                    except:
                        return (
                            "Please reply with the *number* of the car you're interested in (1, 2, 3, etc.), "
                            "or type 'change' to modify your search criteria."
                        )
            
            # Generate intelligent response for other cases
            try:
                response = await generate_browse_car_response(
                    message=message,
                    conversation_context={
                        "step": state.step,
                        "data": state.data
                    },
                    analysis_result=analysis,
                    available_brands=available_brands,
                    available_types=available_types,
                )
                return response
            except:
                return "I didn't quite catch that. Please select a car number or type 'change' to modify your search."
        
        except BrowseCarAnalysisError as e:
            print(f"Analysis error in showing_cars: {e}")
            # Fallback to simple logic
            message_lower = message.lower().strip()
            
            if message_lower in ["change", "modify", "different", "new search"]:
                conversation_manager.update_state(user_id, step="collecting_criteria")
                conversation_manager.update_data(user_id, cars=None)
                return "No problem! Let's start fresh. What would you like to change?"
            
            try:
                car_number = int(message_lower)
                cars_data = state.data.get("cars", [])
                if 1 <= car_number <= len(cars_data):
                    selected_car = cars_data[car_number - 1]
                    # Validate selected_car structure
                    if not isinstance(selected_car, dict):
                        return "I encountered an issue with the car data. Please try selecting again."
                    # Ensure required keys exist with defaults
                    if "brand" not in selected_car:
                        selected_car["brand"] = "Unknown"
                    if "model" not in selected_car:
                        selected_car["model"] = "Unknown"
                    conversation_manager.update_data(user_id, selected_car=selected_car)
                    conversation_manager.update_state(user_id, step="car_selected")
                    return f"Excellent choice! You've selected the *{selected_car.get('brand')} {selected_car.get('model')}* 🎉\n\nWhat would you like to do next?\n\n1️⃣ Book a test drive\n2️⃣ Change search criteria"
            except ValueError:
                return "Please reply with the number of the car you're interested in, or type 'change' to modify your search criteria."
    
    elif state.step == "car_selected":
        # Use intelligent analysis
        try:
            analysis = await analyze_browse_car_message(
                message=message,
                conversation_context={
                    "step": state.step,
                    "data": state.data
                },
                available_brands=available_brands,
                available_types=available_types,
            )
            
            user_intent = analysis.get("user_intent", "").lower()
            message_lower = message.lower().strip()
            
            if "changing_criteria" in user_intent or "change" in message_lower or "2" in message_lower or "different" in message_lower:
                conversation_manager.update_state(user_id, step="collecting_criteria")
                conversation_manager.update_data(user_id, selected_car=None, cars=None)
                try:
                    response = await generate_browse_car_response(
                        message=message,
                        conversation_context={"step": "collecting_criteria", "data": {}},
                        analysis_result=analysis,
                        available_brands=available_brands,
                        available_types=available_types,
                    )
                    return response
                except:
                    return "Sure! Let's start a new search. What are you looking for?"
            
            if "2" in message_lower or "emi" in message_lower or "loan" in message_lower or "finance" in message_lower or "installment" in message_lower:
                # User wants to calculate EMI
                # Store selected car and let main.py handle routing
                return _transition_to_emi_flow(user_id, state)
            
            if "booking_test_drive" in user_intent or "test drive" in message_lower or "1" in message_lower or "book" in message_lower:
                conversation_manager.update_state(user_id, step="test_drive_name")
                try:
                    response = await generate_browse_car_response(
                        message=message,
                        conversation_context={"step": "test_drive_name", "data": state.data},
                        analysis_result=analysis,
                        available_brands=available_brands,
                        available_types=available_types,
                    )
                    return response
                except:
                    return "Perfect! Let's get your test drive booked! 🚗💨\n\nTo get started, could you please share your name?"
            
            # Generate intelligent response
            try:
                response = await generate_browse_car_response(
                    message=message,
                    conversation_context={
                        "step": state.step,
                        "data": state.data
                    },
                    analysis_result=analysis,
                    available_brands=available_brands,
                    available_types=available_types,
                )
                return response
            except:
                return "I didn't quite catch that. Would you like to:\n1️⃣ Book a test drive\n2️⃣ Change search criteria"
        
        except BrowseCarAnalysisError:
            # Fallback
            message_lower = message.lower().strip()
            if "change" in message_lower or "3" in message_lower:
                conversation_manager.update_state(user_id, step="collecting_criteria")
                conversation_manager.update_data(user_id, selected_car=None, cars=None)
                return "Sure! Let's start a new search. What are you looking for?"
            if "emi" in message_lower or "loan" in message_lower or "2" in message_lower:
                # Transition to EMI flow
                return _transition_to_emi_flow(user_id, state)
            if "test drive" in message_lower or "1" in message_lower or "book" in message_lower:
                conversation_manager.update_state(user_id, step="test_drive_name")
                return "Perfect! Let's get your test drive booked! 🚗💨\n\nTo get started, could you please share your name?"
            return "I didn't quite catch that. Would you like to:\n1️⃣ Book a test drive\n2️⃣ Calculate EMI\n3️⃣ Change search criteria"
    
    elif state.step == "test_drive_name":
        # Use intelligent analysis to extract name
        try:
            analysis = await analyze_browse_car_message(
                message=message,
                conversation_context={
                    "step": state.step,
                    "data": state.data
                },
                available_brands=available_brands,
                available_types=available_types,
            )
            
            name = message.strip()
            if len(name) < 2:
                try:
                    response = await generate_browse_car_response(
                        message=message,
                        conversation_context={
                            "step": state.step,
                            "data": state.data
                        },
                        analysis_result=analysis,
                        available_brands=available_brands,
                        available_types=available_types,
                    )
                    return response
                except:
                    return "Please provide a valid name (at least 2 characters)."
            
            conversation_manager.update_data(user_id, test_drive_name=name)
            conversation_manager.update_state(user_id, step="test_drive_phone")
            
            try:
                response = await generate_browse_car_response(
                    message=message,
                    conversation_context={
                        "step": "test_drive_phone",
                        "data": {**state.data, "test_drive_name": name}
                    },
                    analysis_result=analysis,
                    available_brands=available_brands,
                    available_types=available_types,
                )
                return response
            except:
                return f"Nice to meet you, {name}! 👋\n\nCould you please share your phone number?"
        
        except BrowseCarAnalysisError:
            name = message.strip()
            if len(name) < 2:
                return "Please provide a valid name (at least 2 characters)."
            conversation_manager.update_data(user_id, test_drive_name=name)
            conversation_manager.update_state(user_id, step="test_drive_phone")
            return f"Nice to meet you, {name}! 👋\n\nCould you please share your phone number?"
    
    elif state.step == "test_drive_phone":
        # Use intelligent analysis
        try:
            analysis = await analyze_browse_car_message(
                message=message,
                conversation_context={
                    "step": state.step,
                    "data": state.data
                },
                available_brands=available_brands,
                available_types=available_types,
            )
            
            phone = re.sub(r'\D', '', message)  # Extract only digits
            if len(phone) < 10:
                try:
                    response = await generate_browse_car_response(
                        message=message,
                        conversation_context={
                            "step": state.step,
                            "data": state.data
                        },
                        analysis_result=analysis,
                        available_brands=available_brands,
                        available_types=available_types,
                    )
                    return response
                except:
                    return "Please provide a valid 10-digit phone number."
            
            conversation_manager.update_data(user_id, test_drive_phone=phone)
            conversation_manager.update_state(user_id, step="test_drive_dl")
            
            try:
                response = await generate_browse_car_response(
                    message=message,
                    conversation_context={
                        "step": "test_drive_dl",
                        "data": {**state.data, "test_drive_phone": phone}
                    },
                    analysis_result=analysis,
                    available_brands=available_brands,
                    available_types=available_types,
                )
                return response
            except:
                return "Got it! 📱\n\nDo you have a valid driving license? (Yes/No)"
        
        except BrowseCarAnalysisError:
            phone = re.sub(r'\D', '', message)
            if len(phone) < 10:
                return "Please provide a valid 10-digit phone number."
            conversation_manager.update_data(user_id, test_drive_phone=phone)
            conversation_manager.update_state(user_id, step="test_drive_dl")
            return "Got it! 📱\n\nDo you have a valid driving license? (Yes/No)"
    
    elif state.step == "test_drive_dl":
        # Use intelligent analysis
        try:
            analysis = await analyze_browse_car_message(
                message=message,
                conversation_context={
                    "step": state.step,
                    "data": state.data
                },
                available_brands=available_brands,
                available_types=available_types,
            )
            
            message_lower = message.lower().strip()
            has_dl = message_lower in ["yes", "y", "yeah", "sure", "i have", "have", "yes i have", "yes i do"]
            
            if not has_dl and message_lower not in ["no", "n", "don't", "dont", "i don't", "i dont"]:
                try:
                    response = await generate_browse_car_response(
                        message=message,
                        conversation_context={
                            "step": state.step,
                            "data": state.data
                        },
                        analysis_result=analysis,
                        available_brands=available_brands,
                        available_types=available_types,
                    )
                    return response
                except:
                    return "Please reply with 'Yes' or 'No' - do you have a valid driving license?"
            
            conversation_manager.update_data(user_id, test_drive_has_dl=has_dl)
            conversation_manager.update_state(user_id, step="test_drive_location")
            
            try:
                response = await generate_browse_car_response(
                    message=message,
                    conversation_context={
                        "step": "test_drive_location",
                        "data": {**state.data, "test_drive_has_dl": has_dl}
                    },
                    analysis_result=analysis,
                    available_brands=available_brands,
                    available_types=available_types,
                )
                return response
            except:
                if has_dl:
                    return "Perfect! ✅\n\nWhere would you prefer the test drive?\n\n1️⃣ Showroom visit\n2️⃣ Home pickup\n\nJust reply with '1' or '2'!"
                else:
                    return "No worries! You can still book a test drive, but you'll need to bring a valid license on the day. 📝\n\nWhere would you prefer the test drive?\n\n1️⃣ Showroom visit\n2️⃣ Home pickup\n\nJust reply with '1' or '2'!"
        
        except BrowseCarAnalysisError:
            message_lower = message.lower().strip()
            has_dl = message_lower in ["yes", "y", "yeah", "sure", "i have", "have"]
            if not has_dl and message_lower not in ["no", "n", "don't", "dont"]:
                return "Please reply with 'Yes' or 'No' - do you have a valid driving license?"
            conversation_manager.update_data(user_id, test_drive_has_dl=has_dl)
            conversation_manager.update_state(user_id, step="test_drive_location")
            if has_dl:
                return "Perfect! ✅\n\nWhere would you prefer the test drive?\n\n1️⃣ Showroom visit\n2️⃣ Home pickup\n\nJust reply with '1' or '2'!"
            else:
                return "No worries! You can still book a test drive, but you'll need to bring a valid license on the day. 📝\n\nWhere would you prefer the test drive?\n\n1️⃣ Showroom visit\n2️⃣ Home pickup\n\nJust reply with '1' or '2'!"
    
    elif state.step == "test_drive_location":
        # Collecting location preference
        message_lower = message.lower().strip()
        
        if "1" in message_lower or "showroom" in message_lower:
            location_type = "showroom"
        elif "2" in message_lower or "home" in message_lower or "pickup" in message_lower:
            location_type = "home"
        else:
            return (
                "Please choose:\n"
                "1️⃣ Showroom visit\n"
                "2️⃣ Home pickup"
            )
        
        # Get all test drive data
        test_drive_data = state.data
        selected_car = test_drive_data.get("selected_car")
        
        if not selected_car:
            return "I'm sorry, there was an error. Please start over."
        
        # Validate selected_car structure and ensure required fields exist
        if not isinstance(selected_car, dict):
            return "I'm sorry, there was an error with the car data. Please start over."
        
        car_id = selected_car.get("id")
        if not car_id:
            return "I'm sorry, there was an error. The car ID is missing. Please start over."
        
        # Create booking
        try:
            if not car_db:
                return "Database connection is not available. Please try again later."
            
            booking_id = await car_db.create_test_drive_booking(
                user_name=test_drive_data.get("test_drive_name"),
                phone_number=test_drive_data.get("test_drive_phone"),
                car_id=car_id,
                has_dl=test_drive_data.get("test_drive_has_dl", False),
                location_type=location_type
            )
            
            # Clear conversation state
            conversation_manager.clear_state(user_id)
            
            location_text = "at our showroom" if location_type == "showroom" else "with home pickup"
            dl_text = "with your driving license" if test_drive_data.get("test_drive_has_dl") else "and bring a valid driving license"
            
            year_str = f"({selected_car.get('year')})" if selected_car.get('year') else ""
            variant_str = f" {selected_car.get('variant')}" if selected_car.get('variant') else ""
            
            return (
                f"🎉 *Test Drive Booked Successfully!*\n\n"
                f"*Car:* {selected_car.get('brand', 'N/A')} {selected_car.get('model', 'N/A')}{variant_str} {year_str}\n"
                f"*Name:* {test_drive_data.get('test_drive_name')}\n"
                f"*Phone:* {test_drive_data.get('test_drive_phone')}\n"
                f"*Location:* {location_text}\n"
                f"*Booking ID:* #{booking_id}\n\n"
                f"Our team will contact you shortly to confirm the details {dl_text}. "
                f"We're excited to show you this amazing car! 🚗✨\n\n"
                f"Is there anything else I can help you with?"
            )
            
        except Exception as e:
            return f"I encountered an error booking your test drive. Please try again or contact us directly. Error: {str(e)}"
    
    return "I'm not sure how to help with that. Could you please rephrase?"

