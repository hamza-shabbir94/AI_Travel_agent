"""AI Travel Advisor: conversation logic, tools, image generation and cost tracking.

index.py (FastAPI) imports this module. You can also chat in the terminal:
    python advisor.py

Conversation memory: OpenAI stores the chat. Every reply has a `response_id`;
send it back with the next message (`previous_response_id`). The server itself
remembers nothing, which is what Vercel's serverless functions need.
"""
import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import openai
import requests
from dotenv import find_dotenv, load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError, model_validator

# .env in the folder you start from, or next to this file
load_dotenv(find_dotenv(usecwd=True) or Path(__file__).with_name(".env"), override=True)
client = OpenAI()   # raises openai.OpenAIError if OPENAI_API_KEY is missing


# =====================================================================
# Settings
# =====================================================================
MODEL = "gpt-6-luna"
MAX_ROUNDS = 6                          # agent loop circuit breaker

IMAGE_MODEL = "gpt-image-2.5-flare"
GENERATE_IMAGES = True
IMAGE_SIZE = "1536x1024"                # landscape suits a cover
IMAGE_QUALITY = "low"

# --- Pricing (USD), checked 2026-10-14 on developers.openai.com/api/docs/pricing ---
PRICES = {
    "gpt-6-luna": {"input": 0.10, "cached_input": 0.01, "output": 0.50},   # per 1M tokens
}
USD_TO_EUR = 0.86                          # example rate, update it with today's rate
WEB_SEARCH_COST_PER_CALL = 10.00 / 1_000   # $10 per 1,000 searches
IMAGE_COST_PER_IMAGE = 0.006               # must match IMAGE_QUALITY + IMAGE_SIZE

GREETING = ("Hi! I'm your AI travel advisor ✈️ "
            "Where would you like to go, and for how many days?")

# Human-readable names for what the agent does (used by the UI and terminal)
STEP_LABELS = {
    "get_weather_forecast": "Checked the weather forecast",
    "get_exchange_rate": "Looked up an exchange rate",
    "web_search": "Searched the web",
    "create_travel_plan": "Wrote the travel plan",
    "plan_rejected": "Plan failed validation, asked the model to fix it",
    "image": "Created a cover image",
}


# =====================================================================
# Cost tracking
# =====================================================================
class UsageTracker:
    def __init__(self, model):
        self.model = model
        self.calls = self.input_tokens = self.cached_tokens = 0
        self.output_tokens = self.web_searches = self.images = 0

    def add(self, response):
        usage = response.usage
        self.calls += 1
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        details = getattr(usage, "input_tokens_details", None)
        self.cached_tokens += getattr(details, "cached_tokens", 0) or 0
        self.web_searches += sum(1 for i in response.output if i.type == "web_search_call")

    def cost_usd(self):
        p = PRICES[self.model]
        normal_input = self.input_tokens - self.cached_tokens
        return ((normal_input * p["input"]
                 + self.cached_tokens * p["cached_input"]
                 + self.output_tokens * p["output"]) / 1_000_000
                + self.web_searches * WEB_SEARCH_COST_PER_CALL
                + self.images * IMAGE_COST_PER_IMAGE)

    def summary(self):
        usd = self.cost_usd()
        return (f"📊 {self.calls} calls | input: {self.input_tokens:,} "
                f"(cached: {self.cached_tokens:,}) | output: {self.output_tokens:,} | "
                f"web searches: {self.web_searches} | images: {self.images} | "
                f"cost: ${usd:.5f} ≈ €{usd * USD_TO_EUR:.5f}")


# =====================================================================
# Tool functions (run by our code when the model asks)
# =====================================================================
def get_weather_forecast(city: str, start_date: str, end_date: str) -> str:
    """Daily forecast for the trip dates (YYYY-MM-DD). Only up to 16 days ahead."""
    try:
        start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
    except ValueError:
        return "Dates must be in YYYY-MM-DD format."

    today = date.today()
    last_day = today + timedelta(days=15)          # Open-Meteo: 16 days including today
    if end < today:
        return "These dates are in the past. No forecast available."
    if start > last_day:
        return (f"Forecast only available until {last_day}. "
                "Use typical seasonal weather and say it is not a forecast.")
    start, end = max(start, today), min(end, last_day)

    try:
        geo = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                           params={"name": city, "count": 1}, timeout=10).json()
        if not geo.get("results"):
            return f"City '{city}' not found."
        place = geo["results"][0]

        data = requests.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": "auto",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        }, timeout=10).json()

        d = data["daily"]
        lines = [f"Forecast for {place['name']}, {place.get('country', '')}:"]
        for day, tmax, tmin, rain in zip(d["time"], d["temperature_2m_max"],
                                         d["temperature_2m_min"],
                                         d["precipitation_probability_max"]):
            lines.append(f"{day}: {tmin}–{tmax}°C, rain chance {rain}%")
        return "\n".join(lines)
    except (requests.RequestException, KeyError, ValueError) as e:
        return f"Weather service unavailable: {e}"


