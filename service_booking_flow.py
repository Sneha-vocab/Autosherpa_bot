"""Service Booking Flow Handler."""

import re
from typing import Optional, List, Dict, Any
from datetime import datetime
from conversation_state import conversation_manager, ConversationState
from database import car_db
from intent_service import generate_response
from service_booking_analyzer import (
    analyze_service_booking_message,
    generate_service_booking_response,
    ServiceBookingAnalysisError,
    AVAILABLE_SERVICES,
    SERVICE_TYPES,
)

# Cache for brands (fetched from database)
_brands_cache: Optional[List[str]] = None


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


def clear_brands_cache():
    """Clear brands cache to force refresh from database."""
    global _brands_cache
    _brands_cache = None


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


def extract_registration_number(message: str) -> Optional[str]:
    """Extract registration number from message."""
    # Pattern for Indian registration numbers: XX##XX####
    pattern = r'\b([A-Z]{2}\d{2}[A-Z]{1,2}\d{4})\b'
    match = re.search(pattern, message.upper())
    if match:
        return match.group(1)
    return None


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


def format_services_list() -> str:
    """Format list of available services for display."""
    message = (
        "🚗 *At Sherpa Hyundai, we offer everything you need — from car buying to servicing — all under one roof!*\n\n"
        "*OUR SERVICES INCLUDE:*\n\n"
        "*1. New Car Sales*\n"
        "   • Full range of Hyundai models\n"
        "   • Expert sales consultation\n"
        "   • Test drive at your convenience\n\n"
        "*2. Certified Pre-Owned Cars*\n"
        "   • Thoroughly inspected & certified\n"
        "   • Transparent pricing & service history\n"
        "   • Finance & exchange options\n\n"
        "*3. Vehicle Servicing & Repairs*\n"
        "   • Hyundai-certified technicians\n"
        "   • Genuine spare parts\n"
        "   • Quick turnaround & pickup-drop facility\n\n"
        "*4. Bodyshop & Insurance Claims*\n"
        "   • Accident repairs & dent-paint services\n"
        "   • Hassle-free insurance claim assistance\n"
        "   • Cashless facility with major insurers\n\n"
        "*5. Finance & Loan Assistance*\n"
        "   • Tie-ups with top banks & NBFCs\n"
        "   • Best interest rates & fast approvals\n"
        "   • On-road pricing breakdown\n\n"
        "*6. Car Insurance & Renewals*\n"
        "   • Instant insurance quotes\n"
        "   • Renewal reminders\n"
        "   • Claim support from start to finish\n\n"
        "*7. RC Transfer & Documentation*\n"
        "   • Ownership transfer assistance\n"
        "   • RTO support\n"
        "   • Documentation help for resale or exchange\n\n"
        "Want to explore a service in detail?\n\n"
        "1️⃣ Book a Service (We will call you back shortly)\n"
        "2️⃣ Browse Used Cars\n"
        "3️⃣ Talk to Our Team\n"
        "4️⃣ Back to main menu\n\n"
        "Please select an option (1, 2, 3, or 4):"
    )
    return message


def format_service_booking_confirmation(booking_data: Dict[str, Any]) -> str:
    """Format service booking confirmation message."""
    service = booking_data.get("service", "N/A")
    make = booking_data.get("make", "N/A")
    car_model = booking_data.get("model", "N/A")
    year = booking_data.get("year", "N/A")
    registration = booking_data.get("registration_number", "N/A")
    service_type = booking_data.get("service_type", "N/A")
    booking_id = booking_data.get("booking_id", "N/A")
    customer_name = booking_data.get("customer_name", "N/A")
    phone = booking_data.get("phone_number", "N/A")
    
    message = (
        f"✅ *Service Booking Confirmed!*\n\n"
        f"*Booking ID:* #{booking_id}\n\n"
        f"*Service Details:*\n"
        f"• Service: {service}\n"
        f"• Service Type: {service_type}\n\n"
        f"*Vehicle Details:*\n"
        f"• Make: {make}\n"
        f"• Model: {car_model}\n"
        f"• Year: {year}\n"
        f"• Registration: {registration}\n\n"
        f"*Customer Details:*\n"
        f"• Name: {customer_name}\n"
        f"• Phone: {phone}\n\n"
        f"Our team will call you back shortly to confirm the details and schedule your service! 📞\n\n"
        f"Is there anything else I can help you with?"
    )
    
    return message


