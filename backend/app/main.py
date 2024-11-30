from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Set
from enum import Enum
from datetime import datetime, timedelta
import random
import uuid
import openai
import os
from dotenv import load_dotenv
import json

import logging

# Create a logger
logger = logging.getLogger(__name__)

# Set the logging level
logger.setLevel(logging.INFO)

# Create a file handler and a stream handler
file_handler = logging.FileHandler('app.log')
stream_handler = logging.StreamHandler()

# Create a formatter and add it to the handlers
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
stream_handler.setFormatter(formatter)

# Add the handlers to the logger
logger.addHandler(file_handler)
logger.addHandler(stream_handler)



load_dotenv()

app = FastAPI(title="AI Food Game Backend")
client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Combined Enums
class ServeOrderRequest(BaseModel):
    items_served: List[str]
    
class RestrictionType(str, Enum):
    GLUTEN = "GLUTEN"
    LACTOSE = "LACTOSE"
    VEGAN = "VEGAN"
    VEGETARIAN = "VEGETARIAN"
    HALAL = "HALAL"
    KOSHER = "KOSHER"
    NUT = "NUT"

class ConsequenceType(str, Enum):
    REFUND = "REFUND"
    TOILET_EXPLOSION = "TOILET_EXPLOSION"
    ANGER = "ANGER"
    FLATULENCE = "FLATULENCE"
    RELIGIOUS_OFFENSE = "RELIGIOUS_OFFENSE"
    SEIZURE = "SEIZURE"

class OrderStatus(str, Enum):
    PENDING = "PENDING"
    SERVED = "SERVED"
    FAILED = "FAILED"

class PersonalityTrait(str, Enum):
    PATIENT = "PATIENT"
    IMPATIENT = "IMPATIENT"
    PICKY = "PICKY"
    GENEROUS = "GENEROUS"
    INFLUENCER = "INFLUENCER"
    KAREN = "KAREN"
    REGULAR = "REGULAR"
    FOODIE = "FOODIE"
    HEALTH_CONSCIOUS = "HEALTH_CONSCIOUS"

class MoodState(str, Enum):
    HAPPY = "HAPPY"
    NEUTRAL = "NEUTRAL"
    ANNOYED = "ANNOYED"
    ANGRY = "ANGRY"
    HANGRY = "HANGRY"

class CustomerTier(str, Enum):
    FIRST_TIME = "FIRST_TIME"
    REGULAR = "REGULAR"
    FREQUENT = "FREQUENT"
    VIP = "VIP"

# Combined Models
class MenuItem(BaseModel):
    name: str
    description: str
    price: float
    restrictions: List[RestrictionType]
    preparation_time: int

class CustomerReview(BaseModel):
    rating: int
    comment: str
    timestamp: datetime
    order_id: str
    incident_reported: bool = False

class CustomerProfile(BaseModel):
    id: str
    name: str
    personality_traits: List[PersonalityTrait]
    current_mood: MoodState = MoodState.NEUTRAL
    dietary_restrictions: List[RestrictionType]
    visit_history: List[datetime] = []
    favorite_items: List[str] = []
    disliked_items: List[str] = []
    average_spending: float = 0.0
    total_spent: float = 0.0
    reviews_given: List[CustomerReview] = []
    current_tier: CustomerTier = CustomerTier.FIRST_TIME
    patience_threshold: int = Field(default=5, ge=1, le=10)
    tip_tendency: float = Field(default=0.15, ge=0, le=0.5)
    influence_score: int = Field(default=1, ge=1, le=100)
    last_visit: Optional[datetime] = None
    return_probability: float = 0.5
    satisfaction_history: List[float] = []

class Order(BaseModel):
    id: str
    customer_id: str
    customer_profile: CustomerProfile
    restrictions: List[RestrictionType]
    items_ordered: List[str]
    status: OrderStatus
    created_at: datetime
    wait_time: int = 0
    total_price: float = 0.0

class GameState(BaseModel):
    player_id: str
    score: int = 0
    active_orders: List[Order] = []
    completed_orders: int = 0
    mistakes: List[Dict] = []
    money: float = 1000.0
    reputation: float = 50.0
    customers: Dict[str, CustomerProfile] = {}
    daily_customers_served: int = 0
    total_customers_served: int = 0