def fetch_rate(from_currency: str, to_currency: str):
    """Returns (rate, source), or (None, None) if no source has the pair."""
    f, t = from_currency.upper(), to_currency.upper()
    if not (len(f) == len(t) == 3 and f.isalpha() and t.isalpha()):
        return None, None                      # only valid ISO codes go into the URL

    # 1st choice: ECB via Frankfurter (~30 major currencies)
    try:
        r = requests.get("https://api.frankfurter.app/latest",
                         params={"from": f, "to": t}, timeout=10)
        if r.ok:
            return r.json()["rates"][t], "ECB"
    except (requests.RequestException, KeyError, ValueError):
        pass

    # Fallback: open.er-api.com (160+ currencies, e.g. PKR, updated daily)
    try:
        data = requests.get(f"https://open.er-api.com/v6/latest/{f}", timeout=10).json()
        if data.get("result") == "success" and t in data["rates"]:
            return data["rates"][t], "open.er-api.com"
    except (requests.RequestException, KeyError, ValueError):
        pass

    return None, None


def get_exchange_rate(from_currency: str, to_currency: str) -> str:
    rate, source = fetch_rate(from_currency, to_currency)
    if rate is None:
        return f"Exchange rate unavailable for {from_currency}->{to_currency}."
    return f"1 {from_currency.upper()} = {rate} {to_currency.upper()} (source: {source})"


# name the model uses -> real Python function
TOOL_FUNCTIONS = {
    "get_weather_forecast": get_weather_forecast,
    "get_exchange_rate": get_exchange_rate,
}


# =====================================================================
# System prompt (built per call, so the date is never stale)
# =====================================================================
def build_system_prompt() -> str:
    return f"""You are a friendly, expert travel advisor.

GOAL: Collect enough information, then create a personalized trip plan.

REQUIRED before planning:
- Destination
- Trip duration (number of days)
- Interests (e.g. food, museums, hiking, beaches, nightlife, shopping)

OPTIONAL (use if given, don't insist): budget level, travel dates or season,
who is travelling, pace, dietary needs, mobility constraints.

RULES:
- Ask at most 1–2 short questions per message.
- Never ask for information the user already gave.
- If information is contradictory or ambiguous (e.g. "3 days" and later "a week",
  or "Paris" which could be France or Texas), ask for clarification first.
- As soon as you have the required information and nothing is unclear,
  call the create_travel_plan tool. Do NOT write the plan as normal text.
- Keep plans realistic: group nearby places on the same day, avoid overpacked days,
  respect the user's interests and constraints.
- Budget numbers are estimates per person, in the local currency.
- If the user asks for changes after the plan, call create_travel_plan again
  with the updated plan.

TODAY: {date.today().isoformat()}

TOOLS:
- get_weather_forecast: if the user gave travel dates and the trip is within the
  next 16 days, call it with the trip's start_date and end_date (YYYY-MM-DD).
  Put each day's forecast in that day's weather field. For later trips, or
  without dates, write typical seasonal weather and start it with
  "Seasonal estimate:".
- get_exchange_rate: use for currency questions during the chat. In the plan,
  set budget.home_currency to the currency the user pays in; the app converts
  the total itself.
- web_search: use for transport options (e.g. airport to city, transit passes),
  opening hours or current events. Search only when it adds real value.
- Use the retrieved information in the plan: put indoor activities on rainy
  days, and add transport info to the tips.
- Never invent forecast numbers or exchange rates. If a tool fails, say so.
- For trips longer than 14 days, ask whether the user wants a detailed plan for
  the first week only, or a week-by-week overview.
"""


# =====================================================================
# Structured output: the plan, written once in Pydantic
# =====================================================================
def to_responses_tool(model, name, description):
    """pydantic_function_tool() returns the Chat Completions format;
    the Responses API needs the same fields one level up (flat)."""
    tool = openai.pydantic_function_tool(model, name=name, description=description)
    return {"type": "function", **tool["function"]}