async def handle_service_booking_flow(
    user_id: str,
    message: str,
    intent_result: Any
) -> str:
    """Handle the service booking flow with intelligent message analysis."""
    state = conversation_manager.get_state(user_id)
    
    # Get available brands from database
    available_brands = await get_brands_from_db()
    
    # Initialize flow if not already started
    if state is None or state.flow_name != "service_booking":
        # Show services list
        conversation_manager.set_state(
            user_id,
            ConversationState(
                user_id=user_id,
                flow_name="service_booking",
                step="showing_services",
                data={}
            )
        )
        return format_services_list()
    
    # Continue based on current step
    state = conversation_manager.get_state(user_id)
    
    if state.step == "showing_services":
        # User selecting a service or option
        message_lower = message.lower().strip()
        
        # Check for option selection
        if message_lower in ["1", "book", "book service", "book a service"]:
            # User wants to book a service
            conversation_manager.update_state(user_id, step="collecting_vehicle_details")
            conversation_manager.update_data(user_id, service="Vehicle Servicing & Repairs")
            try:
                analysis = await analyze_service_booking_message(
                    message=message,
                    conversation_context={"step": "collecting_vehicle_details", "data": {}},
                    available_brands=available_brands,
                )
                response = await generate_service_booking_response(
                    message=message,
                    conversation_context={"step": "collecting_vehicle_details", "data": {}},
                    analysis_result=analysis,
                    available_brands=available_brands,
                )
                return response
            except ServiceBookingAnalysisError as e:
                print(f"Analysis error: {e}")
                return (
                    "Perfect! Let's book a service for you! 🚗🔧\n\n"
                    "Please provide all required details:\n\n"
                    "*Vehicle Details:*\n"
                    "• Make: (e.g., Hyundai, Maruti, Honda)\n"
                    "• Model: (e.g., i20, Swift, City)\n"
                    "• Year: (e.g., 2020, 2021)\n"
                    "• Registration Number: (e.g., KA01AB1234)\n\n"
                    "Let's start with the car make/brand:"
                )
            except Exception as e:
                print(f"Error generating response: {e}")
                return (
                    "Perfect! Let's book a service for you! 🚗🔧\n\n"
                    "Please provide all required details:\n\n"
                    "*Vehicle Details:*\n"
                    "• Make: (e.g., Hyundai, Maruti, Honda)\n"
                    "• Model: (e.g., i20, Swift, City)\n"
                    "• Year: (e.g., 2020, 2021)\n"
                    "• Registration Number: (e.g., KA01AB1234)\n\n"
                    "Let's start with the car make/brand:"
                )
        
        elif message_lower in ["2", "browse", "browse cars", "used cars"]:
            # Route to browse cars
            conversation_manager.clear_state(user_id)
            from browse_car_flow import handle_browse_car_flow
            return await handle_browse_car_flow(user_id, "I want to browse cars", None)
        
        elif message_lower in ["3", "talk", "team", "contact"]:
            # Talk to team
            return (
                "Great! Our team is here to help! 👥\n\n"
                "You can reach us at:\n"
                "📞 Phone: [Contact Number]\n"
                "📧 Email: [Email Address]\n"
                "📍 Address: [Showroom Address]\n\n"
                "Or you can book a service and we'll call you back shortly!\n\n"
                "Would you like to book a service? (Yes/No)"
            )
        
        elif message_lower in ["4", "back", "menu", "main menu"]:
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
        
        else:
            # Try intelligent analysis
            try:
                analysis = await analyze_service_booking_message(
                    message=message,
                    conversation_context={
                        "step": state.step,
                        "data": state.data
                    },
                    available_brands=available_brands,
                )
                
                response = await generate_service_booking_response(
                    message=message,
                    conversation_context={
                        "step": state.step,
                        "data": state.data
                    },
                    analysis_result=analysis,
                    available_brands=available_brands,
                )
                return response
            except ServiceBookingAnalysisError as e:
                print(f"Analysis error in showing_services: {e}")
                return format_services_list()
            except Exception as e:
                print(f"Error generating response: {e}")
                return format_services_list()
    
    elif state.step == "collecting_vehicle_details":
        # Collecting vehicle details: Make, Model, Year, Registration
        try:
            analysis = await analyze_service_booking_message(
                message=message,
                conversation_context={
                    "step": state.step,
                    "data": state.data
                },
                available_brands=available_brands,
            )
            
            # Extract information
            make = analysis.get("extracted_make") or state.data.get("make")
            car_model = analysis.get("extracted_model") or state.data.get("model")
            year = analysis.get("extracted_year") or state.data.get("year")
            registration = analysis.get("extracted_registration") or state.data.get("registration_number")
            
            # Handle change intent
            user_intent = analysis.get("user_intent", "").lower()
            if "changing_criteria" in user_intent or "change" in message.lower():
                conversation_manager.update_state(user_id, step="showing_services")
                conversation_manager.update_data(user_id, make=None, model=None, year=None, registration_number=None)
                try:
                    response = await generate_service_booking_response(
                        message=message,
                        conversation_context={"step": "showing_services", "data": {}},
                        analysis_result=analysis,
                        available_brands=available_brands,
                    )
                    return response
                except Exception as e:
                    print(f"Error generating response: {e}")
                return format_services_list()
            
            # Fallback extraction
            if not make:
                make = await extract_brand_from_message(message)
            if not year:
                year = extract_year_from_message(message)
            if not registration:
                registration = extract_registration_number(message)
            
            # Update state
            conversation_manager.update_data(
                user_id,
                make=make,
                model=car_model if car_model else state.data.get("model"),
                year=year,
                registration_number=registration
            )
            
            # Check what's missing
            if not make:
                try:
                    response = await generate_service_booking_response(
                        message=message,
                        conversation_context={
                            "step": state.step,
                            "data": {"make": None, "model": car_model, "year": year, "registration_number": registration}
                        },
                        analysis_result=analysis,
                        available_brands=available_brands,
                    )
                    return response
                except Exception as e:
                    print(f"Error generating response: {e}")
                    brands_list = ", ".join(available_brands[:5]) if available_brands else ""
                    return f"Which brand/make is your car? (e.g., {brands_list})" if brands_list else "Which brand/make is your car?"
            
            elif not car_model and not state.data.get("model"):
                try:
                    response = await generate_service_booking_response(
                        message=message,
                        conversation_context={
                            "step": state.step,
                            "data": {"make": make, "model": None, "year": year, "registration_number": registration}
                        },
                        analysis_result=analysis,
                        available_brands=available_brands,
                    )
                    return response
                except Exception as e:
                    print(f"Error generating response: {e}")
                    return f"What's the model of your {make} car? (e.g., i20, Creta, Venue)"
            
            elif not year:
                try:
                    response = await generate_service_booking_response(
                        message=message,
                        conversation_context={
                            "step": state.step,
                            "data": {"make": make, "model": car_model or state.data.get("model"), "year": None, "registration_number": registration}
                        },
                        analysis_result=analysis,
                        available_brands=available_brands,
                    )
                    return response
                except Exception as e:
                    print(f"Error generating response: {e}")
                    return f"What year is your {make} {car_model or state.data.get('model', 'car')}? (e.g., 2020, 2021)"
            
            elif not registration:
                try:
                    response = await generate_service_booking_response(
                        message=message,
                        conversation_context={
                            "step": state.step,
                            "data": {"make": make, "model": car_model or state.data.get("model"), "year": year, "registration_number": None}
                        },
                        analysis_result=analysis,
                        available_brands=available_brands,
                    )
                    return response
                except Exception as e:
                    print(f"Error generating response: {e}")
                    return f"What's the registration number of your car? (e.g., KA01AB1234)"
            
            else:
                # All vehicle details collected, move to service type
                conversation_manager.update_state(user_id, step="collecting_service_type")
                try:
                    response = await generate_service_booking_response(
                        message=message,
                        conversation_context={
                            "step": "collecting_service_type",
                            "data": state.data
                        },
                        analysis_result=analysis,
                        available_brands=available_brands,
                    )
                    return response
                except Exception as e:
                    print(f"Error generating response: {e}")
                    return (
                        f"Perfect! I have all the vehicle details:\n"
                        f"• Make: {make}\n"
                        f"• Model: {car_model or state.data.get('model')}\n"
                        f"• Year: {year}\n"
                        f"• Registration: {registration}\n\n"
                        f"Now, what type of service do you need?\n\n"
                        f"1️⃣ Regular Service\n"
                        f"2️⃣ Major Service\n"
                        f"3️⃣ Accident Repair\n"
                        f"4️⃣ Insurance Claim\n"
                        f"5️⃣ Other (please specify)\n\n"
                        f"Please select an option (1-5):"
                    )
        
        except ServiceBookingAnalysisError as e:
            print(f"Analysis error in collecting_vehicle_details: {e}")
            # Fallback extraction
            make = await extract_brand_from_message(message) or state.data.get("make")
            car_model = state.data.get("model")
            year = extract_year_from_message(message) or state.data.get("year")
            registration = extract_registration_number(message) or state.data.get("registration_number")
            
            conversation_manager.update_data(user_id, make=make, model=car_model, year=year, registration_number=registration)
            
            if not make:
                return "Which brand/make is your car?"
            elif not car_model:
                return f"What's the model of your {make} car?"
            elif not year:
                return f"What year is your {make} {car_model}?"
            elif not registration:
                return f"What's the registration number? (e.g., KA01AB1234)"
            else:
                conversation_manager.update_state(user_id, step="collecting_service_type")
                return (
                    f"Perfect! Now, what type of service do you need?\n\n"
                    f"1️⃣ Regular Service\n"
                    f"2️⃣ Major Service\n"
                    f"3️⃣ Accident Repair\n"
                    f"4️⃣ Insurance Claim\n"
                    f"5️⃣ Other\n\n"
                    f"Please select (1-5):"
                )
        except Exception as e:
            print(f"Error in collecting_vehicle_details step: {e}")
            # Fallback extraction
            make = await extract_brand_from_message(message) or state.data.get("make")
            car_model = state.data.get("model")
            year = extract_year_from_message(message) or state.data.get("year")
            registration = extract_registration_number(message) or state.data.get("registration_number")
            
            conversation_manager.update_data(user_id, make=make, model=car_model, year=year, registration_number=registration)
            
            if not make:
                return "Which brand/make is your car?"
            elif not car_model:
                return f"What's the model of your {make} car?"
            elif not year:
                return f"What year is your {make} {car_model}?"
            elif not registration:
                return f"What's the registration number? (e.g., KA01AB1234)"
            else:
                conversation_manager.update_state(user_id, step="collecting_service_type")
                return (
                    f"Perfect! Now, what type of service do you need?\n\n"
                    f"1️⃣ Regular Service\n"
                    f"2️⃣ Major Service\n"
                    f"3️⃣ Accident Repair\n"
                    f"4️⃣ Insurance Claim\n"
                    f"5️⃣ Other\n\n"
                    f"Please select (1-5):"
                )
    
    elif state.step == "collecting_service_type":
        # Collecting service type
        try:
            analysis = await analyze_service_booking_message(
                message=message,
                conversation_context={
                    "step": state.step,
                    "data": state.data
                },
                available_brands=available_brands,
            )
            
            # Extract service type
            service_type = analysis.get("extracted_service_type")
            message_lower = message.lower().strip()
            
            # Map number selections to service types
            if not service_type:
                if message_lower in ["1", "regular", "regular service"]:
                    service_type = "Regular Service"
                elif message_lower in ["2", "major", "major service"]:
                    service_type = "Major Service"
                elif message_lower in ["3", "accident", "accident repair", "repair"]:
                    service_type = "Accident Repair"
                elif message_lower in ["4", "insurance", "insurance claim", "claim"]:
                    service_type = "Insurance Claim"
                elif message_lower in ["5", "other"]:
                    service_type = "Other"
            
            # Handle change intent
            user_intent = analysis.get("user_intent", "").lower()
            if "changing_criteria" in user_intent or "change" in message_lower:
                conversation_manager.update_state(user_id, step="collecting_vehicle_details")
                conversation_manager.update_data(user_id, service_type=None)
                try:
                    response = await generate_service_booking_response(
                        message=message,
                        conversation_context={"step": "collecting_vehicle_details", "data": state.data},
                        analysis_result=analysis,
                        available_brands=available_brands,
                    )
                    return response
                except Exception as e:
                    print(f"Error generating response: {e}")
                return "No problem! Let's update the vehicle details. What would you like to change?"
            
            if service_type:
                # Store service type and collect customer details
                conversation_manager.update_data(user_id, service_type=service_type)
                conversation_manager.update_state(user_id, step="collecting_customer_details")
                
                try:
                    response = await generate_service_booking_response(
                        message=message,
                        conversation_context={
                            "step": "collecting_customer_details",
                            "data": {**state.data, "service_type": service_type}
                        },
                        analysis_result=analysis,
                        available_brands=available_brands,
                    )
                    return response
                except Exception as e:
                    print(f"Error generating response: {e}")
                    return (
                        f"Excellent! Service type: *{service_type}* ✅\n\n"
                        f"Now I need your contact details:\n\n"
                        f"Please provide your name:"
                    )
            else:
                # Ask for service type
                try:
                    response = await generate_service_booking_response(
                        message=message,
                        conversation_context={
                            "step": state.step,
                            "data": state.data
                        },
                        analysis_result=analysis,
                        available_brands=available_brands,
                    )
                    return response
                except Exception as e:
                    print(f"Error generating response: {e}")
                    return (
                        f"Please select a service type:\n\n"
                        f"1️⃣ Regular Service\n"
                        f"2️⃣ Major Service\n"
                        f"3️⃣ Accident Repair\n"
                        f"4️⃣ Insurance Claim\n"
                        f"5️⃣ Other (please specify)\n\n"
                        f"Reply with the number (1-5) or the service type name:"
                    )
        
        except ServiceBookingAnalysisError as e:
            print(f"Analysis error in collecting_service_type: {e}")
            message_lower = message.lower().strip()
            if message_lower in ["1", "regular"]:
                service_type = "Regular Service"
            elif message_lower in ["2", "major"]:
                service_type = "Major Service"
            elif message_lower in ["3", "accident", "repair"]:
                service_type = "Accident Repair"
            elif message_lower in ["4", "insurance", "claim"]:
                service_type = "Insurance Claim"
            elif message_lower in ["5", "other"]:
                service_type = "Other"
            else:
                return "Please select a service type (1-5):"
            
            conversation_manager.update_data(user_id, service_type=service_type)
            conversation_manager.update_state(user_id, step="collecting_customer_details")
            return (
                f"Perfect! Service type: *{service_type}* ✅\n\n"
                f"Now I need your contact details. Please provide your name:"
            )
        except Exception as e:
            print(f"Error in collecting_service_type step: {e}")
            message_lower = message.lower().strip()
            if message_lower in ["1", "regular"]:
                service_type = "Regular Service"
            elif message_lower in ["2", "major"]:
                service_type = "Major Service"
            elif message_lower in ["3", "accident", "repair"]:
                service_type = "Accident Repair"
            elif message_lower in ["4", "insurance", "claim"]:
                service_type = "Insurance Claim"
            elif message_lower in ["5", "other"]:
                service_type = "Other"
            else:
                return "Please select a service type (1-5):"
            
            conversation_manager.update_data(user_id, service_type=service_type)
            conversation_manager.update_state(user_id, step="collecting_customer_details")
            return (
                f"Perfect! Service type: *{service_type}* ✅\n\n"
                f"Now I need your contact details. Please provide your name:"
            )
    
    elif state.step == "collecting_customer_details":
        # Collecting customer name and phone
        try:
            analysis = await analyze_service_booking_message(
                message=message,
                conversation_context={
                    "step": state.step,
                    "data": state.data
                },
                available_brands=available_brands,
            )
            
            # Check if we have name and phone
            customer_name = state.data.get("customer_name")
            phone = state.data.get("phone_number")
            
            # Extract phone number if present
            phone_digits = re.sub(r'\D', '', message)
            if len(phone_digits) >= 10 and not phone:
                phone = phone_digits[:10] if len(phone_digits) == 10 else phone_digits[-10:]
            
            # If no name yet, assume this message is the name
            if not customer_name:
                # Remove phone digits from name
                name = message
                if phone:
                    name = re.sub(r'\d+', '', name).strip()
                if len(name) >= 2:
                    customer_name = name
                    conversation_manager.update_data(user_id, customer_name=customer_name)
            
            if phone:
                conversation_manager.update_data(user_id, phone_number=phone)
            
            # Check what's missing
            if not customer_name:
                try:
                    response = await generate_service_booking_response(
                        message=message,
                        conversation_context={
                            "step": state.step,
                            "data": state.data
                        },
                        analysis_result=analysis,
                        available_brands=available_brands,
                    )
                    return response
                except Exception as e:
                    print(f"Error generating response: {e}")
                    return "Please provide your name:"
            
            elif not phone:
                try:
                    response = await generate_service_booking_response(
                        message=message,
                        conversation_context={
                            "step": state.step,
                            "data": {**state.data, "customer_name": customer_name}
                        },
                        analysis_result=analysis,
                        available_brands=available_brands,
                    )
                    return response
                except Exception as e:
                    print(f"Error generating response: {e}")
                    return f"Nice to meet you, {customer_name}! 👋\n\nCould you please share your phone number?"
            
            else:
                # All details collected, create booking
                booking_data = {
                    "service": "Vehicle Servicing & Repairs",  # Default service
                    "make": state.data.get("make"),
                    "model": state.data.get("model"),
                    "year": state.data.get("year"),
                    "registration_number": state.data.get("registration_number"),
                    "service_type": state.data.get("service_type"),
                    "customer_name": customer_name,
                    "phone_number": phone,
                }
                
                # Create booking in database
                try:
                    if car_db:
                        booking_id = await car_db.create_service_booking(
                            customer_name=customer_name,
                            phone_number=phone,
                            make=booking_data["make"],
                            model=booking_data["model"],
                            year=booking_data["year"],
                            registration_number=booking_data["registration_number"],
                            service_type=booking_data["service_type"]
                        )
                        booking_data["booking_id"] = booking_id
                    else:
                        booking_data["booking_id"] = f"SB{datetime.now().strftime('%Y%m%d%H%M%S')}"
                except Exception as e:
                    print(f"Error creating service booking: {e}")
                    booking_data["booking_id"] = f"SB{datetime.now().strftime('%Y%m%d%H%M%S')}"
                    return f"I encountered an error booking your service. Please try again or contact us directly. Error: {str(e)}"
                
                # Clear state
                conversation_manager.clear_state(user_id)
                
                return format_service_booking_confirmation(booking_data)
        
        except ServiceBookingAnalysisError as e:
            print(f"Analysis error in collecting_customer_details: {e}")
            # Fallback
            customer_name = state.data.get("customer_name")
            phone = state.data.get("phone_number")
            
            if not customer_name:
                if len(message.strip()) >= 2:
                    customer_name = message.strip()
                    conversation_manager.update_data(user_id, customer_name=customer_name)
                else:
                    return "Please provide a valid name (at least 2 characters)."
            
            if not phone:
                phone_digits = re.sub(r'\D', '', message)
                if len(phone_digits) >= 10:
                    phone = phone_digits[:10] if len(phone_digits) == 10 else phone_digits[-10:]
                    conversation_manager.update_data(user_id, phone_number=phone)
                else:
                    return f"Nice to meet you, {customer_name}! Please share your 10-digit phone number."
            
            if customer_name and phone:
                # Create booking
                booking_data = {
                    "service": "Vehicle Servicing & Repairs",
                    "make": state.data.get("make"),
                    "model": state.data.get("model"),
                    "year": state.data.get("year"),
                    "registration_number": state.data.get("registration_number"),
                    "service_type": state.data.get("service_type"),
                    "customer_name": customer_name,
                    "phone_number": phone,
                }
                
                try:
                    if car_db:
                        booking_id = await car_db.create_service_booking(
                            customer_name=customer_name,
                            phone_number=phone,
                            make=booking_data["make"],
                            model=booking_data["model"],
                            year=booking_data["year"],
                            registration_number=booking_data["registration_number"],
                            service_type=booking_data["service_type"]
                        )
                        booking_data["booking_id"] = booking_id
                    else:
                        booking_data["booking_id"] = f"SB{datetime.now().strftime('%Y%m%d%H%M%S')}"
                except Exception as e:
                    print(f"Error creating service booking: {e}")
                    booking_data["booking_id"] = f"SB{datetime.now().strftime('%Y%m%d%H%M%S')}"
                    return f"I encountered an error booking your service. Please try again or contact us directly. Error: {str(e)}"
                
                conversation_manager.clear_state(user_id)
                return format_service_booking_confirmation(booking_data)
        except Exception as e:
            print(f"Error in collecting_customer_details step: {e}")
            # Fallback
            customer_name = state.data.get("customer_name")
            phone = state.data.get("phone_number")
            
            if not customer_name:
                if len(message.strip()) >= 2:
                    customer_name = message.strip()
                    conversation_manager.update_data(user_id, customer_name=customer_name)
                else:
                    return "Please provide a valid name (at least 2 characters)."
            
            if not phone:
                phone_digits = re.sub(r'\D', '', message)
                if len(phone_digits) >= 10:
                    phone = phone_digits[:10] if len(phone_digits) == 10 else phone_digits[-10:]
                    conversation_manager.update_data(user_id, phone_number=phone)
                else:
                    return f"Nice to meet you, {customer_name}! Please share your 10-digit phone number."
            
            if customer_name and phone:
                # Create booking
                booking_data = {
                    "service": "Vehicle Servicing & Repairs",
                    "make": state.data.get("make"),
                    "model": state.data.get("model"),
                    "year": state.data.get("year"),
                    "registration_number": state.data.get("registration_number"),
                    "service_type": state.data.get("service_type"),
                    "customer_name": customer_name,
                    "phone_number": phone,
                }
                
                try:
                    if car_db:
                        booking_id = await car_db.create_service_booking(
                            customer_name=customer_name,
                            phone_number=phone,
                            make=booking_data["make"],
                            model=booking_data["model"],
                            year=booking_data["year"],
                            registration_number=booking_data["registration_number"],
                            service_type=booking_data["service_type"]
                        )
                        booking_data["booking_id"] = booking_id
                    else:
                        booking_data["booking_id"] = f"SB{datetime.now().strftime('%Y%m%d%H%M%S')}"
                except Exception as e:
                    print(f"Error creating service booking: {e}")
                    booking_data["booking_id"] = f"SB{datetime.now().strftime('%Y%m%d%H%M%S')}"
                    return f"I encountered an error booking your service. Please try again or contact us directly. Error: {str(e)}"
                
                conversation_manager.clear_state(user_id)
                return format_service_booking_confirmation(booking_data)
    
    return "I'm not sure how to help with that. Could you please rephrase?"