# In-memory storage
games: Dict[str, GameState] = {}
menu_cache: Dict[str, List[MenuItem]] = {}
consequence_cache: Dict[str, Dict] = {}

class CustomerManager:
    def __init__(self):
        self.personality_weights = {
            PersonalityTrait.KAREN: {
                "complaint_chance": 0.8,
                "return_rate": 0.3,
                "tip_modifier": -0.5,
                "reputation_impact": -2.0,
            },
            PersonalityTrait.INFLUENCER: {
                "complaint_chance": 0.4,
                "return_rate": 0.6,
                "tip_modifier": 0.2,
                "reputation_impact": 3.0,
            },
            # Add other personality weights...
        }

    async def generate_customer_profile(self) -> CustomerProfile:
        """Generate a new customer profile using AI"""
        prompt = """Generate a unique restaurant customer profile with:
        1. Two personality traits
        2. 1-2 dietary restrictions
        3. A patience level (1-10)
        4. A tip tendency (0-0.5)
        
        Respond in JSON format."""

        response = await client.chat.completions.create(
            model="gpt-4-1106-preview",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "You are creating customer profiles for a restaurant game"},
                {"role": "user", "content": prompt}
            ]
        )
        
        data = response.choices[0].message.content
        
        return CustomerProfile(
            id=str(uuid.uuid4()),
            name=f"Customer_{random.randint(1000, 9999)}",
            personality_traits=data["personality_traits"],
            dietary_restrictions=data["dietary_restrictions"],
            patience_threshold=data["patience_level"],
            tip_tendency=data["tip_tendency"]
        )

    def calculate_satisfaction(
        self,
        customer: CustomerProfile,
        order_result: Dict,
        wait_time: int
    ) -> float:
        base_satisfaction = 70.0
        
        # Personality impacts
        if PersonalityTrait.IMPATIENT in customer.personality_traits:
            base_satisfaction -= (wait_time / customer.patience_threshold) * 10
        
        # Order accuracy
        if order_result.get("perfect", False):
            base_satisfaction += 20
        elif order_result.get("has_mistakes", False):
            base_satisfaction -= 30
        
        # Dietary violations
        if order_result.get("dietary_violation", False):
            base_satisfaction = 0
        
        return max(0, min(100, base_satisfaction))

# Enhanced API functions

async def generate_menu_items(restrictions: List[RestrictionType]) -> List[MenuItem]:
    """Generate menu items using AI based on dietary restrictions"""
    restrictions_str = ", ".join([r.value for r in restrictions])
    
    prompt = f"""Generate 3 creative food items that would be safe for someone with these dietary restrictions: {restrictions_str}.
    For each item, provide:
    1. A creative name
    2. A brief description
    3. A reasonable price
    4. Preparation time in minutes
    
    Return ONLY a valid JSON array in this exact format:
    {{
        "items": [
            {{
                "name": "item name",
                "description": "brief description",
                "price": 0.00,
                "preparation_time": 0
            }}
        ]
    }}"""

    try:
        response = await client.chat.completions.create(
            model="gpt-4-1106-preview",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "You are a creative chef who specializes in dietary restrictions. You only respond with valid JSON."},
                {"role": "user", "content": prompt}
            ]
        )
        
        content = response.choices[0].message.content
        data = json.loads(content)  # Parse the JSON response
        
        menu_items = []
        for item in data.get("items", []):
            menu_items.append(MenuItem(
                name=item["name"],
                description=item["description"],
                price=float(item["price"]),
                restrictions=restrictions,
                preparation_time=int(item["preparation_time"])
            ))
        
        return menu_items
    except Exception as e:
        print(f"Error generating menu items: {e}")
        print(f"API Response: {response.choices[0].message.content if response else 'No response'}")
        # Return some fallback menu items
        return [
            MenuItem(
                name="Safe Default Item",
                description="A simple item that meets all dietary restrictions",
                price=9.99,
                restrictions=restrictions,
                preparation_time=10
            )
        ]

