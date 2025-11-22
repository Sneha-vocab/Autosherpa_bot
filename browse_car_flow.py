"""Browse Used Car Flow Handler.

This module uses a systematic, dynamic step router for handling the browse car flow.
All step handlers are registered with the router, which routes messages dynamically
based on the current step.
"""

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
from intent_service import generate_response, FlowRoutingError
from browse_car_analyzer import (
    analyze_browse_car_message,
    generate_browse_car_response,
    analyze_test_drive_details,
    validate_and_extract_field,
    BrowseCarAnalysisError,
)
from browse_car_flow_router import get_router, BrowseCarFlowError


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


async def handle_flexible_test_drive_collection(
    user_id: str,
    message: str,
    state: ConversationState,
    intent_result: Any
 ) -> str:
    """Flexible test drive collection handler that can extract multiple data points at once.
    
    Flow order: date -> time -> name -> phone -> DL -> location -> address -> confirmation
    Allows users to provide multiple pieces of data in one message.
    Asks for confirmation if LLM is uncertain.
    """
    current_step = state.step
    data = state.data
    
    # Special handling for name step - validate with LLM first
    if current_step == "test_drive_name" and message and message.strip():
        try:
            validation = await validate_and_extract_field(
                message=message,
                field_type="name",
                conversation_context={
                    "step": "test_drive_name",
                    "data": data
                }
            )
            
            print(f"🔵 [test_drive] Name validation: {validation}")
            
            if validation.get("needs_confirmation", False):
                confirmation_msg = validation.get("confirmation_message")
                if confirmation_msg:
                    return f"🤔 {confirmation_msg}\n\nPlease confirm or provide your name again."
                else:
                    return "I want to make sure I got your name correctly. Did you mean to provide your name? Please confirm or provide your name again."
            
            if validation.get("is_valid", False) and validation.get("extracted_value"):
                # Valid name extracted, save it
                extracted_name = validation.get("extracted_value")
                conversation_manager.update_data(user_id, test_drive_name=extracted_name)
                # Continue to next step
                updated_state = conversation_manager.get_state(user_id)
                return await handle_flexible_test_drive_collection(user_id, "", updated_state, intent_result)
            else:
                # Invalid name, ask again
                reason = validation.get("validation_reason", "")
                if reason:
                    return f"I didn't catch a valid name from your message. {reason}\n\nPlease provide your full name."
                else:
                    return "I didn't catch a valid name from your message. Please provide your full name (e.g., 'John Doe' or 'Kashyap')."
        except Exception as e:
            print(f"Error validating name: {e}")
            import traceback
            traceback.print_exc()
            # Fall through to general analysis
    
    # Special handling for address step - validate with LLM first
    if current_step == "test_drive_address" and message and message.strip():
        try:
            validation = await validate_and_extract_field(
                message=message,
                field_type="address",
                conversation_context={
                    "step": "test_drive_address",
                    "data": data
                }
            )
            
            print(f"🔵 [test_drive] Address validation: {validation}")
            
            if validation.get("needs_confirmation", False):
                confirmation_msg = validation.get("confirmation_message")
                if confirmation_msg:
                    return f"🤔 {confirmation_msg}\n\nPlease confirm or provide your complete address again."
                else:
                    return "I want to make sure I got your address correctly. Please confirm if this is your complete address, or provide it again with more details (street, area, city)."
            
            if validation.get("is_valid", False) and validation.get("extracted_value"):
                # Valid address extracted, save it
                extracted_address = validation.get("extracted_value")
                conversation_manager.update_data(user_id, test_drive_address=extracted_address)
                conversation_manager.update_state(user_id, step="test_drive_confirm")
                # Continue to confirmation
                updated_state = conversation_manager.get_state(user_id)
                return await handle_flexible_test_drive_collection(user_id, "", updated_state, intent_result)
            else:
                # Invalid address, ask again
                reason = validation.get("validation_reason", "")
                if reason:
                    return f"I need a complete address for home pickup. {reason}\n\nPlease provide your full address including street, area, and city."
                else:
                    return "I need a complete address for home pickup. Please provide your full address including street, area, and city (e.g., '123 Main Street, MG Road, Bangalore')."
        except Exception as e:
            print(f"Error validating address: {e}")
            import traceback
            traceback.print_exc()
            # Fall through to general analysis
    
    try:
        # Use the new analyzer to extract all possible data from the message
        analysis = await analyze_test_drive_details(
            message=message,
            conversation_context={
                "step": state.step,
                "data": state.data
            }
        )
        
        print(f"🔵 [test_drive] Analysis result: {analysis}")
        
        # Check if confirmation is needed
        if analysis.get("needs_confirmation", False):
            confirmation_msg = analysis.get("confirmation_message")
            if confirmation_msg:
                return f"🤔 {confirmation_msg}\n\nPlease confirm or provide the correct information."
            else:
                return "I want to make sure I understood correctly. Could you please confirm the details you provided?"
        
        # Extract what we can from the analysis
        extracted_date = analysis.get("extracted_date")
        extracted_time = analysis.get("extracted_time")
        extracted_name = analysis.get("extracted_name")
        extracted_phone = analysis.get("extracted_phone")
        extracted_has_dl = analysis.get("extracted_has_dl")
        extracted_location = analysis.get("extracted_location")
        
        # Update state with extracted data (only if not None)
        if extracted_date:
            conversation_manager.update_data(user_id, test_drive_date=extracted_date)
        if extracted_time:
            conversation_manager.update_data(user_id, test_drive_time=extracted_time)
        if extracted_name:
            conversation_manager.update_data(user_id, test_drive_name=extracted_name)
        if extracted_phone:
            conversation_manager.update_data(user_id, test_drive_phone=extracted_phone)
        if extracted_has_dl is not None:
            conversation_manager.update_data(user_id, test_drive_has_dl=extracted_has_dl)
        if extracted_location:
            conversation_manager.update_data(user_id, test_drive_location=extracted_location)
        
        # Get updated state
        updated_state = conversation_manager.get_state(user_id)
        data = updated_state.data
        
        # Check what we have and what's missing
        has_date = data.get("test_drive_date") is not None
        has_time = data.get("test_drive_time") is not None
        has_name = data.get("test_drive_name") is not None
        has_phone = data.get("test_drive_phone") is not None
        has_dl = data.get("test_drive_has_dl") is not None
        has_location = data.get("test_drive_location") is not None
        has_address = data.get("test_drive_address") is not None
        
        # Determine next step based on what's missing (in order: date -> time -> name -> phone -> DL -> location -> address)
        if not has_date:
            conversation_manager.update_state(user_id, step="test_drive_date")
            return "When would you like to schedule the test drive? Please provide a date (e.g., 'Today', 'Tomorrow', 'Friday', '15th January')."
        
        if not has_time:
            conversation_manager.update_state(user_id, step="test_drive_time")
            date_str = data.get("test_drive_date", "the selected date")
            return f"Great! You've selected {date_str}. What time would you prefer? (e.g., '5 pm', '2:30', 'morning', 'afternoon')"
        
        if not has_name:
            conversation_manager.update_state(user_id, step="test_drive_name")
            return "Perfect! Could you please share your name?"
        
        if not has_phone:
            conversation_manager.update_state(user_id, step="test_drive_phone")
            name = data.get("test_drive_name", "there")
            return f"Nice to meet you, {name}! 👋\n\nCould you please share your phone number?"
        
        if not has_dl:
            conversation_manager.update_state(user_id, step="test_drive_dl")
            return "Got it! 📱\n\nDo you have a valid driving license? (Yes/No)"
        
        # Check if user said NO to DL - apologize and cancel
        if has_dl and data.get("test_drive_has_dl") is False:
            # User doesn't have DL - apologize and cancel test drive
            conversation_manager.clear_state(user_id)
            return (
                "I apologize, but a valid driving license is required for test drives. 😔\n\n"
                "We want to ensure your safety and comply with regulations. "
                "Once you have a valid driving license, we'd be happy to help you book a test drive!\n\n"
                "Feel free to reach out anytime. Thank you for your understanding! 🙏"
            )
        
        if not has_location:
            conversation_manager.update_state(user_id, step="test_drive_location")
            dl_status = "Perfect! ✅" if data.get("test_drive_has_dl") else "No worries! You can still book a test drive, but you'll need to bring a valid license on the day. 📝"
            return f"{dl_status}\n\nWhere would you prefer the test drive?\n\n1️⃣ Showroom visit\n2️⃣ Home pickup\n\nJust reply with '1' or '2'!"
        
        # Check if location is "home" and address is not collected yet
        has_address = data.get("test_drive_address") is not None
        location_type = data.get("test_drive_location", "showroom")
        
        if location_type == "home" and not has_address:
            conversation_manager.update_state(user_id, step="test_drive_address")
            return "Great! For home pickup, we'll need your address. 📍\n\nPlease provide your complete address where you'd like the test drive vehicle to be delivered."
        
        # All data collected! Move to confirmation
        conversation_manager.update_state(user_id, step="test_drive_confirm")
        
        # Format confirmation message
        selected_car = data.get("selected_car", {})
        location_type = data.get("test_drive_location", "showroom")
        location_text = "Showroom visit" if location_type == "showroom" else "Home pickup"
        dl_status = "Yes, I have a driving license" if data.get("test_drive_has_dl") else "No, I'll bring it on the day"
        
        date_str = data.get("test_drive_date", "N/A")
        time_str = data.get("test_drive_time", "N/A")
        datetime_str = f"{date_str} at {time_str}" if time_str != "N/A" else date_str
        
        # Add address if home pickup
        address_text = ""
        if location_type == "home":
            address = data.get("test_drive_address", "N/A")
            address_text = f"• Address: {address}\n"
        
        year_str = f"({selected_car.get('year')})" if selected_car.get('year') else ""
        variant_str = f" {selected_car.get('variant')}" if selected_car.get('variant') else ""
        price_str = f"₹{selected_car.get('price', 0):,.0f}" if selected_car.get('price') else "Price on request"
        
        return (
            f"📋 *Please Confirm Your Test Drive Details*\n\n"
            f"*Car Selected:*\n"
            f"• {selected_car.get('brand', 'N/A')} {selected_car.get('model', 'N/A')}{variant_str} {year_str}\n"
            f"• Price: {price_str}\n\n"
            f"*Test Drive Details:*\n"
            f"• Date: {date_str}\n"
            f"• Time: {time_str}\n"
            f"• Name: {data.get('test_drive_name', 'N/A')}\n"
            f"• Phone: {data.get('test_drive_phone', 'N/A')}\n"
            f"• Location: {location_text}\n"
            f"{address_text}"
            f"• Driving License: {dl_status}\n\n"
            f"Please confirm if all details are correct:\n"
            f"✅ Reply 'Yes' or 'Confirm' to book the test drive\n"
            f"❌ Reply 'No' or 'Change' to modify any details"
        )
        
    except BrowseCarAnalysisError as e:
        print(f"Error in test drive analysis: {e}")
        # Fallback to simple extraction based on current step
        current_step = state.step
        data = state.data
        
        if current_step == "test_drive_date":
            if not data.get("test_drive_date"):
                conversation_manager.update_data(user_id, test_drive_date=message.strip())
                conversation_manager.update_state(user_id, step="test_drive_time")
                return f"Great! You've selected {message.strip()}. What time would you prefer? (e.g., '5 pm', '2:30', 'morning')"
            return "When would you like to schedule the test drive? Please provide a date."
        
        elif current_step == "test_drive_time":
            if not data.get("test_drive_time"):
                conversation_manager.update_data(user_id, test_drive_time=message.strip())
                conversation_manager.update_state(user_id, step="test_drive_name")
                return "Perfect! Could you please share your name?"
            return "What time would you prefer for the test drive?"
        
        elif current_step == "test_drive_name":
            if not data.get("test_drive_name"):
                conversation_manager.update_data(user_id, test_drive_name=message.strip())
                conversation_manager.update_state(user_id, step="test_drive_phone")
                return f"Nice to meet you, {message.strip()}! 👋\n\nCould you please share your phone number?"
            return "Could you please share your name?"
        
        elif current_step == "test_drive_phone":
            phone = re.sub(r'\D', '', message)
            if len(phone) >= 10:
                conversation_manager.update_data(user_id, test_drive_phone=phone[-10:])
                conversation_manager.update_state(user_id, step="test_drive_dl")
                return "Got it! 📱\n\nDo you have a valid driving license? (Yes/No)"
            return "Please provide a valid 10-digit phone number."
        
        elif current_step == "test_drive_dl":
            message_lower = message.lower().strip()
            has_dl = message_lower in ["yes", "y", "yeah", "sure", "i have", "have"]
            if has_dl:
                conversation_manager.update_data(user_id, test_drive_has_dl=has_dl)
                conversation_manager.update_state(user_id, step="test_drive_location")
                return "Perfect! ✅\n\nWhere would you prefer the test drive?\n\n1️⃣ Showroom visit\n2️⃣ Home pickup\n\nJust reply with '1' or '2'!"
            elif message_lower in ["no", "n", "don't", "dont", "i don't", "i dont"]:
                # User doesn't have DL - apologize and cancel test drive
                conversation_manager.clear_state(user_id)
                return (
                    "I apologize, but a valid driving license is required for test drives. 😔\n\n"
                    "We want to ensure your safety and comply with regulations. "
                    "Once you have a valid driving license, we'd be happy to help you book a test drive!\n\n"
                    "Feel free to reach out anytime. Thank you for your understanding! 🙏"
                )
            return "Please reply with 'Yes' or 'No' - do you have a valid driving license?"
        
        elif current_step == "test_drive_location":
            message_lower = message.lower().strip()
            if "1" in message_lower or "showroom" in message_lower:
                location_type = "showroom"
            elif "2" in message_lower or "home" in message_lower or "pickup" in message_lower:
                location_type = "home"
            else:
                return "Please choose:\n1️⃣ Showroom visit\n2️⃣ Home pickup"
            
            conversation_manager.update_data(user_id, test_drive_location=location_type)
            conversation_manager.update_state(user_id, step="test_drive_confirm")
            
            # Format confirmation
            selected_car = data.get("selected_car", {})
            location_text = "Showroom visit" if location_type == "showroom" else "Home pickup"
            dl_status = "Yes, I have a driving license" if data.get("test_drive_has_dl") else "No, I'll bring it on the day"
            
            date_str = data.get("test_drive_date", "N/A")
            time_str = data.get("test_drive_time", "N/A")
            
            year_str = f"({selected_car.get('year')})" if selected_car.get('year') else ""
            variant_str = f" {selected_car.get('variant')}" if selected_car.get('variant') else ""
            price_str = f"₹{selected_car.get('price', 0):,.0f}" if selected_car.get('price') else "Price on request"
            
            return (
                f"📋 *Please Confirm Your Test Drive Details*\n\n"
                f"*Car Selected:*\n"
                f"• {selected_car.get('brand', 'N/A')} {selected_car.get('model', 'N/A')}{variant_str} {year_str}\n"
                f"• Price: {price_str}\n\n"
                f"*Test Drive Details:*\n"
                f"• Date: {date_str}\n"
                f"• Time: {time_str}\n"
                f"• Name: {data.get('test_drive_name', 'N/A')}\n"
                f"• Phone: {data.get('test_drive_phone', 'N/A')}\n"
                f"• Location: {location_text}\n"
                f"• Driving License: {dl_status}\n\n"
                f"Please confirm if all details are correct:\n"
                f"✅ Reply 'Yes' or 'Confirm' to book the test drive\n"
                f"❌ Reply 'No' or 'Change' to modify any details"
            )
        
        return "I didn't quite catch that. Could you please provide the information again?"


