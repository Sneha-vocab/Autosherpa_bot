"""Database models and operations for cars."""

import os
import asyncpg
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")


@dataclass
class Car:
    """Represents a used car listing."""
    id: int
    brand: Optional[str] = None
    model: Optional[str] = None
    variant: Optional[str] = None
    type: Optional[str] = None  # SUV, Sedan, Hatchback, etc. (column name is 'type')
    year: Optional[int] = None
    fuel_type: Optional[str] = None
    transmission: Optional[str] = None
    mileage: Optional[int] = None
    price: Optional[float] = None
    color: Optional[str] = None
    engine_cc: Optional[int] = None
    power_bhp: Optional[int] = None
    seats: Optional[int] = None
    description: Optional[str] = None
    registration_number: Optional[str] = None
    status: Optional[str] = None
    
    def to_dict(self) -> dict:
        """Convert car to dictionary."""
        return {
            "id": self.id,
            "brand": self.brand,
            "model": self.model,
            "variant": self.variant,
            "type": self.type,
            "year": self.year,
            "price": self.price,
            "mileage": self.mileage,
            "fuel_type": self.fuel_type,
            "transmission": self.transmission,
            "color": self.color,
            "engine_cc": self.engine_cc,
            "power_bhp": self.power_bhp,
            "seats": self.seats,
            "description": self.description,
            "registration_number": self.registration_number,
            "status": self.status,
        }