async def generate_consequence(violation: RestrictionType) -> Dict:
    """Generate creative consequence using AI"""
    prompt = f"""Generate a creative and humorous consequence for serving food that violates a {violation.value} dietary restriction.
    Include:
    1. A funny description of what happens
    2. A visual effect for the game
    3. A sound effect suggestion
    4. A monetary penalty
    5. A score impact
    
    Return ONLY a valid JSON object in this exact format:
    {{
        "consequence": {{
            "description": "funny description here",
            "visual_effect": "effect name",
            "sound_effect": "sound name",
            "money_impact": -50,
            "score_impact": -100,
            "reputation_impact": -5
        }}
    }}"""

    try:
        response = await client.chat.completions.create(
            model="gpt-4-1106-preview",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "You are a creative game designer specializing in humorous consequences. You only respond with valid JSON."},
                {"role": "user", "content": prompt}
            ]
        )
        
        content = response.choices[0].message.content
        data = json.loads(content)  # Parse the JSON response
        
        return data["consequence"]
    except Exception as e:
        print(f"Error generating consequence: {e}")
        print(f"API Response: {response.choices[0].message.content if response else 'No response'}")
        # Return a fallback consequence
        return {
            "description": f"Customer is unhappy about the {violation.value} violation",
            "visual_effect": "angry_customer",
            "sound_effect": "complaint",
            "money_impact": -50,
            "score_impact": -100,
            "reputation_impact": -5
        }

# Initialize customer manager
customer_manager = CustomerManager()

# Enhanced API Endpoints
@app.post("/game/start")
async def start_game():
    game_id = str(uuid.uuid4())
    games[game_id] = GameState(player_id=game_id)
    return {"game_id": game_id}

@app.post("/game/{game_id}/generate-order")
async def generate_order(game_id: str):
    if game_id not in games:
        raise HTTPException(status_code=404, detail="Game not found")
    
    game = games[game_id]
    
    # Generate customer profile
    customer = await customer_manager.generate_customer_profile()
    game.customers[customer.id] = customer
    
    # Generate menu items for restrictions
    menu_key = ",".join(sorted([r.value for r in customer.dietary_restrictions]))
    if menu_key not in menu_cache:
        menu_cache[menu_key] = await generate_menu_items(customer.dietary_restrictions)
    
    menu_items = menu_cache[menu_key]
    
    # Create order
    order = Order(
        id=str(uuid.uuid4()),
        customer_id=customer.id,
        customer_profile=customer,
        restrictions=customer.dietary_restrictions,
        items_ordered=[item.name for item in menu_items],
        status=OrderStatus.PENDING,
        created_at=datetime.now(),
        total_price=sum(item.price for item in menu_items)
    )
    
    game.active_orders.append(order)
    
    return {
        "order": order,
        "menu_items": menu_items,
        "customer": customer
    }