async def handle_browse_car_flow(
    user_id: str,
    message: str,
    intent_result: Any
 ) -> str:
    """Handle the browse used car flow with intelligent message analysis."""
    print(f"🔵 [browse_car_flow] Handling message from {user_id}: '{message}'")
    state = conversation_manager.get_state(user_id)
    if state:
        print(f"🔵 [browse_car_flow] Current state: flow={state.flow_name}, step={state.step}, data={state.data}")
    else:
        print(f"🔵 [browse_car_flow] No existing state, will initialize")
    
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
    # IMPORTANT: Don't re-initialize if user is already in browse_car flow (even if step is car_selected)
    if state is None or (state.flow_name != "browse_car" and state.flow_name is not None):
        print(f"🔵 [browse_car_flow] Initializing new flow - state is None: {state is None}, flow_name: {state.flow_name if state else 'None'}")
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
            
            # Check if all criteria are collected - if yes, show cars immediately
            if brand and budget and car_type:
                # All criteria collected, search and show cars
                if budget and isinstance(budget, tuple) and len(budget) == 2:
                    min_price, max_price = budget
                else:
                    min_price, max_price = None, None
                
                try:
                    print(f"🔍 [browse_car_flow] Initial search: brand={brand}, type={car_type}, min_price={min_price}, max_price={max_price}")
                    cars = await car_db.search_cars(
                        brand=brand,
                        car_type=car_type,
                        min_price=min_price,
                        max_price=max_price,
                        limit=10
                    )
                    
                    if not cars:
                        print(f"⚠️ [browse_car_flow] No cars found for initial criteria")
                        return (
                            "I couldn't find any cars matching your exact criteria. 😔\n\n"
                            "Would you like to:\n"
                            "1. Try a different brand\n"
                            "2. Adjust your budget\n"
                            "3. Change the car type\n\n"
                            "Just let me know what you'd like to change!"
                        )
                    
                    # Store cars and move to showing_cars step
                    conversation_manager.update_data(user_id, cars=[c.to_dict() for c in cars])
                    conversation_manager.update_state(user_id, step="showing_cars")
                    
                    print(f"✅ [browse_car_flow] Found {len(cars)} cars, showing to user")
                    return format_car_list(cars)
                    
                except Exception as e:
                    print(f"Error searching cars during initialization: {e}")
                    import traceback
                    traceback.print_exc()
                    # Fall through to ask for missing criteria
            
            # Not all criteria collected, ask for what's missing
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
            
            # Check if all criteria are collected - if yes, show cars immediately
            if brand and budget and car_type:
                # All criteria collected, search and show cars
                if budget and isinstance(budget, tuple) and len(budget) == 2:
                    min_price, max_price = budget
                else:
                    min_price, max_price = None, None
                
                try:
                    print(f"🔍 [browse_car_flow] Initial search (fallback): brand={brand}, type={car_type}, min_price={min_price}, max_price={max_price}")
                    cars = await car_db.search_cars(
                        brand=brand,
                        car_type=car_type,
                        min_price=min_price,
                        max_price=max_price,
                        limit=10
                    )
                    
                    if cars:
                        conversation_manager.update_data(user_id, cars=[c.to_dict() for c in cars])
                        conversation_manager.update_state(user_id, step="showing_cars")
                        print(f"✅ [browse_car_flow] Found {len(cars)} cars (fallback), showing to user")
                        return format_car_list(cars)
                except Exception as e:
                    print(f"Error searching cars (fallback): {e}")
            
            # Not all criteria collected, ask for what's missing
            if not brand:
                return "Great! I'd be happy to help you find the perfect used car! 🚗\n\nWhich brand are you interested in?"
            elif not budget:
                return f"Perfect! I see you're interested in {brand} cars. That's a great choice! 👍\n\nWhat's your budget range?"
            elif not car_type:
                return f"Excellent! So you're looking for a {brand} car within your budget. 🎯\n\nWhat type of car are you looking for?"
    
    # Continue based on current step - use dynamic router
    state = conversation_manager.get_state(user_id)
    
    # Safety check: state should exist after initialization
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
    
    # All step handling is now done through the router
    # The router will route to the appropriate handler based on state.step
    # This replaces all the nested if/elif statements
    
    # Route using dynamic router (commented out until handlers are fully extracted)
    # try:
    #     router = get_router()
    #     return await router.route(
    #         user_id,
    #         message,
    #         state,
    #         intent_result,
    #         available_brands=available_brands,
    #         available_types=available_types
    #     )
    # except FlowRoutingError as e:
    #     # Fallback to old logic if router doesn't have handler
    #     print(f"⚠️ Router doesn't have handler for step '{state.step}', using fallback")
    #     # Continue with old if/elif logic as fallback
    #     pass
    
    # Old if/elif chain (will be replaced by router once all handlers are extracted)
    if state.step == "collecting_criteria":
        # Handle confirmation responses first
        message_lower = message.lower().strip()
        
        # Check if we're awaiting confirmation
        if state.data.get("awaiting_confirmation", False):
            # User is responding to a clarification question
            # Understand if user is agreeing or disagreeing
            message_lower = message.lower().strip()
            
            # Quick check for common confirmation patterns
            is_confirming = message_lower in ["yes", "y", "yeah", "sure", "correct", "confirm", "ok", "okay", "right", "that's right", "thats right", "yes please", "yes that's right"]
            is_rejecting = message_lower in ["no", "n", "nope", "wrong", "incorrect", "not", "that's wrong", "thats wrong", "no that's wrong"]
            
            if is_confirming:
                # User confirmed - save the pending values
                pending_brand = state.data.get("pending_brand")
                pending_budget = state.data.get("pending_budget")
                pending_car_type = state.data.get("pending_car_type")
                
                print(f"🔵 [browse_car_flow] User confirmed! Pending values: brand={pending_brand}, budget={pending_budget}, car_type={pending_car_type}")
                
                # Update with confirmed values - use pending values if they exist, otherwise keep existing
                brand = pending_brand if pending_brand is not None else state.data.get("brand")
                budget = pending_budget if pending_budget is not None else state.data.get("budget")
                car_type = pending_car_type if pending_car_type is not None else state.data.get("car_type")
                
                print(f"🔵 [browse_car_flow] Saving confirmed values: brand={brand}, budget={budget}, car_type={car_type}")
                
                conversation_manager.update_data(
                    user_id,
                    brand=brand,
                    budget=budget,
                    car_type=car_type,
                    pending_brand=None,
                    pending_budget=None,
                    pending_car_type=None,
                    awaiting_confirmation=False
                )
                
                print(f"🔵 [browse_car_flow] Confirmed values saved: brand={brand}, budget={budget}, car_type={car_type}")
                
                # Check if all criteria are now collected
                if brand and budget and car_type:
                    # All criteria collected, search and show cars
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
                        
                        if cars:
                            conversation_manager.update_data(user_id, cars=[c.to_dict() for c in cars])
                            conversation_manager.update_state(user_id, step="showing_cars")
                            return format_car_list(cars)
                        else:
                            return (
                                "I couldn't find any cars matching your criteria. 😔\n\n"
                                "Would you like to:\n"
                                "1. Try a different brand\n"
                                "2. Adjust your budget\n"
                                "3. Change the car type\n\n"
                                "Just let me know what you'd like to change!"
                            )
                    except Exception as e:
                        print(f"Error searching cars after confirmation: {e}")
                        return "I encountered an issue searching for cars. Please try again."
                else:
                    # Still missing criteria, ask for what's missing
                    if not brand:
                        return "Great! Which brand are you interested in?"
                    elif not budget:
                        return f"Perfect! I see you're interested in {brand} cars. What's your budget range?"
                    elif not car_type:
                        return f"Excellent! So you're looking for a {brand} car within your budget. What type of car are you looking for?"
            elif message_lower in ["no", "n", "nope", "wrong", "incorrect"]:
                # User said the extracted value is wrong - clear pending and ask again
                conversation_manager.update_data(
                    user_id,
                    pending_brand=None,
                    pending_budget=None,
                    pending_car_type=None,
                    awaiting_confirmation=False
                )
                
                # Ask for the correct value based on what was pending
                if state.data.get("pending_car_type"):
                    return "No problem! What type of car are you looking for? (e.g., Hatchback, Sedan, SUV)"
                elif state.data.get("pending_brand"):
                    return "No problem! Which brand are you interested in?"
                elif state.data.get("pending_budget"):
                    return "No problem! What's your budget range?"
                else:
                    return "I understand. Could you please provide the correct information?"
            
            else:
                # User provided an ambiguous response - use LLM to understand intent
                print(f"🔵 [browse_car_flow] Ambiguous confirmation response, analyzing with LLM: '{message}'")
                try:
                    # Re-analyze the message to understand if it's confirmation or new input
                    confirmation_analysis = await analyze_browse_car_message(
                        message=message,
                        conversation_context={
                            "step": state.step,
                            "data": state.data
                        },
                        available_brands=available_brands,
                        available_types=available_types,
                    )
                    
                    user_intent = confirmation_analysis.get("user_intent", "").lower()
                    
                    # Check if user is providing new information (brand, type, budget)
                    if "providing_brand" in user_intent or confirmation_analysis.get("extracted_brand"):
                        # User provided a new brand - clear confirmation and process normally
                        conversation_manager.update_data(
                            user_id,
                            pending_brand=None,
                            pending_budget=None,
                            pending_car_type=None,
                            awaiting_confirmation=False
                        )
                        # Fall through to normal processing
                    elif "providing_type" in user_intent or confirmation_analysis.get("extracted_type"):
                        # User provided a new car type - clear confirmation and process normally
                        conversation_manager.update_data(
                            user_id,
                            pending_brand=None,
                            pending_budget=None,
                            pending_car_type=None,
                            awaiting_confirmation=False
                        )
                        # Fall through to normal processing
                    elif "confirm" in user_intent or "yes" in message_lower or "correct" in message_lower:
                        # Treat as confirmation
                        pending_brand = state.data.get("pending_brand")
                        pending_budget = state.data.get("pending_budget")
                        pending_car_type = state.data.get("pending_car_type")
                        
                        brand = pending_brand if pending_brand is not None else state.data.get("brand")
                        budget = pending_budget if pending_budget is not None else state.data.get("budget")
                        car_type = pending_car_type if pending_car_type is not None else state.data.get("car_type")
                        
                        conversation_manager.update_data(
                            user_id,
                            brand=brand,
                            budget=budget,
                            car_type=car_type,
                            pending_brand=None,
                            pending_budget=None,
                            pending_car_type=None,
                            awaiting_confirmation=False
                        )
                        # Continue to check what's missing (will be handled below)
                    else:
                        # Unclear - ask for clarification
                        return "I want to make sure I understand correctly. Did you mean to confirm the suggestion, or would you like to provide different information?"
                except Exception as e:
                    print(f"Error analyzing confirmation response: {e}")
                    import traceback
                    traceback.print_exc()
                    # Fall through to normal processing
                    conversation_manager.update_data(
                        user_id,
                        pending_brand=None,
                        pending_budget=None,
                        pending_car_type=None,
                        awaiting_confirmation=False
                    )
        
        # Handle "no" response - skip to showing cars if all criteria already collected
        if message_lower in ["no", "n", "nope", "skip"]:
            # Check if we have all criteria
            brand = state.data.get("brand")
            budget = state.data.get("budget")
            car_type = state.data.get("car_type")
            
            if brand and budget and car_type:
                # All criteria collected, show cars
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
                    
                    if cars:
                        conversation_manager.update_data(user_id, cars=[c.to_dict() for c in cars])
                        conversation_manager.update_state(user_id, step="showing_cars")
                        return format_car_list(cars)
                    else:
                        return (
                            "I couldn't find any cars matching your criteria. 😔\n\n"
                            "Would you like to:\n"
                            "1. Try a different brand\n"
                            "2. Adjust your budget\n"
                            "3. Change the car type\n\n"
                            "Just let me know what you'd like to change!"
                        )
                except Exception as e:
                    print(f"Error searching cars: {e}")
                    return "I encountered an issue searching for cars. Please try again."
            else:
                # Missing criteria, ask for what's missing
                if not brand:
                    return "Which brand are you interested in?"
                elif not budget:
                    return "What's your budget range?"
                elif not car_type:
                    return "What type of car are you looking for?"
        
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
            
            # Check if clarification is needed BEFORE updating criteria
            needs_clarification = analysis.get("needs_clarification", False)
            clarification_question = analysis.get("clarification_question")
            
            if needs_clarification and clarification_question:
                # Store the extracted values temporarily for confirmation
                # We'll save them after user confirms
                extracted_brand = analysis.get("extracted_brand")
                extracted_budget = analysis.get("extracted_budget")
                extracted_type = analysis.get("extracted_type")
                
                # If extracted values are None, try to extract from clarification question
                # Example: "Did you mean 'Maruti'?" → extract "Maruti"
                import re
                if extracted_brand is None:
                    # Try to extract brand from clarification question
                    brand_match = re.search(r"['\"]([^'\"]+)['\"]", clarification_question)
                    if brand_match:
                        suggested_value = brand_match.group(1)
                        # Check if it's a valid brand
                        if suggested_value in available_brands:
                            extracted_brand = suggested_value
                            print(f"🔵 [browse_car_flow] Extracted brand '{extracted_brand}' from clarification question")
                
                if extracted_type is None:
                    # Try to extract car type from clarification question
                    type_match = re.search(r"['\"]([^'\"]+)['\"]", clarification_question)
                    if type_match:
                        suggested_value = type_match.group(1)
                        # Check if it's a valid car type
                        if suggested_value in available_types:
                            extracted_type = suggested_value
                            print(f"🔵 [browse_car_flow] Extracted car type '{extracted_type}' from clarification question")
                
                print(f"🔵 [browse_car_flow] Storing pending values for confirmation: brand={extracted_brand}, budget={extracted_budget}, car_type={extracted_type}")
                
                # Store pending values in state for confirmation
                # Only update pending values for fields that were actually extracted (not None)
                update_data = {"awaiting_confirmation": True}
                if extracted_brand is not None:
                    update_data["pending_brand"] = extracted_brand
                if extracted_budget is not None:
                    update_data["pending_budget"] = extracted_budget
                if extracted_type is not None:
                    update_data["pending_car_type"] = extracted_type
                
                conversation_manager.update_data(user_id, **update_data)
                
                print(f"🔵 [browse_car_flow] Needs clarification: {clarification_question}")
                print(f"🔵 [browse_car_flow] Stored pending values: {update_data}")
                return f"🤔 {clarification_question}"
            
            # No clarification needed, proceed with extraction
            # Update criteria based on analysis
            brand = analysis.get("extracted_brand") or state.data.get("brand")
            budget = analysis.get("extracted_budget") or state.data.get("budget")
            car_type = analysis.get("extracted_type") or state.data.get("car_type")
            
            # Clear any pending confirmation flags
            conversation_manager.update_data(
                user_id,
                pending_brand=None,
                pending_budget=None,
                pending_car_type=None,
                awaiting_confirmation=False
            )
            
            print(f"🔵 [browse_car_flow] Extracted: brand={brand}, budget={budget}, car_type={car_type}")
            
            # Handle special intents
            user_intent = analysis.get("user_intent", "")
            print(f"🔵 [browse_car_flow] User intent: {user_intent}")
            
            if "changing_criteria" in user_intent.lower() or "change" in message.lower():
                # User wants to change criteria - update with NEW extracted values
                # Don't clear everything, use the newly extracted values from analysis
                print(f"🔵 [browse_car_flow] User changing criteria, updating with: brand={brand}, budget={budget}, car_type={car_type}")
                
                # Update state with newly extracted values (these may be None if not provided)
                conversation_manager.update_state(user_id, step="collecting_criteria")
                conversation_manager.update_data(
                    user_id,
                    brand=brand,  # Use extracted brand (could be None)
                    budget=budget,  # Use extracted budget (could be None)
                    car_type=car_type  # Use extracted car_type (could be None)
                )
                
                # Check if all criteria are now present after update
                updated_state = conversation_manager.get_state(user_id)
                final_brand = updated_state.data.get("brand")
                final_budget = updated_state.data.get("budget")
                final_car_type = updated_state.data.get("car_type")
                
                if final_brand and final_budget and final_car_type:
                    # All criteria collected, search and show cars immediately
                    if final_budget and isinstance(final_budget, tuple) and len(final_budget) == 2:
                        min_price, max_price = final_budget
                    else:
                        min_price, max_price = None, None
                    
                    try:
                        print(f"🔍 [browse_car_flow] All criteria present after change, searching: brand={final_brand}, type={final_car_type}, min_price={min_price}, max_price={max_price}")
                        cars = await car_db.search_cars(
                            brand=final_brand,
                            car_type=final_car_type,
                            min_price=min_price,
                            max_price=max_price,
                            limit=10
                        )
                        
                        if not cars:
                            print(f"⚠️ [browse_car_flow] No cars found after criteria change")
                            return (
                                "I couldn't find any cars matching your updated criteria. 😔\n\n"
                                "Would you like to:\n"
                                "1. Try a different brand\n"
                                "2. Adjust your budget\n"
                                "3. Change the car type\n\n"
                                "Just let me know what you'd like to change!"
                            )
                        
                        # Store cars and move to showing_cars step
                        conversation_manager.update_data(user_id, cars=[c.to_dict() for c in cars])
                        conversation_manager.update_state(user_id, step="showing_cars")
                        
                        print(f"✅ [browse_car_flow] Found {len(cars)} cars after criteria change, showing to user")
                        return format_car_list(cars)
                        
                    except Exception as e:
                        print(f"Error searching cars after criteria change: {e}")
                        import traceback
                        traceback.print_exc()
                        # Fall through to ask for missing criteria
                
                # Not all criteria present, ask for what's missing
                if not final_brand:
                    return "No problem! Let's update your search. Which brand are you interested in?"
                elif not final_budget:
                    return f"Got it! You're looking for {final_brand} cars. What's your budget range?"
                elif not final_car_type:
                    return f"Perfect! So {final_brand} within your budget. What type of car are you looking for?"
            
            # Update state with extracted information FIRST
            conversation_manager.update_data(
                user_id,
                brand=brand,
                budget=budget,
                car_type=car_type
            )
            
            print(f"🔵 [browse_car_flow] After update - brand={brand}, budget={budget}, car_type={car_type}")
            
            # Check what's missing and use LLM to generate natural response
            if not brand:
                # Brand is missing - use LLM to generate natural response
                try:
                    response = await generate_browse_car_response(
                        message=message,
                        conversation_context={
                            "step": "collecting_criteria",
                            "data": {"brand": None, "budget": budget, "car_type": car_type}
                        },
                        analysis_result=analysis,
                        available_brands=available_brands,
                        available_types=available_types,
                    )
                    return response
                except Exception as e:
                    print(f"Error generating response: {e}")
                    brands_list = ", ".join(available_brands[:5]) if available_brands else ""
                    if brands_list:
                        return f"Great! I see you're looking for a {car_type if car_type else 'car'}. Which brand are you interested in? (e.g., {brands_list})"
                    else:
                        return f"Great! I see you're looking for a {car_type if car_type else 'car'}. Which brand are you interested in?"
            
            elif not budget:
                # Budget is missing - use LLM to generate natural response
                try:
                    response = await generate_browse_car_response(
                        message=message,
                        conversation_context={
                            "step": "collecting_criteria",
                            "data": {"brand": brand, "budget": None, "car_type": car_type}
                        },
                        analysis_result=analysis,
                        available_brands=available_brands,
                        available_types=available_types,
                    )
                    return response
                except Exception as e:
                    print(f"Error generating response: {e}")
                    brand_text = brand if brand else "a car"
                    car_type_text = f" {car_type}" if car_type else ""
                    return f"Perfect! I see you're interested in {brand_text}{car_type_text}. What's your budget range? (e.g., '5-10 lakh', 'under 8 lakh')"
            
            elif not car_type:
                # Car type is missing - use LLM to generate natural response
                try:
                    response = await generate_browse_car_response(
                        message=message,
                        conversation_context={
                            "step": "collecting_criteria",
                            "data": {"brand": brand, "budget": budget, "car_type": None}
                        },
                        analysis_result=analysis,
                        available_brands=available_brands,
                        available_types=available_types,
                    )
                    return response
                except Exception as e:
                    print(f"Error generating response: {e}")
                    brand_text = brand if brand else "a car"
                    budget_text = ""
                    if budget and isinstance(budget, tuple) and len(budget) == 2:
                        min_price, max_price = budget
                        if min_price:
                            budget_text = f" within ₹{min_price/100000:.1f}-{max_price/100000:.1f} lakh"
                        else:
                            budget_text = f" under ₹{max_price/100000:.1f} lakh"
                    
                    types_list = ", ".join(available_types) if available_types else ""
                    if types_list:
                        return f"Excellent! So you're looking for {brand_text}{budget_text}. What type of car are you looking for? (e.g., {types_list})"
                    else:
                        return f"Excellent! So you're looking for {brand_text}{budget_text}. What type of car are you looking for?"
            
            else:
                # All criteria collected, search for cars immediately
                # Safely unpack budget with type validation
                if budget and isinstance(budget, tuple) and len(budget) == 2:
                    min_price, max_price = budget
                else:
                    min_price, max_price = None, None
                
                # Update state with all collected criteria
                conversation_manager.update_data(
                    user_id,
                    brand=brand,
                    budget=budget,
                    car_type=car_type
                )
                
                try:
                    print(f"🔍 [browse_car_flow] Searching cars: brand={brand}, type={car_type}, min_price={min_price}, max_price={max_price}")
                    cars = await car_db.search_cars(
                        brand=brand,
                        car_type=car_type,
                        min_price=min_price,
                        max_price=max_price,
                        limit=10
                    )
                    
                    if not cars:
                        print(f"⚠️ [browse_car_flow] No cars found for criteria")
                        return (
                            "I couldn't find any cars matching your exact criteria. 😔\n\n"
                            "Would you like to:\n"
                            "1. Try a different brand\n"
                            "2. Adjust your budget\n"
                            "3. Change the car type\n\n"
                            "Just let me know what you'd like to change!"
                        )
                    
                    # Store cars in state and move to showing_cars step
                    conversation_manager.update_data(user_id, cars=[c.to_dict() for c in cars])
                    conversation_manager.update_state(user_id, step="showing_cars")
                    
                    print(f"✅ [browse_car_flow] Found {len(cars)} cars, showing to user")
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
            
            # Check if user wants to change criteria - but ONLY if they explicitly say so
            # Don't reset if they just said a number (they're selecting a car)
            is_selecting_car = message_lower.strip().isdigit() and 1 <= int(message_lower.strip()) <= 10
            
            # Only reset if user explicitly wants to change AND they're not selecting a car
            wants_to_change = (
                ("changing_criteria" in user_intent and not is_selecting_car) or
                (message_lower in ["change", "modify", "different", "new search", "start over"]) or
                ("change" in message_lower and "criteria" in message_lower) or
                ("modify" in message_lower and "search" in message_lower)
            )
            
            if wants_to_change and not is_selecting_car:
                print(f"🔵 [browse_car_flow] User wants to change criteria in showing_cars step")
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
                        
                        # Don't use LLM for car selection confirmation - use static message to avoid confusion
                        # The LLM might misinterpret "1" as something else
                        brand_name = selected_car.get('brand', 'Unknown')
                        model_name = selected_car.get('model', 'Unknown')
                        variant = selected_car.get('variant', '')
                        year = selected_car.get('year', '')
                        
                        variant_str = f" {variant}" if variant else ""
                        year_str = f" ({year})" if year else ""
                        
                        return (
                            f"Excellent choice! 🎉 You've selected the *{brand_name} {model_name}{variant_str}{year_str}*\n\n"
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
        print(f"🔵 [browse_car_flow] In car_selected step, message: '{message}', state data: {state.data}")
        
        # FIRST: Check for date/time intent BEFORE other analysis (priority check)
        if intent_result:
            intent_lower = intent_result.intent.lower()
            has_date_entity = intent_result.entities and intent_result.entities.get("date") is not None
            has_time_entity = intent_result.entities and intent_result.entities.get("time") is not None
            
            # Check if this is a date/time related intent
            is_date_time_intent = (
                "provide_date" in intent_lower or 
                "provide_time" in intent_lower or
                "date" in intent_lower or
                has_date_entity or
                has_time_entity
            )
            
            if is_date_time_intent:
                print(f"🔵 [browse_car_flow] Date/time intent detected in car_selected: intent={intent_lower}, has_date={has_date_entity}, has_time={has_time_entity}")
                # Check if already in test drive flow (has test drive data)
                if state.data.get("test_drive_name"):
                    # Already started test drive, route to appropriate step
                    print(f"🔵 [browse_car_flow] Already in test drive flow, routing to next step")
                    # This will be handled by the flexible handler when we move to test_drive_date step
                    conversation_manager.update_state(user_id, step="test_drive_date")
                    updated_state = conversation_manager.get_state(user_id)
                    return await handle_flexible_test_drive_collection(user_id, message, updated_state, intent_result)
                else:
                    # Not in test drive flow yet - they want to book test drive
                    # Start with test_drive_date step and use flexible handler to extract date/time
                    print(f"🔵 [browse_car_flow] Starting test drive booking with date/time extraction")
                    conversation_manager.update_state(user_id, step="test_drive_date")
                    # Get updated state and use the flexible handler to extract date/time from the message
                    updated_state = conversation_manager.get_state(user_id)
                    return await handle_flexible_test_drive_collection(user_id, message, updated_state, intent_result)
        
        # Use intelligent analysis for other cases
        try:
            message_lower = message.lower().strip()
            
            # CRITICAL: In car_selected step, if user says "1", "2", or "3", they're choosing an option
            # Don't analyze with LLM - handle directly
            if message_lower in ["1", "2", "3", "1️⃣", "2️⃣", "3️⃣"]:
                print(f"🔵 [browse_car_flow] User chose option {message_lower} in car_selected step")
                
                if message_lower in ["1", "1️⃣"]:
                    # Option 1: Book test drive
                    conversation_manager.update_state(user_id, step="test_drive_name")
                    return "Perfect! Let's get your test drive booked! 🚗💨\n\nTo get started, could you please share your name?"
                elif message_lower in ["2", "2️⃣"]:
                    # Option 2: Calculate EMI
                    return _transition_to_emi_flow(user_id, state)
                elif message_lower in ["3", "3️⃣"]:
                    # Option 3: Change search criteria
                    conversation_manager.update_state(user_id, step="collecting_criteria")
                    conversation_manager.update_data(user_id, selected_car=None, cars=None)
                    return "Sure! Let's start a new search. What are you looking for?"
            
            # For other messages, use LLM analysis
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
            
            # Check if user wants to change criteria - but ONLY if they explicitly say so
            # Don't reset if they just said "1" (which could be selecting car or choosing option 1)
            wants_to_change = (
                ("changing_criteria" in user_intent and message_lower not in ["1", "2", "3"]) or 
                (message_lower in ["change", "modify", "different", "new search", "start over"]) or
                ("change" in message_lower and "criteria" in message_lower) or
                ("modify" in message_lower and "search" in message_lower)
            )
            
            if wants_to_change:
                print(f"🔵 [browse_car_flow] User wants to change criteria, resetting to collecting_criteria")
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
            
            # Check if user wants to calculate EMI - be specific about option 2
            is_option_2 = message_lower.strip() == "2" or message_lower.strip() == "2️⃣"
            wants_emi = (
                is_option_2 or
                "emi" in message_lower or 
                "loan" in message_lower or 
                "finance" in message_lower or 
                "installment" in message_lower
            )
            
            if wants_emi:
                # User wants to calculate EMI
                # Store selected car and let main.py handle routing
                return _transition_to_emi_flow(user_id, state)
            
            # Check if user wants to book test drive
            # Be careful: "1" could be in other contexts, so check it's exactly "1" or option 1
            is_option_1 = message_lower.strip() == "1" or message_lower.strip() == "1️⃣"
            wants_test_drive = (
                "booking_test_drive" in user_intent or 
                "test drive" in message_lower or 
                is_option_1 or
                ("book" in message_lower and "test" in message_lower)
            )
            
            if wants_test_drive:
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
                conversation_manager.update_state(user_id, step="test_drive_date")
                return "Perfect! Let's get your test drive booked! 🚗💨\n\nWhen would you like to schedule the test drive? Please provide a date (e.g., 'Today', 'Tomorrow', 'Friday', '15th January')."
            return "I didn't quite catch that. Would you like to:\n1️⃣ Book a test drive\n2️⃣ Calculate EMI\n3️⃣ Change search criteria"
    
    # New flexible test drive flow - handles multiple data points and confirmation
    # This should come BEFORE the old individual step handlers
    elif state.step in ["test_drive_date", "test_drive_time", "test_drive_name", "test_drive_phone", "test_drive_dl", "test_drive_location", "test_drive_address"]:
        return await handle_flexible_test_drive_collection(user_id, message, state, intent_result)
    
    elif state.step == "test_drive_name":
        # OLD HANDLER - kept for backward compatibility but should not be reached
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
            
            if has_dl:
                return "Perfect! ✅\n\nWhere would you prefer the test drive?\n\n1️⃣ Showroom visit\n2️⃣ Home pickup\n\nJust reply with '1' or '2'!"
            else:
                return "No worries! You can still book a test drive, but you'll need to bring a valid license on the day. 📝\n\nWhere would you prefer the test drive?\n\n1️⃣ Showroom visit\n2️⃣ Home pickup\n\nJust reply with '1' or '2'!"
        
        except BrowseCarAnalysisError:
            message_lower = message.lower().strip()
            has_dl = message_lower in ["yes", "y", "yeah", "sure", "i have", "have"]
            if not has_dl and message_lower not in ["no", "n", "don't", "dont"]:
                return "Please reply with 'Yes' or 'No' - do you have a valid driving license?"
            if has_dl:
                conversation_manager.update_data(user_id, test_drive_has_dl=has_dl)
                conversation_manager.update_state(user_id, step="test_drive_location")
                return "Perfect! ✅\n\nWhere would you prefer the test drive?\n\n1️⃣ Showroom visit\n2️⃣ Home pickup\n\nJust reply with '1' or '2'!"
            elif message_lower in ["no", "n", "don't", "dont", "i don't", "i dont"]:
                # User doesn't have DL - apologize and cancel test drive
                conversation_manager.clear_state(user_id)
                return (
                    "I apologize, but a valid driving license is required for test drives. 😔\n\n"
                    "We want to ensure your safety and comply with regulations. "
                    "Once you have a valid driving license, we'd be happy to help you book a test drive!\n\n"
                    "Feel free to reach out anytime. Thank you for your understanding! 🙏"
                )
            return "Please reply with 'Yes' or 'No' - do you have a valid driving license?"
    
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
        
        # Store location
        conversation_manager.update_data(user_id, test_drive_location=location_type)
        
        # If home pickup, ask for address; otherwise move to confirmation
        if location_type == "home":
            conversation_manager.update_state(user_id, step="test_drive_address")
            return "Great! For home pickup, we'll need your address. 📍\n\nPlease provide your complete address where you'd like the test drive vehicle to be delivered."
        else:
            # Showroom visit - move to confirmation
            conversation_manager.update_state(user_id, step="test_drive_confirm")
            # Get updated state and format confirmation
            updated_state = conversation_manager.get_state(user_id)
            return await handle_flexible_test_drive_collection(user_id, "", updated_state, intent_result)
    
    elif state.step == "test_drive_address":
        # Collecting address for home pickup
        address = message.strip()
        if len(address) < 10:
            return "Please provide a complete address (at least 10 characters). This helps us ensure accurate delivery."
        
        conversation_manager.update_data(user_id, test_drive_address=address)
        conversation_manager.update_state(user_id, step="test_drive_confirm")
        
        # Move to confirmation
        updated_state = conversation_manager.get_state(user_id)
        return await handle_flexible_test_drive_collection(user_id, "", updated_state, intent_result)
    
    elif state.step == "test_drive_datetime":
        # Collecting date and time
        # Extract date/time from message using analysis
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
            
            # Extract date/time from entities if available
            datetime_str = message.strip()
            if intent_result and intent_result.entities:
                date = intent_result.entities.get("date")
                time = intent_result.entities.get("time")
                if date and time:
                    datetime_str = f"{date} at {time}"
            
            # Store date/time
            conversation_manager.update_data(user_id, test_drive_datetime=datetime_str)
            
            # Get all test drive data for confirmation
            test_drive_data = state.data
            selected_car = test_drive_data.get("selected_car")
            
            if not selected_car:
                return "I'm sorry, there was an error. Please start over."
            
            # Validate selected_car structure
            if not isinstance(selected_car, dict):
                return "I'm sorry, there was an error with the car data. Please start over."
            
            # Move to confirmation step
            conversation_manager.update_state(user_id, step="test_drive_confirm")
            
            # Format confirmation message
            location_type = test_drive_data.get("test_drive_location", "showroom")
            location_text = "Showroom visit" if location_type == "showroom" else "Home pickup"
            dl_status = "Yes, I have a driving license" if test_drive_data.get("test_drive_has_dl") else "No, I'll bring it on the day"
            
            year_str = f"({selected_car.get('year')})" if selected_car.get('year') else ""
            variant_str = f" {selected_car.get('variant')}" if selected_car.get('variant') else ""
            price_str = f"₹{selected_car.get('price', 0):,.0f}" if selected_car.get('price') else "Price on request"
            
            confirmation_message = (
                f"📋 *Please Confirm Your Test Drive Details*\n\n"
                f"*Car Selected:*\n"
                f"• {selected_car.get('brand', 'N/A')} {selected_car.get('model', 'N/A')}{variant_str} {year_str}\n"
                f"• Price: {price_str}\n\n"
                f"*Test Drive Details:*\n"
                f"• Name: {test_drive_data.get('test_drive_name', 'N/A')}\n"
                f"• Phone: {test_drive_data.get('test_drive_phone', 'N/A')}\n"
                f"• Date & Time: {datetime_str}\n"
                f"• Location: {location_text}\n"
                f"• Driving License: {dl_status}\n\n"
                f"Please confirm if all details are correct:\n"
                f"✅ Reply 'Yes' or 'Confirm' to book the test drive\n"
                f"❌ Reply 'No' or 'Change' to modify any details"
            )
            
            return confirmation_message
        
        except BrowseCarAnalysisError:
            # Fallback: just use the message as datetime
            datetime_str = message.strip()
            conversation_manager.update_data(user_id, test_drive_datetime=datetime_str)
            
            # Get all test drive data for confirmation
            test_drive_data = state.data
            selected_car = test_drive_data.get("selected_car")
            
            if not selected_car or not isinstance(selected_car, dict):
                return "I'm sorry, there was an error. Please start over."
            
            # Move to confirmation step
            conversation_manager.update_state(user_id, step="test_drive_confirm")
            
            # Format confirmation message
            location_type = test_drive_data.get("test_drive_location", "showroom")
            location_text = "Showroom visit" if location_type == "showroom" else "Home pickup"
            dl_status = "Yes, I have a driving license" if test_drive_data.get("test_drive_has_dl") else "No, I'll bring it on the day"
            
            year_str = f"({selected_car.get('year')})" if selected_car.get('year') else ""
            variant_str = f" {selected_car.get('variant')}" if selected_car.get('variant') else ""
            price_str = f"₹{selected_car.get('price', 0):,.0f}" if selected_car.get('price') else "Price on request"
            
            confirmation_message = (
                f"📋 *Please Confirm Your Test Drive Details*\n\n"
                f"*Car Selected:*\n"
                f"• {selected_car.get('brand', 'N/A')} {selected_car.get('model', 'N/A')}{variant_str} {year_str}\n"
                f"• Price: {price_str}\n\n"
                f"*Test Drive Details:*\n"
                f"• Name: {test_drive_data.get('test_drive_name', 'N/A')}\n"
                f"• Phone: {test_drive_data.get('test_drive_phone', 'N/A')}\n"
                f"• Date & Time: {datetime_str}\n"
                f"• Location: {location_text}\n"
                f"• Driving License: {dl_status}\n\n"
                f"Please confirm if all details are correct:\n"
                f"✅ Reply 'Yes' or 'Confirm' to book the test drive\n"
                f"❌ Reply 'No' or 'Change' to modify any details"
            )
            
            return confirmation_message
    
    elif state.step == "test_drive_confirm":
        # User confirming or changing test drive details
        message_lower = message.lower().strip()
        
        # Check if user wants to confirm
        if message_lower in ["yes", "y", "confirm", "ok", "okay", "sure", "correct", "proceed"]:
            # Get all test drive data
            test_drive_data = state.data
            selected_car = test_drive_data.get("selected_car")
            
            if not selected_car or not isinstance(selected_car, dict):
                return "I'm sorry, there was an error. Please start over."
            
            car_id = selected_car.get("id")
            if not car_id:
                return "I'm sorry, there was an error. The car ID is missing. Please start over."
            
            # Create booking
            try:
                if not car_db:
                    return "Database connection is not available. Please try again later."
                
                # Combine date and time for preferred_date
                date_str = test_drive_data.get("test_drive_date", "")
                time_str = test_drive_data.get("test_drive_time", "")
                datetime_str = f"{date_str} at {time_str}" if time_str else date_str
                
                # Fallback to old datetime field if new fields not available
                if not datetime_str:
                    datetime_str = test_drive_data.get("test_drive_datetime", "")
                
                # Include address in preferred_date if home pickup
                location_type = test_drive_data.get("test_drive_location", "showroom")
                if location_type == "home":
                    address = test_drive_data.get("test_drive_address", "")
                    if address:
                        datetime_str = f"{datetime_str} - Address: {address}"
                
                booking_id = await car_db.create_test_drive_booking(
                    user_name=test_drive_data.get("test_drive_name"),
                    phone_number=test_drive_data.get("test_drive_phone"),
                    car_id=car_id,
                    has_dl=test_drive_data.get("test_drive_has_dl", False),
                    location_type=test_drive_data.get("test_drive_location"),
                    preferred_date=datetime_str
                )
                
                # Clear conversation state
                conversation_manager.clear_state(user_id)
                
                location_type = test_drive_data.get("test_drive_location", "showroom")
                location_text = "at our showroom" if location_type == "showroom" else "with home pickup"
                dl_text = "with your driving license" if test_drive_data.get("test_drive_has_dl") else "and bring a valid driving license"
                
                year_str = f"({selected_car.get('year')})" if selected_car.get('year') else ""
                variant_str = f" {selected_car.get('variant')}" if selected_car.get('variant') else ""
                
                return (
                    f"🎉 *Test Drive Booked Successfully!*\n\n"
                    f"*Car:* {selected_car.get('brand', 'N/A')} {selected_car.get('model', 'N/A')}{variant_str} {year_str}\n"
                    f"*Name:* {test_drive_data.get('test_drive_name')}\n"
                    f"*Phone:* {test_drive_data.get('test_drive_phone')}\n"
                    f"*Date & Time:* {datetime_str}\n"
                    f"*Location:* {location_text}\n"
                    f"*Booking ID:* #{booking_id}\n\n"
                    f"Our team will contact you shortly to confirm the details {dl_text}. "
                    f"We're excited to show you this amazing car! 🚗✨\n\n"
                    f"Is there anything else I can help you with?"
                )
                
            except Exception as e:
                return f"I encountered an error booking your test drive. Please try again or contact us directly. Error: {str(e)}"
        
        # Check if user wants to change/modify
        elif message_lower in ["no", "n", "change", "modify", "edit", "wrong", "incorrect"]:
            return (
                "No problem! What would you like to change?\n\n"
                "1️⃣ Name\n"
                "2️⃣ Phone number\n"
                "3️⃣ Date & Time\n"
                "4️⃣ Location\n"
                "5️⃣ Start over"
            )
        
        else:
            return (
                "Please confirm your test drive booking:\n"
                "✅ Reply 'Yes' or 'Confirm' to proceed\n"
                "❌ Reply 'No' or 'Change' to modify details"
            )
    
    return "I'm not sure how to help with that. Could you please rephrase?"