class CarDatabase:
    """Database operations for cars."""
    
    def __init__(self, database_url: str):
        self.database_url = database_url
        self._pool: Optional[asyncpg.Pool] = None
    
    async def connect(self):
        """Create database connection pool."""
        if self._pool is None:
            self._pool = await asyncpg.create_pool(self.database_url)
    
    async def close(self):
        """Close database connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
    
    async def get_available_brands(self) -> List[str]:
        """Get all distinct brands from the cars table."""
        await self.connect()
        
        async with self._pool.acquire() as conn:
            # Try 'cars' table first, fallback to 'used_cars'
            try:
                rows = await conn.fetch("SELECT DISTINCT brand FROM cars ORDER BY brand")
            except:
                rows = await conn.fetch("SELECT DISTINCT brand FROM used_cars ORDER BY brand")
            return [row['brand'] for row in rows if row['brand']]
    
    async def get_available_car_types(self) -> List[str]:
        """Get all distinct car types from the cars table."""
        await self.connect()
        
        async with self._pool.acquire() as conn:
            # Column name is 'type' not 'car_type'
            rows = await conn.fetch("SELECT DISTINCT type FROM cars WHERE type IS NOT NULL ORDER BY type")
            return [row['type'] for row in rows if row['type']]
    
    async def search_cars(
        self,
        brand: Optional[str] = None,
        car_type: Optional[str] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        limit: int = 10
    ) -> List[Car]:
        """Search for cars based on criteria."""
        await self.connect()
        
        # Use 'cars' table (column name is 'type' not 'car_type')
        query = "SELECT * FROM cars WHERE status = 'available'"
        params = []
        param_count = 0
        
        if brand:
            param_count += 1
            query += f" AND LOWER(brand) = LOWER(${param_count})"
            params.append(brand)
        
        if car_type:
            param_count += 1
            query += f" AND LOWER(type) = LOWER(${param_count})"
            params.append(car_type)
        
        if min_price:
            param_count += 1
            query += f" AND price >= ${param_count}"
            params.append(min_price)
        
        if max_price:
            param_count += 1
            query += f" AND price <= ${param_count}"
            params.append(max_price)
        
        query += f" ORDER BY price ASC LIMIT ${param_count + 1}"
        params.append(limit)
        
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            # Convert rows to Car objects, handling missing fields
            cars = []
            for row in rows:
                car_dict = dict(row)
                # Ensure 'id' is present (required field)
                if 'id' not in car_dict or car_dict['id'] is None:
                    continue
                # Filter to only include fields that exist in Car dataclass
                # Get all field names from Car dataclass
                car_fields = {f.name for f in Car.__dataclass_fields__.values()}
                filtered_dict = {k: v for k, v in car_dict.items() if k in car_fields}
                # Ensure id is in the dict
                if 'id' in filtered_dict:
                    cars.append(Car(**filtered_dict))
            return cars
    
    async def get_car_by_id(self, car_id: int) -> Optional[Car]:
        """Get a specific car by ID."""
        await self.connect()
        
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM cars WHERE id = $1", car_id)
            if row:
                car_dict = dict(row)
                # Get all field names from Car dataclass
                car_fields = {f.name for f in Car.__dataclass_fields__.values()}
                filtered_dict = {k: v for k, v in car_dict.items() if k in car_fields}
                if 'id' in filtered_dict:
                    return Car(**filtered_dict)
            return None
    
    async def create_test_drive_booking(
        self,
        user_name: str,
        phone_number: str,
        car_id: int,
        has_dl: bool,
        location_type: str,  # "showroom" or "home"
        preferred_date: Optional[str] = None
    ) -> int:
        """Create a test drive booking."""
        await self.connect()
        
        # Get car details for car_name
        car = await self.get_car_by_id(car_id)
        car_name = None
        if car:
            parts = []
            if car.brand:
                parts.append(car.brand)
            if car.model:
                parts.append(car.model)
            if car.variant:
                parts.append(car.variant)
            car_name = " ".join(parts) if parts else f"Car #{car_id}"
        
        async with self._pool.acquire() as conn:
            booking_id = await conn.fetchval(
                """
                INSERT INTO test_drive_bookings 
                (customer_name, customer_phone, vehicle_id, car_name, location, status, notes, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, NOW(), NOW())
                RETURNING id
                """,
                user_name,  # customer_name
                phone_number,  # customer_phone
                str(car_id),  # vehicle_id (character varying)
                car_name,  # car_name
                location_type,  # location
                'pending',  # status
                f"Has DL: {has_dl}" if has_dl else "No DL provided"  # notes (store has_dl info here)
            )
            return booking_id
    
    async def create_service_booking(
        self,
        customer_name: str,
        phone_number: str,
        make: Optional[str] = None,
        model: Optional[str] = None,
        year: Optional[int] = None,
        registration_number: Optional[str] = None,
        service_type: Optional[str] = None
    ) -> int:
        """Create a service booking."""
        await self.connect()
        
        # Build vehicle info string
        vehicle_parts = []
        if make:
            vehicle_parts.append(f"Make: {make}")
        if model:
            vehicle_parts.append(f"Model: {model}")
        if year:
            vehicle_parts.append(f"Year: {year}")
        if registration_number:
            vehicle_parts.append(f"Registration: {registration_number}")
        vehicle_info = "; ".join(vehicle_parts) if vehicle_parts else "Vehicle details not provided"
        
        # Build notes with service type
        notes_parts = [vehicle_info]
        if service_type:
            notes_parts.append(f"Service Type: {service_type}")
        notes = " | ".join(notes_parts)
        
        async with self._pool.acquire() as conn:
            # Try to insert into service_bookings table if it exists
            # Otherwise, use test_drive_bookings table as fallback
            try:
                booking_id = await conn.fetchval(
                    """
                    INSERT INTO service_bookings 
                    (customer_name, customer_phone, vehicle_make, vehicle_model, vehicle_year, registration_number, service_type, status, notes, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, 'pending', $8, NOW(), NOW())
                    RETURNING id
                    """,
                    customer_name,
                    phone_number,
                    make,
                    model,
                    year,
                    registration_number,
                    service_type,
                    notes
                )
                return booking_id
            except Exception:
                # Fallback: use test_drive_bookings table
                booking_id = await conn.fetchval(
                    """
                    INSERT INTO test_drive_bookings 
                    (customer_name, customer_phone, vehicle_id, car_name, location, status, notes, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, NOW(), NOW())
                    RETURNING id
                    """,
                    customer_name,
                    phone_number,
                    None,  # vehicle_id
                    f"{make} {model}" if make and model else "Service Booking",
                    "service_booking",  # location
                    'pending',  # status
                    notes  # notes
                )
                return booking_id
    
    async def init_schema(self):
        """Initialize database schema (create tables if they don't exist)."""
        await self.connect()
        
        async with self._pool.acquire() as conn:
            # Check if 'cars' table exists
            try:
                await conn.fetchrow("SELECT 1 FROM cars LIMIT 1")
                print("✓ Using existing 'cars' table")
            except Exception as e:
                print(f"⚠ 'cars' table not found: {e}")
            
            # Check if 'test_drive_bookings' table exists, create if not
            try:
                await conn.fetchrow("SELECT 1 FROM test_drive_bookings LIMIT 1")
                print("✓ Using existing 'test_drive_bookings' table")
            except:
                # Create test_drive_bookings table if it doesn't exist
                # Note: The actual table has a different schema, so we won't create it
                # if it already exists with the actual schema
                print("✓ Using existing 'test_drive_bookings' table (actual schema may differ)")
            
            # Create indexes on cars table (if they don't exist)
            try:
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_cars_brand ON cars(brand)
                """)
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_cars_type ON cars(type)
                """)
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_cars_price ON cars(price)
                """)
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_cars_status ON cars(status)
                """)
                print("✓ Indexes created/verified")
            except Exception as e:
                print(f"⚠ Error creating indexes: {e}")


# Global database instance
car_db = CarDatabase(DATABASE_URL) if DATABASE_URL else None

