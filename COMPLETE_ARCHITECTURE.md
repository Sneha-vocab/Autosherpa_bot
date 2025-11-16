# AutoSherpa - Complete Architecture Documentation

**Version:** 1.0.0  
**Last Updated:** 2024  
**Project:** WhatsApp AI Chatbot for Sherpa Hyundai

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [System Overview](#system-overview)
3. [Architecture Layers](#architecture-layers)
4. [Orchestrator Pattern](#orchestrator-pattern)
5. [Component Architecture](#component-architecture)
6. [Data Flow Architecture](#data-flow-architecture)
7. [Flow Architecture](#flow-architecture)
8. [State Management](#state-management)
9. [Database Architecture](#database-architecture)
10. [API Architecture](#api-architecture)
11. [AI Integration Architecture](#ai-integration-architecture)
12. [Error Handling Architecture](#error-handling-architecture)
13. [Security Architecture](#security-architecture)
14. [Technology Stack](#technology-stack)
15. [Design Patterns](#design-patterns)
16. [Module Structure](#module-structure)
17. [Deployment Architecture](#deployment-architecture)
18. [Scalability & Performance](#scalability--performance)

---

## Executive Summary

**AutoSherpa** is a conversational AI chatbot system for Sherpa Hyundai that enables customers to browse used cars, get car valuations, calculate EMI, and book services through WhatsApp. The system uses a **layered architecture with an orchestrator pattern** to coordinate multiple AI-powered flows.

### Key Architectural Decisions

- ✅ **Orchestrator Pattern**: Central coordinator (`process_text_message()`) routes and coordinates all flows
- ✅ **State Machine Pattern**: Each flow implements a state machine for conversation progression
- ✅ **AI-Powered Analysis**: Google Gemini LLM for intelligent message understanding
- ✅ **Layered Architecture**: Clear separation between Presentation, API, Application, State, and Data layers
- ✅ **Exception Handling**: Comprehensive error handling with fallback mechanisms
- ✅ **Async/Await**: Fully asynchronous for high performance

---

## System Overview

### Purpose
Provide an intelligent, conversational interface for car dealership operations via WhatsApp, enabling customers to:
- Browse and search used cars
- Get car valuations
- Calculate EMI for car loans
- Book car services

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    EXTERNAL INTERFACES                          │
│  WhatsApp (Meta API)  │  Google Gemini API  │  PostgreSQL      │
└───────────────────────┬─────────────────────┬──────────────────┘
                        │                     │
                        ▼                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                    ORCHESTRATOR LAYER                            │
│              process_text_message() (main.py)                    │
│  - State Coordination  │  Flow Routing  │  Service Coordination │
└───────────────────────┬──────────────────────────────────────────┘
                        │
        ┌───────────────┼───────────────┐
        │               │               │
        ▼               ▼               ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ Intent       │ │ Flow         │ │ State       │
│ Service      │ │ Handlers     │ │ Manager     │
└──────┬───────┘ └──────┬───────┘ └──────┬───────┘
       │                 │                │
       └─────────────────┼────────────────┘
                        │
        ┌───────────────┼───────────────┐
        │               │               │
        ▼               ▼               ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ AI Analyzers │ │ Database     │ │ WhatsApp API │
│ (Gemini LLM) │ │ (PostgreSQL) │ │ (Meta)      │
└──────────────┘ └──────────────┘ └──────────────┘
```

---

## Architecture Layers

### Layer 1: Presentation Layer
**Component**: WhatsApp Business API (Meta)
- **Purpose**: User interface for conversations
- **Protocol**: HTTP/HTTPS webhooks
- **Security**: Signature verification, token validation

### Layer 2: API Layer
**Component**: FastAPI Application (`main.py`)
- **Endpoints**:
  - `GET /` - Health check
  - `GET /webhook` - Webhook verification
  - `POST /webhook` - Message reception
- **Responsibilities**:
  - Webhook verification
  - Signature validation
  - Message parsing
  - Request routing

### Layer 3: Application Layer (Orchestrator)
**Component**: `process_text_message()` in `main.py`
- **Responsibilities**:
  - Message orchestration
  - Intent extraction coordination
  - Flow routing
  - Service coordination
  - Error handling
  - Response delivery

**Sub-Components**:
1. **Intent Service** (`intent_service.py`)
   - Intent extraction using Gemini LLM
   - General response generation
   - Car-related detection

2. **Flow Handlers** (4 handlers)
   - `browse_car_flow.py` - Browse used cars
   - `car_valuation_flow.py` - Car valuation
   - `emi_flow.py` - EMI calculation
   - `service_booking_flow.py` - Service booking

3. **AI Analyzers** (4 analyzers)
   - `browse_car_analyzer.py` - Browse flow analysis
   - `car_valuation_analyzer.py` - Valuation analysis
   - `emi_analyzer.py` - EMI analysis
   - `service_booking_analyzer.py` - Service booking analysis

### Layer 4: State Layer
**Component**: `conversation_state.py`
- **Storage**: In-memory dictionary (extensible to Redis/DB)
- **Purpose**: Track conversation progress and collected data
- **Structure**: `ConversationState` dataclass

### Layer 5: Data Layer
**Component**: `database.py` (PostgreSQL via asyncpg)
- **Purpose**: Data persistence
- **Operations**: CRUD for cars, bookings, services
- **Connection**: Async connection pooling

---

## Orchestrator Pattern

### Main Orchestrator: `process_text_message()`

**Location**: `main.py` (lines 262-482)

**Architecture**:
```
┌─────────────────────────────────────────────────────────────┐
│         ORCHESTRATOR: process_text_message()                │
│                    (main.py)                               │
└──────────────────────┬──────────────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        │              │              │
        ▼              ▼              ▼
┌───────────────┐ ┌──────────────┐ ┌──────────────┐
│ State Check   │ │ Intent       │ │ Flow         │
│ Manager       │ │ Extraction   │ │ Routing      │
└───────┬───────┘ └──────┬───────┘ └──────┬───────┘
        │                │                 │
        └────────────────┼─────────────────┘
                         │
                         ▼
        ┌────────────────────────────────┐
        │   Route to Appropriate Flow     │
        └────────────────────────────────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
        ▼                ▼                ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ Browse Flow  │ │ Valuation    │ │ EMI Flow    │
│ Handler      │ │ Flow Handler │ │ Handler     │
└──────┬───────┘ └──────┬───────┘ └──────┬───────┘
        │                 │                │
        └─────────────────┼────────────────┘
                          │
                          ▼
              ┌──────────────────┐
              │ Response Delivery│
              └──────────────────┘
```

### Orchestration Responsibilities

1. **State-Based Routing**
   ```python
   # Check if user is in active flow
   state = conversation_manager.get_state(user_id)
   if state and state.flow_name == "browse_car":
       return await handle_browse_car_flow(...)
   ```

2. **Intent-Based Routing**
   ```python
   # Extract intent using AI
   intent_result = await extract_intent(message)
   
   # Route based on intent
   if is_service_intent:
       return await handle_service_booking_flow(...)
   elif is_emi_intent:
       return await handle_emi_flow(...)
   # ... etc
   ```

3. **Service Coordination**
   - Coordinates Intent Service
   - Coordinates Flow Handlers
   - Coordinates AI Analyzers
   - Coordinates Database operations
   - Coordinates WhatsApp messaging

4. **Error Handling**
   - Catches errors from all services
   - Provides fallback responses
   - Logs errors for debugging

### Orchestration Decision Tree

```
Message Received
    │
    ▼
Check Active Flow State
    │
    ├─► In Active Flow? ──Yes──► Route to Flow Handler
    │                              │
    │                              └─► Process & Return Response
    │
    └─► No Active Flow
        │
        ▼
    Extract Intent (AI - Gemini)
        │
        ▼
    Check Intent Type
        │
        ├─► Service Intent ──► Service Booking Flow
        ├─► EMI Intent ──────► EMI Flow
        ├─► Valuation Intent ─► Valuation Flow
        ├─► Browse Intent ───► Browse Flow
        │
        └─► General Intent ──► General Response (AI)
```

---

## Component Architecture

### Core Components

```
┌─────────────────────────────────────────────────────────────┐
│                    COMPONENT ARCHITECTURE                    │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  main.py (Orchestrator)                                     │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  FastAPI App                                         │  │
│  │  - Webhook Handlers                                  │  │
│  │  - process_text_message() [ORCHESTRATOR]            │  │
│  │  - send_whatsapp_message()                           │  │
│  └──────────────────────────────────────────────────────┘  │
└──────────────────────┬──────────────────────────────────────┘
                       │
        ┌──────────────┼──────────────┬──────────────┐
        │              │              │              │
        ▼              ▼              ▼              ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ Intent       │ │ Browse Car   │ │ Valuation    │ │ EMI          │
│ Service      │ │ Flow         │ │ Flow         │ │ Flow         │
└──────┬───────┘ └──────┬───────┘ └──────┬───────┘ └──────┬───────┘
       │                 │                │                │
       ▼                 ▼                ▼                ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ Gemini LLM   │ │ Browse       │ │ Valuation    │ │ EMI          │
│ (Intent)     │ │ Analyzer     │ │ Analyzer     │ │ Analyzer     │
│              │ │ (Gemini LLM) │ │ (Gemini LLM) │ │ (Gemini LLM) │
└──────────────┘ └──────┬───────┘ └──────┬───────┘ └──────┬───────┘
                        │                │                │
                        └────────────────┼────────────────┘
                                           │
                        ┌──────────────────┼──────────────────┐
                        │                  │                  │
                        ▼                  ▼                  ▼
              ┌─────────────────┐ ┌──────────────┐ ┌──────────────┐
              │ Conversation    │ │ Database     │ │ WhatsApp API │
              │ State Manager   │ │ (PostgreSQL) │ │ (Meta)      │
              └─────────────────┘ └──────────────┘ └──────────────┘
```

### Component Details

#### 1. Orchestrator (`main.py`)
- **Function**: `process_text_message()`
- **Role**: Central coordinator
- **Responsibilities**:
  - State management coordination
  - Flow routing (state-based + intent-based)
  - Service coordination
  - Error handling
  - Response delivery

#### 2. Intent Service (`intent_service.py`)
- **Functions**:
  - `extract_intent()` - AI-powered intent extraction
  - `generate_response()` - General response generation
  - `is_car_related()` - Car-related detection
- **Technology**: Google Gemini LLM

#### 3. Flow Handlers (4 handlers)
- **Browse Car**: `handle_browse_car_flow()`
- **Valuation**: `handle_car_valuation_flow()`
- **EMI**: `handle_emi_flow()`
- **Service Booking**: `handle_service_booking_flow()`

#### 4. AI Analyzers (4 analyzers)
Each analyzer provides:
- `analyze_*_message()` - Extract information from messages
- `generate_*_response()` - Generate contextual responses
- **Technology**: Google Gemini LLM

#### 5. State Manager (`conversation_state.py`)
- **Storage**: In-memory dictionary
- **Methods**: `get_state()`, `set_state()`, `update_state()`, `clear_state()`

#### 6. Database (`database.py`)
- **Class**: `CarDatabase`
- **Operations**: `search_cars()`, `create_test_drive_booking()`, `create_service_booking()`

---

## Data Flow Architecture

### Complete Message Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    MESSAGE FLOW DIAGRAM                     │
└─────────────────────────────────────────────────────────────┘

1. User sends message via WhatsApp
   │
   ▼
2. Meta WhatsApp API receives message
   │
   ▼
3. Meta sends webhook to FastAPI server
   POST /webhook
   │
   ▼
4. FastAPI verifies webhook signature
   verify_signature()
   │
   ▼
5. FastAPI parses message payload
   handle_message()
   │
   ▼
6. FastAPI routes to process_text_message()
   [ORCHESTRATOR]
   │
   ├─► Check Conversation State
   │   │
   │   ├─► Active Flow? ──Yes──► Route to Flow Handler
   │   │                          │
   │   │                          ▼
   │   │                   Flow Handler
   │   │                   │
   │   │                   ├─► Check Current Step
   │   │                   ├─► Analyze Message (AI)
   │   │                   ├─► Extract Information
   │   │                   ├─► Update State
   │   │                   ├─► Generate Response (AI)
   │   │                   └─► Return Response
   │   │
   │   └─► No Active Flow
   │       │
   │       ▼
   │   Extract Intent (AI - Gemini)
   │   extract_intent()
   │       │
   │       ▼
   │   Route Based on Intent
   │       │
   │       ├─► Service Intent ──► Service Booking Flow
   │       ├─► EMI Intent ──────► EMI Flow
   │       ├─► Valuation Intent ─► Valuation Flow
   │       ├─► Browse Intent ───► Browse Flow
   │       │
   │       └─► General Intent ──► General Response (AI)
   │
   ▼
7. Orchestrator sends response via WhatsApp API
   send_whatsapp_message()
   │
   ▼
8. Meta WhatsApp API delivers message to user
   │
   ▼
9. User receives response
```

### Flow Processing Details

```
Flow Handler Execution:
┌─────────────────────────────────────┐
│ handle_*_flow(user_id, message)     │
└──────────────┬──────────────────────┘
               │
               ▼
    ┌──────────────────────┐
    │ Check State         │
    │ get_state(user_id)  │
    └──────────┬───────────┘
               │
               ▼
    ┌──────────────────────┐
    │ Get Current Step     │
    │ state.step           │
    └──────────┬───────────┘
               │
               ▼
    ┌──────────────────────┐
    │ Analyze Message (AI) │
    │ analyze_*_message() │
    └──────────┬───────────┘
               │
               ▼
    ┌──────────────────────┐
    │ Extract Information  │
    │ - Brand, Model, etc.  │
    └──────────┬───────────┘
               │
               ▼
    ┌──────────────────────┐
    │ Update State         │
    │ update_state()       │
    │ update_data()        │
    └──────────┬───────────┘
               │
               ▼
    ┌──────────────────────┐
    │ Check Step Complete  │
    │ All data collected? │
    └──────────┬───────────┘
               │
               ├─► Yes ──► Move to Next Step
               │          │
               │          ├─► Database Operation (if needed)
               │          │   search_cars() / create_booking()
               │          │
               │          └─► Generate Response
               │
               └─► No ──► Generate Response (ask for missing info)
                          │
                          ▼
                   Return Response
```

---

## Flow Architecture

### 1. Browse Car Flow

**State Machine**:
```
Initial
  │
  ▼
collecting_criteria
  │ (Brand, Budget, Car Type)
  ▼
showing_cars
  │ (User selects car)
  ▼
car_selected
  │ (User chooses action)
  ├─► test_drive_name
  │     │
  │     ▼
  │   test_drive_phone
  │     │
  │     ▼
  │   test_drive_dl
  │     │
  │     ▼
  │   test_drive_location
  │     │
  │     ▼
  │   Booking Created
  │
  └─► (Other actions: EMI, Change criteria)
```

**Steps**:
1. **collecting_criteria**: Collect brand, budget, car type
2. **showing_cars**: Display search results
3. **car_selected**: User selected a car
4. **test_drive_name**: Collect name
5. **test_drive_phone**: Collect phone
6. **test_drive_dl**: Collect driving license info
7. **test_drive_location**: Collect location preference
8. **Complete**: Create booking

### 2. Car Valuation Flow

**State Machine**:
```
Initial
  │
  ▼
collecting_info
  │ (Brand, Model, Year, Fuel Type, Condition)
  ▼
showing_valuation
  │ (Display valuation result)
  ▼
Complete / Restart
```

**Steps**:
1. **collecting_info**: Collect car details
2. **showing_valuation**: Display calculated valuation

### 3. EMI Flow

**State Machine**:
```
Initial
  │
  ▼
selecting_car
  │ (Car selection)
  ▼
down_payment
  │ (Down payment amount)
  ▼
selecting_tenure
  │ (Loan tenure)
  ▼
showing_emi
  │ (Display EMI calculation)
  ▼
Complete / Restart
```

**Steps**:
1. **selecting_car**: Select car for EMI
2. **down_payment**: Collect down payment
3. **selecting_tenure**: Select loan tenure
4. **showing_emi**: Display EMI options and result

### 4. Service Booking Flow

**State Machine**:
```
Initial
  │
  ▼
showing_services
  │ (Service options)
  ▼
collecting_vehicle_details
  │ (Make, Model, Year, Registration)
  ▼
collecting_service_type
  │ (Service type)
  ▼
collecting_customer_details
  │ (Name, Phone)
  ▼
Booking Created
```

**Steps**:
1. **showing_services**: Display service options
2. **collecting_vehicle_details**: Collect vehicle info
3. **collecting_service_type**: Collect service type
4. **collecting_customer_details**: Collect customer info
5. **Complete**: Create service booking

---

## State Management

### State Structure

```python
@dataclass
class ConversationState:
    user_id: str                    # WhatsApp phone number
    flow_name: str                  # "browse_car" | "car_valuation" | "emi" | "service_booking"
    step: str                       # Current step in flow
    data: Dict[str, Any]            # Collected data
    timestamp: datetime             # Last activity timestamp
```

### State Manager

**Class**: `ConversationManager` (Singleton)**

**Methods**:
- `get_state(user_id)` - Get current state
- `set_state(user_id, state)` - Set new state
- `update_state(user_id, **kwargs)` - Update state fields
- `update_data(user_id, **kwargs)` - Update data dictionary
- `clear_state(user_id)` - Clear state

### State Lifecycle

```
1. User sends first message
   │
   ▼
2. Orchestrator checks state
   get_state(user_id)
   │
   ├─► No state exists
   │   │
   │   ▼
   │   Extract intent
   │   │
   │   ▼
   │   Initialize new flow
   │   set_state(user_id, new_state)
   │
   └─► State exists
       │
       ▼
   Continue existing flow
   │
   ▼
3. Flow handler processes message
   │
   ▼
4. Update state with new data
   update_state() / update_data()
   │
   ▼
5. Check if step complete
   │
   ├─► Complete ──► Move to next step
   │
   └─► Incomplete ──► Stay in current step
```

### State Storage

**Current**: In-memory dictionary
```python
_states: Dict[str, ConversationState] = {}
```

**Future Enhancement**: Redis or Database
- Distributed state management
- Persistence across restarts
- Multi-instance support

---

## Database Architecture

### Database: PostgreSQL

**Connection**: Async via `asyncpg`

### Schema

#### 1. Cars Table
```sql
CREATE TABLE cars (
    id SERIAL PRIMARY KEY,
    brand VARCHAR(100),
    model VARCHAR(100),
    variant VARCHAR(100),
    type VARCHAR(50),              -- SUV, Sedan, Hatchback, etc.
    year INTEGER,
    fuel_type VARCHAR(50),         -- Petrol, Diesel, Electric, CNG, Hybrid
    transmission VARCHAR(50),      -- Manual, Automatic
    mileage INTEGER,                -- in kilometers
    price DECIMAL(12, 2),          -- in rupees
    color VARCHAR(50),
    engine_cc INTEGER,
    power_bhp INTEGER,
    seats INTEGER,
    description TEXT,
    registration_number VARCHAR(20),
    status VARCHAR(20) DEFAULT 'available'
);
```

#### 2. Test Drive Bookings Table
```sql
CREATE TABLE test_drive_bookings (
    id SERIAL PRIMARY KEY,
    user_name VARCHAR(200),
    phone_number VARCHAR(20),
    car_id INTEGER REFERENCES cars(id),
    has_dl BOOLEAN,
    location_type VARCHAR(50),      -- showroom, home
    booking_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(20) DEFAULT 'pending'
);
```

#### 3. Service Bookings Table
```sql
CREATE TABLE service_bookings (
    id SERIAL PRIMARY KEY,
    customer_name VARCHAR(200),
    phone_number VARCHAR(20),
    make VARCHAR(100),
    model VARCHAR(100),
    year INTEGER,
    registration_number VARCHAR(20),
    service_type VARCHAR(100),      -- Regular Service, Major Service, etc.
    booking_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(20) DEFAULT 'pending'
);
```

### Database Operations

**Class**: `CarDatabase`

**Methods**:
- `init_schema()` - Initialize database schema
- `connect()` - Create connection pool
- `close()` - Close connections
- `get_available_brands()` - Get distinct brands
- `get_available_car_types()` - Get distinct car types
- `search_cars()` - Search cars by criteria
- `get_car_by_id()` - Get car by ID
- `create_test_drive_booking()` - Create test drive booking
- `create_service_booking()` - Create service booking

---

## API Architecture

### FastAPI Application

**File**: `main.py`

**Endpoints**:

#### `GET /`
Health check endpoint
- **Response**: `{"status": "ok", "message": "WhatsApp Webhook API is running"}`

#### `GET /webhook`
Webhook verification (Meta callback)
- **Query Parameters**:
  - `hub.mode` - Should be "subscribe"
  - `hub.verify_token` - Verification token
  - `hub.challenge` - Challenge string
- **Response**: Challenge string (200) or 403

#### `POST /webhook`
Main webhook endpoint
- **Headers**: `X-Hub-Signature-256` (optional, for signature verification)
- **Body**: Meta webhook payload (JSON)
- **Response**: `{"status": "success"}`

### Internal Functions

#### `process_text_message(from_number, text, message_id)`
Main message processing orchestrator
- **Input**: User phone number, message text, message ID
- **Process**:
  1. Check conversation state
  2. Route to flow or extract intent
  3. Process message
  4. Generate response
  5. Send response
- **Output**: None (sends response directly)

#### `send_whatsapp_message(to, message, **kwargs)`
Send message via Meta WhatsApp API
- **Input**: Recipient phone number, message text
- **Process**: HTTP POST to Meta Graph API
- **Output**: API response JSON

---

## AI Integration Architecture

### Google Gemini API Integration

**Purpose**: Intelligent message understanding and response generation

**Usage Points**:

1. **Intent Extraction** (`intent_service.py`)
   - **Function**: `extract_intent()`
   - **Input**: User message
   - **Output**: `IntentResult` (intent, summary, confidence, entities)
   - **Model**: Gemini (configurable)

2. **Message Analysis** (All analyzers)
   - **Function**: `analyze_*_message()`
   - **Input**: Message + conversation context
   - **Output**: Extracted entities (brand, model, budget, etc.)
   - **Model**: Gemini (configurable)

3. **Response Generation** (All analyzers)
   - **Function**: `generate_*_response()`
   - **Input**: Message + context + analysis result
   - **Output**: Natural, contextual response text
   - **Model**: Gemini (configurable)

### API Configuration

- **Base URL**: `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`
- **Authentication**: API Key (`GOOGLE_API_KEY`)
- **Timeout**: 12 seconds (configurable)
- **Model**: `gemini-1.5-flash` (default, configurable via `GEMINI_MODEL`)

### AI Flow

```
User Message
    │
    ▼
Build Prompt
    │
    ├─► System Prompt (context-aware)
    ├─► User Message
    ├─► Conversation Context
    └─► Available Options (brands, types, etc.)
    │
    ▼
Send to Gemini API
    │
    ├─► Success ──► Parse Response
    │                │
    │                └─► Extract Information
    │
    └─► Error ──► Fallback Extraction
                   │
                   └─► Use Regex/Simple Logic
```

---

## Error Handling Architecture

### Exception Hierarchy

```
Exception
├── IntentExtractionError          # Intent extraction failures
├── ResponseGenerationError        # Response generation failures
├── BrowseCarAnalysisError         # Browse car analysis failures
├── CarValuationAnalysisError      # Valuation analysis failures
├── EMIAnalysisError              # EMI analysis failures
└── ServiceBookingAnalysisError   # Service booking analysis failures
```

### Error Handling Strategy

**Pattern**: Try-Catch with Fallback

```python
try:
    # Primary operation (AI-powered)
    result = await ai_operation()
except SpecificError as e:
    # Log error
    print(f"Error: {e}")
    # Fallback to simple extraction
    result = fallback_extraction()
except Exception as e:
    # Generic error handling
    print(f"Unexpected error: {e}")
    return fallback_response()
```

### Error Handling Locations

1. **Orchestrator Level** (`main.py`)
   - Catches flow handler errors
   - Provides fallback routing
   - Logs errors

2. **Flow Handler Level** (All flows)
   - Catches analyzer errors
   - Falls back to simple extraction
   - Provides fallback responses

3. **Analyzer Level** (All analyzers)
   - Catches Gemini API errors
   - Returns error information
   - Allows fallback

4. **Database Level** (`database.py`)
   - Catches database errors
   - Returns None/empty results
   - Logs errors

### Error Flow

```
Operation
    │
    ├─► Success ──► Continue Processing
    │
    └─► Error
        │
        ├─► Log Error
        │
        ├─► Try Fallback
        │   │
        │   ├─► Fallback Success ──► Continue
        │   │
        │   └─► Fallback Fails ──► Return Error Response
        │
        └─► Return User-Friendly Error Message
```

---

## Security Architecture

### Webhook Security

1. **Signature Verification**
   - HMAC-SHA256 signature validation
   - Verifies request authenticity
   - Prevents unauthorized access

2. **Token Verification**
   - Verify token for webhook setup
   - Prevents unauthorized webhook registration

3. **HTTPS**
   - Required in production
   - Encrypts data in transit

### Data Security

1. **Input Validation**
   - Pydantic models for validation
   - Type checking
   - Sanitization

2. **SQL Injection Prevention**
   - Parameterized queries (asyncpg)
   - No string concatenation in SQL

3. **Error Message Sanitization**
   - No sensitive data in error messages
   - Generic error messages to users

4. **Environment Variables**
   - Sensitive data in `.env`
   - Not committed to version control

### Security Layers

```
┌─────────────────────────────────────┐
│  Layer 1: Network Security         │
│  - HTTPS/TLS                       │
│  - Firewall Rules                  │
└─────────────────┬───────────────────┘
                  │
┌─────────────────▼───────────────────┐
│  Layer 2: API Security              │
│  - Signature Verification           │
│  - Token Validation                 │
└─────────────────┬───────────────────┘
                  │
┌─────────────────▼───────────────────┐
│  Layer 3: Application Security      │
│  - Input Validation                 │
│  - SQL Injection Prevention         │
└─────────────────┬───────────────────┘
                  │
┌─────────────────▼───────────────────┐
│  Layer 4: Data Security             │
│  - Environment Variables             │
│  - Error Sanitization                │
└─────────────────────────────────────┘
```

---

## Technology Stack

### Backend Framework
- **FastAPI** 0.115.0+ - Modern, fast web framework
- **Uvicorn** 0.32.0+ - ASGI server
- **Python** 3.8+ - Programming language

### AI/ML Services
- **Google Gemini API** - LLM for AI capabilities
- **Model**: `gemini-1.5-flash` (configurable)

### Database
- **PostgreSQL** - Relational database
- **asyncpg** 0.29.0+ - Async PostgreSQL driver

### External APIs
- **Meta WhatsApp Business API** - WhatsApp messaging
- **Google Gemini API** - AI capabilities

### Libraries
- **httpx** 0.27.0+ - Async HTTP client
- **pydantic** 2.10.0+ - Data validation
- **python-dotenv** 1.0.0+ - Environment management
- **pandas** 2.0.0+ - Data processing
- **openpyxl** 3.1.0+ - Excel file generation

---

## Design Patterns

### 1. Orchestrator Pattern ✅
**Implementation**: `process_text_message()` in `main.py`
- **Purpose**: Central coordination of all services and flows
- **Benefits**: Single point of control, easy routing, centralized error handling

### 2. State Machine Pattern ✅
**Implementation**: Each flow handler
- **Purpose**: Manage conversation progression through distinct states
- **Benefits**: Clear flow control, predictable behavior, easy to extend

### 3. Strategy Pattern ✅
**Implementation**: Different analyzers for different flows
- **Purpose**: Interchangeable algorithms for message analysis
- **Benefits**: Flexibility, easy to add new flows, separation of concerns

### 4. Repository Pattern ✅
**Implementation**: `CarDatabase` class
- **Purpose**: Abstract database operations
- **Benefits**: Testability, maintainability, easy to swap implementations

### 5. Template Method Pattern ✅
**Implementation**: Similar structure across all flows
- **Purpose**: Define skeleton of algorithm
- **Benefits**: Code reuse, consistency, easy to maintain

### 6. Factory Pattern ✅
**Implementation**: Response generation
- **Purpose**: Create different response types based on context
- **Benefits**: Flexible response creation, context-aware responses

---

## Module Structure

```
final_autosherpa/
│
├── main.py                          # FastAPI app, orchestrator, webhook handlers
├── intent_service.py                # Intent extraction & general responses
├── conversation_state.py             # State management (in-memory)
├── database.py                      # Database models & operations
│
├── browse_car_flow.py                # Browse car flow handler
├── browse_car_analyzer.py            # AI analyzer for browse flow
│
├── car_valuation_flow.py             # Car valuation flow handler
├── car_valuation_analyzer.py         # AI analyzer for valuation flow
│
├── emi_flow.py                       # EMI calculation flow handler
├── emi_analyzer.py                   # AI analyzer for EMI flow
│
├── service_booking_flow.py           # Service booking flow handler
├── service_booking_analyzer.py       # AI analyzer for service booking
│
├── requirements.txt                  # Python dependencies
├── README.md                         # Project documentation
├── ARCHITECTURE.md                   # Architecture documentation
├── ORCHESTRATOR_PATTERN.md           # Orchestrator pattern details
│
└── Implementation Docs/
    ├── BROWSE_CAR_IMPLEMENTATION.md
    ├── CAR_VALUATION_IMPLEMENTATION.md
    └── EMI_FLOW_IMPLEMENTATION.md
```

### Module Dependencies

```
main.py
├── intent_service.py
├── conversation_state.py
├── database.py
├── browse_car_flow.py
│   └── browse_car_analyzer.py
├── car_valuation_flow.py
│   └── car_valuation_analyzer.py
├── emi_flow.py
│   └── emi_analyzer.py
└── service_booking_flow.py
    └── service_booking_analyzer.py
```

---

## Deployment Architecture

### Production Deployment

```
┌─────────────────────────────────────────┐
│         Load Balancer (Nginx)          │
│         - SSL Termination               │
│         - Request Routing                │
└──────────────────┬──────────────────────┘
                    │
        ┌───────────┴───────────┐
        │                       │
        ▼                       ▼
┌──────────────┐      ┌──────────────┐
│ FastAPI      │      │ FastAPI      │
│ Instance 1   │      │ Instance 2   │
│ (Uvicorn)    │      │ (Uvicorn)    │
└──────┬───────┘      └──────┬───────┘
       │                     │
       └──────────┬──────────┘
                  │
                  ▼
         ┌─────────────────┐
         │   PostgreSQL    │
         │   (Primary)     │
         │   Connection    │
         │   Pooling       │
         └─────────────────┘
                  │
                  ▼
         ┌─────────────────┐
         │   PostgreSQL    │
         │   (Replica)     │
         │   (Read-only)    │
         └─────────────────┘
```

### Deployment Components

1. **Web Server**: Nginx (reverse proxy)
2. **Application Server**: Uvicorn (ASGI)
3. **Application**: FastAPI (Python)
4. **Database**: PostgreSQL (primary + replica)
5. **State Storage**: In-memory (can be Redis)

### Environment Setup

```bash
# Production Environment
- Python 3.8+
- PostgreSQL 12+
- Nginx (reverse proxy)
- SSL Certificate (Let's Encrypt)
- Environment variables configured
```

---

## Scalability & Performance

### Current Architecture

- **State Storage**: In-memory (single server)
- **Database**: PostgreSQL with connection pooling
- **API**: FastAPI (async, handles concurrent requests)
- **AI**: Google Gemini API (external, scalable)

### Performance Characteristics

- **Async/Await**: Non-blocking I/O operations
- **Connection Pooling**: Database connection reuse
- **Caching**: Brand/type lists cached in memory
- **Error Handling**: Fast fallback mechanisms

### Scalability Enhancements

1. **State Management**
   - Current: In-memory
   - Future: Redis for distributed state

2. **Database**
   - Current: Single PostgreSQL instance
   - Future: Read replicas, connection pooling

3. **Application**
   - Current: Single instance
   - Future: Multiple instances behind load balancer

4. **Caching**
   - Current: In-memory cache for brands/types
   - Future: Redis cache for frequently accessed data

5. **Message Queue**
   - Current: Synchronous processing
   - Future: Async message queue (RabbitMQ/Kafka)

---

## Configuration

### Environment Variables

```bash
# Meta WhatsApp API (Required)
PHONE_NUMBER_ID=your_phone_number_id
ACCESS_TOKEN=your_access_token
VERIFY_TOKEN=your_verify_token
WEBHOOK_SECRET=your_webhook_secret        # Optional but recommended
APP_SECRET=your_app_secret                # Optional

# Google Gemini API (Required)
GOOGLE_API_KEY=your_google_api_key
GEMINI_MODEL=gemini-1.5-flash            # Optional, defaults to gemini-1.5-flash

# Database (Required)
DATABASE_URL=postgresql://user:password@host:port/database

# Server (Optional)
PORT=8000                                 # Default: 8000
```

---

## Monitoring & Logging

### Current Logging

- Console output for debugging
- Error messages with stack traces
- Status updates for webhook events
- Print statements for key operations

### Recommended Enhancements

1. **Structured Logging**
   - Use `structlog` or `loguru`
   - JSON format for log aggregation
   - Log levels (DEBUG, INFO, WARNING, ERROR)

2. **Log Aggregation**
   - ELK stack (Elasticsearch, Logstash, Kibana)
   - CloudWatch (AWS)
   - Datadog

3. **Metrics**
   - Prometheus for metrics collection
   - Grafana for visualization
   - Track: request rate, error rate, response time

4. **Error Tracking**
   - Sentry for error tracking
   - Track exceptions and stack traces
   - Alert on critical errors

5. **Performance Monitoring**
   - APM tools (New Relic, Datadog APM)
   - Track slow queries
   - Monitor API response times

---

## Future Enhancements

### Planned Features

1. **Multi-language Support**
   - Support for regional languages (Hindi, Kannada, etc.)
   - Language detection
   - Localized responses

2. **Voice Messages**
   - Process voice messages
   - Speech-to-text conversion
   - Voice response generation

3. **Image Recognition**
   - Analyze car images
   - Extract car details from photos
   - Damage assessment

4. **Analytics Dashboard**
   - Track conversations
   - Monitor conversions
   - User behavior analysis

5. **A/B Testing**
   - Test different response strategies
   - Optimize conversion rates
   - Measure effectiveness

6. **Integration**
   - CRM integration
   - Inventory management systems
   - Payment gateways

7. **Scheduled Messages**
   - Reminders
   - Follow-ups
   - Promotional messages

---

## Conclusion

AutoSherpa uses a **layered architecture with an orchestrator pattern** that provides:

✅ **Clear Separation of Concerns** - Each layer has distinct responsibilities  
✅ **Scalable Design** - Can scale horizontally and vertically  
✅ **Maintainable Code** - Modular structure, easy to extend  
✅ **Robust Error Handling** - Comprehensive error handling with fallbacks  
✅ **AI-Powered Intelligence** - Google Gemini for natural conversations  
✅ **Production-Ready** - Security, monitoring, and deployment considerations

The architecture is designed to be **extensible, maintainable, and scalable** while providing an excellent user experience through intelligent conversation handling.

---

*This architecture document provides a complete overview of the AutoSherpa system architecture.*

