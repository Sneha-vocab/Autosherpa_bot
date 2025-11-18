"""Quick test script for car valuation flow - 5 conversations."""

import asyncio
import random
from conversation_state import conversation_manager
from car_valuation_flow import handle_car_valuation_flow
from database import car_db

# Test data
BRANDS = ["Hyundai", "Maruti", "Tata", "Honda", "Toyota"]
MODELS = ["i20", "Creta", "Swift", "City", "Innova"]
FUEL_TYPES = ["Petrol", "Diesel", "Electric", "CNG"]
CONDITIONS = ["Excellent", "Very Good", "Good", "Average", "Fair"]


async def test_valuation_conversation(conversation_num: int):
    """Test a single car valuation conversation."""
    user_id = f"test_valuation_{conversation_num}"
    
    print(f"\n{'='*80}")
    print(f"CONVERSATION {conversation_num}")
    print(f"{'='*80}")
    
    # Clear any existing state
    conversation_manager.clear_state(user_id)
    
    try:
        # Step 1: Initial message
        user_msg = random.choice([
            "value my car",
            "how much is my car worth",
            "car valuation",
            "I want to sell my car",
            "what's the price of my car"
        ])
        print(f"\n👤 User: {user_msg}")
        response = await handle_car_valuation_flow(user_id, user_msg, None)
        print(f"🤖 Bot: {response[:200]}...")
        
        # Step 2: Provide brand
        brand = random.choice(BRANDS)
        user_msg = brand
        print(f"\n👤 User: {user_msg}")
        response = await handle_car_valuation_flow(user_id, user_msg, None)
        print(f"🤖 Bot: {response[:200]}...")
        
        # Step 3: Provide model
        model = random.choice(MODELS)
        user_msg = model
        print(f"\n👤 User: {user_msg}")
        response = await handle_car_valuation_flow(user_id, user_msg, None)
        print(f"🤖 Bot: {response[:200]}...")
        
        # Step 4: Provide year
        year = random.randint(2015, 2023)
        user_msg = str(year)
        print(f"\n👤 User: {user_msg}")
        response = await handle_car_valuation_flow(user_id, user_msg, None)
        print(f"🤖 Bot: {response[:200]}...")
        
        # Step 5: Provide fuel type
        fuel_type = random.choice(FUEL_TYPES)
        user_msg = fuel_type
        print(f"\n👤 User: {user_msg}")
        response = await handle_car_valuation_flow(user_id, user_msg, None)
        print(f"🤖 Bot: {response[:200]}...")
        
        # Step 6: Provide condition
        condition = random.choice(CONDITIONS)
        user_msg = condition.lower()
        print(f"\n👤 User: {user_msg}")
        response = await handle_car_valuation_flow(user_id, user_msg, None)
        print(f"\n🤖 Bot: {response}")
        
        # Check if valuation was displayed
        if "₹" in response or "valuation" in response.lower() or "lakh" in response.lower():
            print(f"\n✅ SUCCESS: Valuation displayed!")
            if "₹" in response:
                # Extract the valuation amount
                import re
                match = re.search(r'₹([\d,]+)', response)
                if match:
                    print(f"   Valuation Amount: ₹{match.group(1)}")
        else:
            print(f"\n❌ FAILED: Valuation not displayed properly")
            print(f"   Response length: {len(response)}")
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Clear state
        conversation_manager.clear_state(user_id)


async def main():
    """Run 5 test conversations."""
    print("🚀 Testing Car Valuation Flow - 5 Conversations")
    print("=" * 80)
    
    # Initialize database if available
    if car_db and car_db.database_url:
        try:
            await car_db.init_schema()
            print("✓ Database initialized")
        except Exception as e:
            print(f"⚠ Database initialization warning: {e}")
    
    # Run 5 test conversations
    for i in range(1, 6):
        await test_valuation_conversation(i)
        # Small delay between conversations
        await asyncio.sleep(1)
    
    print(f"\n{'='*80}")
    print("✅ Test completed!")
    print(f"{'='*80}")


if __name__ == "__main__":
    asyncio.run(main())

