"""
Comprehensive Bot Testing Script
Tests all flows, flow switching, exit handling, and edge cases
"""

import asyncio
import sys
from typing import List, Tuple, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime
from unittest.mock import patch, AsyncMock

# Import the bot components
from main import process_text_message
from conversation_state import conversation_manager, ConversationState
from intent_service import extract_intent, IntentResult


@dataclass
class TestResult:
    """Result of a test scenario"""
    scenario_name: str
    passed: bool
    expected_flow: str
    actual_response: str
    error: str = ""
    execution_time: float = 0.0


class BotTester:
    """Comprehensive bot tester"""
    
    def __init__(self):
        self.test_results: List[TestResult] = []
        self.test_user_id = "test_user_12345"
        self.captured_responses: List[str] = []
        
    async def mock_send_whatsapp_message(self, to: str, message: str, **kwargs):
        """Mock function to capture messages instead of sending them"""
        self.captured_responses.append(message)
        print(f"Bot Response: {message[:100]}..." if len(message) > 100 else f"Bot Response: {message}")
        return {"status": "sent", "message_id": "test_msg"}
        
    async def run_test(self, scenario_name: str, messages: List[str], expected_flows: List[str]) -> TestResult:
        """Run a test scenario with multiple messages"""
        print(f"\n{'='*60}")
        print(f"Testing: {scenario_name}")
        print(f"{'='*60}")
        
        start_time = datetime.now()
        actual_flows = []
        last_response = ""
        error = ""
        self.captured_responses = []
        
        try:
            # Clear state before test
            conversation_manager.clear_state(self.test_user_id)
            
            # Mock send_whatsapp_message to capture responses without actually sending
            async def mock_send(to: str, message: str, **kwargs):
                self.captured_responses.append(message)
                last_response = message
                print(f"Bot Response: {message[:150]}..." if len(message) > 150 else f"Bot Response: {message}")
                return {"status": "sent", "message_id": "test_msg"}
            
            with patch('main.send_whatsapp_message', side_effect=mock_send):
                for i, message in enumerate(messages):
                    print(f"\n[Message {i+1}/{len(messages)}]")
                    print(f"User: {message}")
                    
                    try:
                        # Skip empty messages
                        if not message or not message.strip():
                            print("Skipping empty message")
                            continue
                        
                        # Process message through main handler
                        await process_text_message(self.test_user_id, message, f"msg_{i+1}")
                        
                        # Get current state after processing
                        state = conversation_manager.get_state(self.test_user_id)
                        current_flow = state.flow_name if state else "none"
                        actual_flows.append(current_flow)
                        
                        if self.captured_responses:
                            last_response = self.captured_responses[-1]
                        
                        print(f"Current Flow: {current_flow}")
                        print(f"Step: {state.step if state else 'none'}")
                        
                    except Exception as e:
                        error = str(e)
                        print(f"ERROR: {e}")
                        import traceback
                        traceback.print_exc()
                        break
            
            # Check if flows match expectations
            passed = True
            if len(actual_flows) != len(expected_flows):
                passed = False
            else:
                for actual, expected in zip(actual_flows, expected_flows):
                    if expected != "any" and actual != expected:
                        passed = False
                        break
            
            execution_time = (datetime.now() - start_time).total_seconds()
            
            result = TestResult(
                scenario_name=scenario_name,
                passed=passed,
                expected_flow=expected_flows[-1] if expected_flows else "none",
                actual_response=last_response,
                error=error,
                execution_time=execution_time
            )
            
            if passed:
                print(f"\n✅ PASSED: {scenario_name}")
            else:
                print(f"\n❌ FAILED: {scenario_name}")
                print(f"   Expected flows: {expected_flows}")
                print(f"   Actual flows: {actual_flows}")
            
            self.test_results.append(result)
            return result
            
        except Exception as e:
            execution_time = (datetime.now() - start_time).total_seconds()
            result = TestResult(
                scenario_name=scenario_name,
                passed=False,
                expected_flow=expected_flows[-1] if expected_flows else "none",
                actual_response="",
                error=str(e),
                execution_time=execution_time
            )
            self.test_results.append(result)
            print(f"\n❌ ERROR in {scenario_name}: {e}")
            return result
    
    async def test_browse_car_flow(self):
        """Test browse car flow"""
        await self.run_test(
            "Browse Car - Complete Flow",
            [
                "I want to browse cars",
                "Honda",
                "500000",
                "Sedan",
                "1",
                "Yes, I want to book a test drive",
                "John Doe",
                "9876543210",
                "Yes, I have a driving license",
                "Showroom"
            ],
            ["browse_car", "browse_car", "browse_car", "browse_car", "browse_car", "browse_car", "browse_car", "browse_car", "browse_car", "browse_car"]
        )
    
    async def test_emi_flow(self):
        """Test EMI calculation flow"""
        await self.run_test(
            "EMI Calculation - Complete Flow",
            [
                "I want to calculate EMI",
                "1",
                "200000",
                "5"
            ],
            ["emi", "emi", "emi", "emi"]
        )
    
    async def test_car_valuation_flow(self):
        """Test car valuation flow"""
        await self.run_test(
            "Car Valuation - Complete Flow",
            [
                "I want to get my car valued",
                "Honda",
                "City",
                "2020",
                "Petrol",
                "Good"
            ],
            ["car_valuation", "car_valuation", "car_valuation", "car_valuation", "car_valuation", "car_valuation"]
        )
    
    async def test_service_booking_flow(self):
        """Test service booking flow"""
        await self.run_test(
            "Service Booking - Complete Flow",
            [
                "I want to book a service",
                "1",
                "Honda",
                "City",
                "John Doe",
                "9876543210"
            ],
            ["service_booking", "service_booking", "service_booking", "service_booking", "service_booking", "service_booking"]
        )
    
    async def test_flow_switching_from_browse_to_emi(self):
        """Test switching from browse car to EMI"""
        await self.run_test(
            "Flow Switch: Browse Car → EMI",
            [
                "I want to browse cars",
                "I want to calculate EMI instead"
            ],
            ["browse_car", "emi"]
        )
    
    async def test_flow_switching_from_service_to_valuation(self):
        """Test switching from service booking to valuation"""
        await self.run_test(
            "Flow Switch: Service Booking → Valuation",
            [
                "I want to book a service",
                "Actually, I want to get my car valued"
            ],
            ["service_booking", "car_valuation"]
        )
    
    async def test_flow_switching_from_emi_to_browse(self):
        """Test switching from EMI to browse car"""
        await self.run_test(
            "Flow Switch: EMI → Browse Car",
            [
                "I want to calculate EMI",
                "Actually, I want to browse cars"
            ],
            ["emi", "browse_car"]
        )
    
    async def test_exit_keywords(self):
        """Test exit keyword handling"""
        await self.run_test(
            "Exit Keywords - Back to Menu",
            [
                "I want to browse cars",
                "back",
                "I want to calculate EMI",
                "menu",
                "I want to book a service",
                "exit"
            ],
            ["browse_car", "none", "emi", "none", "service_booking", "none"]
        )
    
    async def test_multiple_switches(self):
        """Test multiple flow switches in sequence"""
        await self.run_test(
            "Multiple Flow Switches",
            [
                "I want to browse cars",
                "Actually, calculate EMI",
                "Wait, I want to book a service",
                "No, get my car valued"
            ],
            ["browse_car", "emi", "service_booking", "car_valuation"]
        )
    
    async def test_incomplete_flow_then_switch(self):
        """Test starting a flow, not completing it, then switching"""
        await self.run_test(
            "Incomplete Flow Then Switch",
            [
                "I want to browse cars",
                "Honda",
                "I want to calculate EMI instead"
            ],
            ["browse_car", "browse_car", "emi"]
        )
    
    async def test_edge_cases(self):
        """Test edge cases"""
        await self.run_test(
            "Edge Cases - Empty/Invalid Messages",
            [
                "I want to browse cars",
                "",
                "   ",
                "Honda"
            ],
            ["browse_car", "browse_car", "browse_car", "browse_car"]
        )
    
    async def test_rapid_switching(self):
        """Test rapid flow switching"""
        await self.run_test(
            "Rapid Flow Switching",
            [
                "browse cars",
                "calculate EMI",
                "book service",
                "get valuation"
            ],
            ["browse_car", "emi", "service_booking", "car_valuation"]
        )
    
    async def test_natural_language_switches(self):
        """Test natural language flow switches"""
        await self.run_test(
            "Natural Language Flow Switches",
            [
                "I'm looking for a used car",
                "Actually, can you help me with EMI calculation?",
                "Wait, I need to book a service first"
            ],
            ["browse_car", "emi", "service_booking"]
        )
    
    async def test_exit_and_restart(self):
        """Test exiting and restarting a flow"""
        await self.run_test(
            "Exit and Restart Flow",
            [
                "I want to browse cars",
                "back",
                "I want to browse cars again"
            ],
            ["browse_car", "none", "browse_car"]
        )
    
    async def test_all_flows_initialization(self):
        """Test that all flows can be initialized"""
        flows = [
            ("Browse Car", "I want to browse cars", "browse_car"),
            ("EMI", "I want to calculate EMI", "emi"),
            ("Car Valuation", "I want to get my car valued", "car_valuation"),
            ("Service Booking", "I want to book a service", "service_booking"),
        ]
        
        for flow_name, message, expected_flow in flows:
            await self.run_test(
                f"Initialize {flow_name} Flow",
                [message],
                [expected_flow]
            )
            # Clear state between tests
            conversation_manager.clear_state(self.test_user_id)
            await asyncio.sleep(0.5)  # Small delay between tests
    
    async def run_all_tests(self):
        """Run all test scenarios"""
        print("\n" + "="*60)
        print("COMPREHENSIVE BOT TESTING SUITE")
        print("="*60)
        
        # Test all flows initialization
        await self.test_all_flows_initialization()
        
        # Test individual flows
        await self.test_browse_car_flow()
        await asyncio.sleep(1)
        
        await self.test_emi_flow()
        await asyncio.sleep(1)
        
        await self.test_car_valuation_flow()
        await asyncio.sleep(1)
        
        await self.test_service_booking_flow()
        await asyncio.sleep(1)
        
        # Test flow switching
        await self.test_flow_switching_from_browse_to_emi()
        await asyncio.sleep(1)
        
        await self.test_flow_switching_from_service_to_valuation()
        await asyncio.sleep(1)
        
        await self.test_flow_switching_from_emi_to_browse()
        await asyncio.sleep(1)
        
        await self.test_multiple_switches()
        await asyncio.sleep(1)
        
        await self.test_incomplete_flow_then_switch()
        await asyncio.sleep(1)
        
        await self.test_rapid_switching()
        await asyncio.sleep(1)
        
        await self.test_natural_language_switches()
        await asyncio.sleep(1)
        
        # Test exit handling
        await self.test_exit_keywords()
        await asyncio.sleep(1)
        
        await self.test_exit_and_restart()
        await asyncio.sleep(1)
        
        # Test edge cases
        await self.test_edge_cases()
        
        # Print summary
        self.print_summary()
    
    def print_summary(self):
        """Print test summary"""
        print("\n" + "="*60)
        print("TEST SUMMARY")
        print("="*60)
        
        total_tests = len(self.test_results)
        passed_tests = sum(1 for r in self.test_results if r.passed)
        failed_tests = total_tests - passed_tests
        
        print(f"\nTotal Tests: {total_tests}")
        print(f"✅ Passed: {passed_tests}")
        print(f"❌ Failed: {failed_tests}")
        print(f"Success Rate: {(passed_tests/total_tests*100):.1f}%")
        
        total_time = sum(r.execution_time for r in self.test_results)
        print(f"\nTotal Execution Time: {total_time:.2f} seconds")
        print(f"Average Time per Test: {(total_time/total_tests):.2f} seconds")
        
        if failed_tests > 0:
            print("\n" + "="*60)
            print("FAILED TESTS:")
            print("="*60)
            for result in self.test_results:
                if not result.passed:
                    print(f"\n❌ {result.scenario_name}")
                    if result.error:
                        print(f"   Error: {result.error}")
                    print(f"   Execution Time: {result.execution_time:.2f}s")
        
        print("\n" + "="*60)
        print("DETAILED RESULTS:")
        print("="*60)
        for result in self.test_results:
            status = "✅ PASS" if result.passed else "❌ FAIL"
            print(f"{status} | {result.scenario_name:50s} | {result.execution_time:6.2f}s")


async def main():
    """Main test runner"""
    tester = BotTester()
    try:
        await tester.run_all_tests()
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
    except Exception as e:
        print(f"\n\nFatal error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup
        conversation_manager.clear_state(tester.test_user_id)
        print("\n\nTest cleanup completed")


if __name__ == "__main__":
    asyncio.run(main())

