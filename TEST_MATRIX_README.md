# Test Matrix for AutoSherpa Bot

## Overview

This test matrix tests **100 complete conversations per flow** (400 total conversations) to verify bot responses across all flows:

1. **Browse Car Flow** - Complete car browsing and test drive booking
2. **Car Valuation Flow** - Complete car valuation process
3. **EMI Flow** - Complete EMI calculation process
4. **Service Booking Flow** - Complete service booking process

## Usage

### Run Tests

```bash
python test_matrix.py
```

Or use the runner script:

```bash
python run_tests.py
```

### What It Tests

For each flow, the test matrix:

1. **Simulates complete conversations** from start to finish
2. **Verifies bot responses** are appropriate for each step
3. **Tracks errors** and completion rates
4. **Generates comprehensive reports** in JSON and text formats

### Test Coverage

- **100 conversations per flow** = 400 total conversations
- Each conversation goes through **all steps** of the flow
- Responses are **verified** for appropriateness
- **Errors are tracked** and reported

### Output

The test generates two report files:

1. **JSON Report** (`test_report_YYYYMMDD_HHMMSS.json`) - Detailed results with all conversation data
2. **Text Report** (`test_report_YYYYMMDD_HHMMSS.txt`) - Human-readable summary

### Report Contents

Each report includes:

- **Summary Statistics**:
  - Total conversations
  - Completion rate
  - Average steps per conversation
  - Total errors
  - Response verification rate

- **Detailed Results**:
  - All user messages and bot responses
  - Step-by-step conversation flow
  - Error details (if any)
  - Completion status

### Example Output

```
🚀 Starting AutoSherpa Bot Test Matrix
============================================================
⚠️  Note: This will test 100 conversations per flow (400 total)
⚠️  Note: Tests make real API calls to Gemini - may take time
============================================================

📊 Testing browse_car flow (100 conversations)...
  This may take several minutes...
  ✓ Completed: 95/100
  ✓ Total steps: 850
  ✓ Errors: 5

📊 Testing car_valuation flow (100 conversations)...
  ...

============================================================
TEST SUMMARY
============================================================

BROWSE CAR:
  Total Conversations: 100
  Completed: 95 (95.00%)
  Average Steps: 8.50
  Errors: 5
  Verified Responses: 800 (94.12%)

...
```

### Notes

- **API Calls**: Tests make real API calls to Google Gemini, so ensure `GOOGLE_API_KEY` is set in your `.env` file
- **Database**: Tests may require database access for some flows (browse car, service booking)
- **Time**: Running 400 conversations may take 30-60 minutes depending on API response times
- **State Management**: Each conversation uses a unique user ID and clears state after completion

### Requirements

- Python 3.8+
- All dependencies from `requirements.txt`
- Valid `GOOGLE_API_KEY` in `.env`
- Database connection (optional, for full functionality)

### Troubleshooting

**If tests fail:**
1. Check that `GOOGLE_API_KEY` is set correctly
2. Verify database connection if using database-dependent flows
3. Check network connectivity for API calls
4. Review error messages in the generated report

**If completion rates are low:**
- Check bot responses in the detailed report
- Verify that test data (brands, models, etc.) match your database
- Review conversation flows to ensure test messages are appropriate