@app.post("/game/{game_id}/serve-order/{order_id}")
async def serve_order(
    game_id: str,
    order_id: str,
    request: ServeOrderRequest
):
    """Handle serving an order to a customer with complete error handling and consequence generation"""
    try:
        # Validate game exists
        if game_id not in games:
            raise HTTPException(status_code=404, detail="Game not found")
        
        game = games[game_id]
        
        # Find the order
        order = next((o for o in game.active_orders if o.id == order_id), None)
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        
        # Calculate wait time
        wait_time = (datetime.now() - order.created_at).seconds // 60
        order.wait_time = wait_time
        
        # Get customer profile
        customer = game.customers.get(order.customer_id)
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")
        
        # Check for dietary violations
        violations = []
        for item in request.items_served:
            if item not in order.items_ordered:
                violations.append("WRONG_ITEM")
            # Add additional violation checks here
        
        # Random violation for demo (replace with actual logic)
        if random.random() < 0.3:
            violations.append(random.choice(order.restrictions))
        
        if violations:
            # Handle violation
            violation = violations[0]  # Take first violation
            
            try:
                # Get or generate consequence
                if violation not in consequence_cache:
                    consequence = await generate_consequence(violation)
                    consequence_cache[violation] = consequence
                else:
                    consequence = consequence_cache[violation]
                
                # Calculate satisfaction
                satisfaction = max(0, min(100, 50 - len(violations) * 20))
                
                # Update customer profile
                customer.satisfaction_history.append(satisfaction)
                if satisfaction < 30:
                    customer.reviews_given.append(
                        CustomerReview(
                            rating=max(1, int(satisfaction/20)),
                            comment=consequence["description"],
                            timestamp=datetime.now(),
                            order_id=order_id,
                            incident_reported=True
                        )
                    )
                
                # Update game state
                game.score = max(0, game.score + consequence["score_impact"])
                game.money = max(0, game.money + consequence["money_impact"])
                game.reputation = max(0, min(100, game.reputation + consequence.get("reputation_impact", -5)))
                
                game.mistakes.append({
                    "order_id": order_id,
                    "violation": violation,
                    "consequence": consequence["description"],
                    "timestamp": datetime.now().isoformat()
                })
                
                # Update order status
                order.status = OrderStatus.FAILED
                game.active_orders = [o for o in game.active_orders if o.id != order_id]
                
                return {
                    "success": False,
                    "consequence": consequence,
                    "customer_satisfaction": satisfaction,
                    "customer_mood": customer.current_mood,
                    "game_state": {
                        "score": game.score,
                        "money": game.money,
                        "reputation": game.reputation,
                        "mistakes": len(game.mistakes),
                        "completed_orders": game.completed_orders
                    }
                }
                
            except Exception as e:
                logger.error(f"Error processing violation: {str(e)}")
                raise HTTPException(status_code=500, detail="Error processing violation")
        
        else:
            # Successful order
            try:
                # Calculate base satisfaction
                base_satisfaction = 80 - (wait_time * 2)  # Decrease satisfaction for wait time
                
                # Apply customer personality modifiers
                if "IMPATIENT" in customer.personality_traits:
                    base_satisfaction -= wait_time * 3
                if "FOODIE" in customer.personality_traits:
                    base_satisfaction += 10
                
                satisfaction = max(0, min(100, base_satisfaction))
                
                # Calculate tip based on satisfaction and customer profile
                base_tip = order.total_price * customer.tip_tendency
                tip_multiplier = satisfaction / 100
                tip = base_tip * tip_multiplier
                
                # Update customer profile
                customer.satisfaction_history.append(satisfaction)
                customer.total_spent += order.total_price + tip
                
                if satisfaction > 80:
                    for item in request.items_served:
                        if item not in customer.favorite_items:
                            customer.favorite_items.append(item)
                
                # Add review for highly satisfied or unsatisfied customers
                if satisfaction > 90 or satisfaction < 30:
                    customer.reviews_given.append(
                        CustomerReview(
                            rating=max(1, int(satisfaction/20)),
                            comment="Excellent service!" if satisfaction > 90 else "Disappointing experience",
                            timestamp=datetime.now(),
                            order_id=order_id,
                            incident_reported=satisfaction < 30
                        )
                    )
                
                # Update game state
                game.score += 100 + int(satisfaction / 2)
                game.money += order.total_price + tip
                game.completed_orders += 1
                game.reputation = min(100, game.reputation + (satisfaction - 50) / 20)
                game.active_orders = [o for o in game.active_orders if o.id != order_id]
                
                # Update order status
                order.status = OrderStatus.SERVED
                
                return {
                    "success": True,
                    "reward": {
                        "money": float(order.total_price + tip),
                        "tip": float(tip),
                        "score": 100 + int(satisfaction / 2),
                        "message": f"Order served successfully! Customer satisfaction: {satisfaction}%"
                    },
                    "customer_satisfaction": satisfaction,
                    "customer_mood": customer.current_mood,
                    "game_state": {
                        "score": game.score,
                        "money": game.money,
                        "reputation": game.reputation,
                        "completed_orders": game.completed_orders,
                        "active_orders": len(game.active_orders)
                    }
                }
                
            except Exception as e:
                logger.error(f"Error processing successful order: {str(e)}")
                raise HTTPException(status_code=500, detail="Error processing successful order")
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in serve_order: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred")
    
@app.get("/game/{game_id}/state")
async def get_game_state(game_id: str):
    if game_id not in games:
        raise HTTPException(status_code=404, detail="Game not found")
    return games[game_id]

@app.get("/game/leaderboard")
async def get_leaderboard():
    return sorted(
        games.values(),
        key=lambda x: x.score,
        reverse=True
    )[:10]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)