class DayPlan(BaseModel):
    day: int
    theme: str
    weather: str = Field(description=(
        "This day's forecast from get_weather_forecast, e.g. '9–14°C, 60% rain'. "
        "If no forecast is available: 'Seasonal estimate: ...'"))
    morning: str
    afternoon: str
    evening: str


class Budget(BaseModel):
    currency: str = Field(description="Destination currency, ISO code, e.g. EUR")
    home_currency: str = Field(description=(
        "Currency the user pays in, ISO code. Same as currency if not mentioned"))
    accommodation: float
    food: float
    activities: float
    transport: float
    total: float

    @model_validator(mode="after")
    def recompute_total(self):
        # Never trust LLM arithmetic: the total is always the sum of the parts
        self.total = self.accommodation + self.food + self.activities + self.transport
        return self


class TravelPlan(BaseModel):
    title: str
    summary: str
    cover_scene: str = Field(description=(
        "One sentence describing a visual scene for the trip's cover image: "
        "landmarks or landscape, season, time of day, mood. "
        "No text, no logos, no real people."))
    days: list[DayPlan]
    tips: list[str]
    budget: Budget


class WeatherArgs(BaseModel):
    city: str = Field(description="City name, e.g. Lisbon")
    start_date: str = Field(description="Trip start date, YYYY-MM-DD")
    end_date: str = Field(description="Trip end date, YYYY-MM-DD")


class ExchangeArgs(BaseModel):
    from_currency: str = Field(description="ISO code, e.g. EUR")
    to_currency: str = Field(description="ISO code, e.g. JPY")


plan_tool = to_responses_tool(
    TravelPlan,
    name="create_travel_plan",
    description="Create the final personalized travel plan once all required info is collected.",
)
weather_tool = to_responses_tool(
    WeatherArgs,
    name="get_weather_forecast",
    description=("Get the daily weather forecast for a city for the trip dates. "
                 "Only works for dates within the next 16 days."),
)
exchange_tool = to_responses_tool(
    ExchangeArgs,
    name="get_exchange_rate",
    description="Get the latest exchange rate between two currencies (ISO codes like EUR, USD, JPY).",
)

TOOLS = [plan_tool, weather_tool, exchange_tool, {"type": "web_search"}]


# =====================================================================
# Presentation: plan -> Markdown
# =====================================================================
def format_plan(p: TravelPlan) -> str:
    lines = [f"# {p.title}", "", p.summary, "", "## Itinerary"]
    for d in p.days:
        lines += [f"### Day {d.day}: {d.theme}",
                  f"- **Weather:** {d.weather}",
                  f"- **Morning:** {d.morning}",
                  f"- **Afternoon:** {d.afternoon}",
                  f"- **Evening:** {d.evening}", ""]
    lines.append("## Travel tips")
    lines += [f"- {t}" for t in p.tips]

    b = p.budget
    lines += ["", "## Estimated budget (per person)",
              f"- Accommodation: {b.accommodation:,.0f} {b.currency}",
              f"- Food: {b.food:,.0f} {b.currency}",
              f"- Activities: {b.activities:,.0f} {b.currency}",
              f"- Transport: {b.transport:,.0f} {b.currency}",
              f"- **Total: ~{b.total:,.0f} {b.currency}**"]

    # Currency conversion calculated in code, not by the LLM
    if b.home_currency.upper() != b.currency.upper():
        rate, source = fetch_rate(b.currency, b.home_currency)
        if rate:
            lines.append(f"- **Total in {b.home_currency.upper()}: "
                         f"~{b.total * rate:,.0f} {b.home_currency.upper()}** "
                         f"(1 {b.currency.upper()} = {rate} {b.home_currency.upper()}, {source})")
    return "\n".join(lines)


# =====================================================================
# Image generation: a cover for each plan
# =====================================================================
_image_cache = {}      # cover_scene -> image (no new image if the scene didn't change)


def generate_trip_image(plan: TravelPlan, tracker):
    """Creates a cover image for the plan.

    Returns a data URL ("data:image/png;base64,...") that a browser can show
    directly, or None. Nothing is saved to disk: Vercel functions can't write files.
    """
    if plan.cover_scene in _image_cache:
        return _image_cache[plan.cover_scene]

    prompt = (
        f"{plan.cover_scene} "                                    # subject + context (from the model)
        "Style: vibrant travel-poster illustration, "             # style
        "warm inviting colours, soft golden-hour light, "        # lighting
        "wide panoramic composition. "                           # composition
        "Purpose: cover image for a personal travel itinerary. " # purpose
        "No text, no letters, no logos, no recognizable people."
    )

    try:
        result = client.images.generate(
            model=IMAGE_MODEL, prompt=prompt,
            size=IMAGE_SIZE, quality=IMAGE_QUALITY, n=1,
        )
        tracker.images += 1
        image = f"data:image/png;base64,{result.data[0].b64_json}"
        _image_cache[plan.cover_scene] = image
        return image
    except openai.OpenAIError as e:
        print(f"   🖼️ Image failed: {e}")
        return None              # the plan still works without an image


# =====================================================================
# The agent loop
# =====================================================================
PLAN_SHOWN = ("The plan was shown to the user in full. Reply with one short "
              "sentence inviting changes. Do not repeat the plan.")


@dataclass
class Reply:
    text: str
    response_id: str | None = None   # send this back with the next message
    image: str | None = None         # data URL of the cover image, if one was made
    is_plan: bool = False            # True when text is a full travel plan


def chat(user_message, tracker, previous_response_id=None,
         on_step=None, generate_images=GENERATE_IMAGES) -> Reply:
    """One user turn. Pass the previous reply's response_id to continue a chat.
    on_step(name, detail) is called for every tool the agent uses."""
    def step(name, detail=""):
        if on_step:
            on_step(name, detail)

    next_input = [{"role": "user", "content": user_message}]
    prev_id = previous_response_id
    plan = None

    for _ in range(MAX_ROUNDS):
        request = {
            "model": MODEL,
            "instructions": build_system_prompt(),   # not carried over: send every time
            "tools": TOOLS,
            "input": next_input,
        }
        if prev_id:
            request["previous_response_id"] = prev_id

        response = client.responses.create(**request)
        tracker.add(response)
        prev_id = response.id

        for item in response.output:
            if item.type == "web_search_call":
                step("web_search")

        calls = [item for item in response.output if item.type == "function_call"]

        if not calls:                        # the model is done for this turn
            if plan:
                image = None
                if generate_images:
                    step("image")
                    image = generate_trip_image(plan, tracker)
                text = format_plan(plan)
                closing = response.output_text.strip()
                if closing:
                    text += f"\n\n{closing}"
                return Reply(text, response.id, image, is_plan=True)
            return Reply(response.output_text, response.id)

        # Run the tools. Only the OUTPUTS are sent next round:
        # OpenAI already stores the function_call items under prev_id.
        next_input = []
        for call in calls:
            if call.name == "create_travel_plan":
                try:
                    plan = TravelPlan.model_validate_json(call.arguments)
                    output = PLAN_SHOWN
                    step("create_travel_plan")
                except ValidationError as e:
                    output = f"Plan rejected by validation. Fix these fields and call again: {e}"
                    step("plan_rejected")
            elif call.name in TOOL_FUNCTIONS:
                args = json.loads(call.arguments)
                step(call.name, ", ".join(str(v) for v in args.values()))
                output = TOOL_FUNCTIONS[call.name](**args)
            else:
                output = f"Unknown tool '{call.name}'. Use only the provided tools."

            next_input.append({"type": "function_call_output",
                               "call_id": call.call_id, "output": output})

    # Too many rounds: return the PREVIOUS id so the chat continues from a valid state
    return Reply("Sorry, that took too many steps. Could you rephrase your request?",
                 previous_response_id)


# =====================================================================
# Terminal chat:  python advisor.py
# =====================================================================
if __name__ == "__main__":
    def print_step(name, detail=""):
        print(f"   🔧 {STEP_LABELS.get(name, name)}" + (f" ({detail})" if detail else ""))

    tracker = UsageTracker(MODEL)
    response_id = None
    print("Advisor:", GREETING)
    while True:
        user = input("\nYou: ")
        if user.lower() in ("quit", "exit"):
            break
        reply = chat(user, tracker, previous_response_id=response_id, on_step=print_step)
        response_id = reply.response_id
        print("\nAdvisor:", reply.text)
        if reply.image:
            print("   🖼️ Cover image created")
        print(tracker.summary())

    print("\n=== Conversation finished ===")
    print(tracker.summary())
