import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";

// Where the FastAPI backend lives. Set VITE_API_URL on Vercel.
const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

const GREETING =
  "Hi! I'm your AI travel advisor ✈️ Where would you like to go, and for how many days?";

// Trip ideas shown on the first screen. Clicking one sends it as a message.
const IDEAS = [
  "3 days in Lisbon for food lovers",
  "A week in Japan: temples and ramen",
  "Weekend in Berlin, nightlife, €200",
];

// Options for the trip form
const INTERESTS = [
  "Food & wine", "Art & culture", "Nature", "Coast & beaches",
  "Nightlife", "Design & shops", "Architecture", "Local life",
];
const STYLES = ["Budget", "Mid-range", "Luxury"];
const DAYS = Array.from({ length: 14 }, (_, i) => i + 1);   // 1 to 14 days

const FIRST_MESSAGE = { role: "assistant", text: GREETING };

export default function App() {
  // --- State: everything the page needs to remember ---
  const [messages, setMessages] = useState([FIRST_MESSAGE]); // what the chat shows
  const [input, setInput] = useState("");                     // the text box
  const [loading, setLoading] = useState(false);              // waiting for the API?
  const [responseId, setResponseId] = useState(null);         // conversation memory
  const [totalCost, setTotalCost] = useState(0);              // cost of this trip
  const [makeImages, setMakeImages] = useState(true);         // cover images on/off

  const isNewTrip = messages.length === 1;

  // Scroll to the newest message. A new plan is shown from its top (cover + title).
  const bottomRef = useRef(null);
  useEffect(() => {
    if (isNewTrip) return;
    const last = messages[messages.length - 1];
    if (last.isPlan && !loading) {
      const plans = document.querySelectorAll(".postcard");
      plans[plans.length - 1]?.scrollIntoView({ behavior: "smooth", block: "start" });
    } else {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, loading, isNewTrip]);

  // --- Send a message to the backend ---
  async function send(text) {
    text = text.trim();
    if (!text || loading) return;

    setMessages((old) => [...old, { role: "user", text }]);
    setInput("");
    setLoading(true);

    try {
      const response = await fetch(`${API_URL}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          previous_response_id: responseId,
          generate_image: makeImages,
        }),
      });
      if (!response.ok) {
        throw new Error(`the server answered ${response.status}`);
      }
      const data = await response.json();

      setResponseId(data.response_id);    // remember the conversation
      setTotalCost((old) => old + data.cost_usd);
      setMessages((old) => [
        ...old,
        {
          role: "assistant",
          text: data.answer,
          image: data.image,
          steps: data.steps,
          isPlan: data.is_plan,
        },
      ]);
    } catch (error) {
      setMessages((old) => [
        ...old,
        {
          role: "error",
          text: `Couldn't reach the advisor (${error.message}). Check that the backend is running, then send your message again.`,
        },
      ]);
    } finally {
      setLoading(false);
    }
  }

  function handleSubmit(event) {
    event.preventDefault();               // stop the form from reloading the page
    send(input);
  }

  // --- Start over ---
  function newTrip() {
    setMessages([FIRST_MESSAGE]);
    setResponseId(null);
    setTotalCost(0);
  }

  // --- The page ---
  return (
    <div className="app">
      <div className="airmail" aria-hidden="true" />

      <header className="header">
        <span className="brand">
          <span className="brand-mark" aria-hidden="true">✈</span> Travel Advisor
        </span>
        <div className="controls">
          <label className="switch">
            <input
              type="checkbox"
              checked={makeImages}
              onChange={(e) => setMakeImages(e.target.checked)}
            />
            <span className="track" aria-hidden="true" />
            Cover images
          </label>
          <span className="cost" title="Estimated OpenAI cost of this conversation">
            ${totalCost.toFixed(4)}
          </span>
          {!isNewTrip && (
            <button className="ghost" onClick={newTrip} disabled={loading}>
              New trip
            </button>
          )}
        </div>
      </header>

      <main className="chat" aria-live="polite">
        {isNewTrip && <Welcome onPick={send} />}

        {!isNewTrip &&
          messages.map((m, i) =>
            m.isPlan ? <Plan key={i} message={m} /> : <Bubble key={i} message={m} />
          )}

        {loading && <Planning />}
        <div ref={bottomRef} />
      </main>

      <form className="composer" onSubmit={handleSubmit}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Where do you want to go?"
          aria-label="Your message"
          maxLength={2000}
          disabled={loading}
          autoFocus
        />
        <button type="submit" disabled={loading || !input.trim()} aria-label="Send">
          <PaperPlane />
        </button>
      </form>
    </div>
  );
}

// ------------------------------------------------------------------
// Small building blocks
// ------------------------------------------------------------------

// First screen: big question + trip form + trip ideas
function Welcome({ onPick }) {
  return (
    <section className="welcome">
      <h1>Where to next?</h1>
      <p>
        Fill in a few details and I'll draw up your trip day by day, with the
        weather and a budget. Prefer to talk? Type in the chat below.
      </p>
      <TripForm onSubmit={onPick} />
      <p className="or">Or start from an idea:</p>
      <div className="ideas">
        {IDEAS.map((idea) => (
          <button key={idea} className="idea" onClick={() => onPick(idea)}>
            {idea}
          </button>
        ))}
      </div>
    </section>
  );
}

// The trip form: turns the choices into one message for the advisor
function TripForm({ onSubmit }) {
  const [destination, setDestination] = useState("");
  const [days, setDays] = useState(3);
  const [style, setStyle] = useState("Mid-range");
  const [startDate, setStartDate] = useState("");
  const [budget, setBudget] = useState("");
  const [interests, setInterests] = useState([]);
  const [details, setDetails] = useState("");

  // Add or remove an interest when its chip is clicked
  function toggle(interest) {
    setInterests((old) =>
      old.includes(interest) ? old.filter((x) => x !== interest) : [...old, interest]
    );
  }

  const ready = destination.trim() !== "" && interests.length > 0;

  function handleSubmit(event) {
    event.preventDefault();
    if (!ready) return;

    // Build one clear message from the form
    const lines = [
      `Plan a ${days}-day trip to ${destination.trim()}.`,
      `Interests: ${interests.join(", ")}.`,
      `Travel style: ${style}.`,
    ];
    if (startDate) lines.push(`Start date: ${startDate}.`);
    if (budget.trim()) lines.push(`Budget per person: ${budget.trim()}.`);
    if (details.trim()) lines.push(`More details: ${details.trim()}`);
    onSubmit(lines.join("\n"));
  }

  return (
    <form className="trip-form" onSubmit={handleSubmit}>
      <label className="field wide">
        <span>Destination</span>
        <input
          value={destination}
          onChange={(e) => setDestination(e.target.value)}
          placeholder="Lisbon, Japan, the Scottish Highlands…"
          required
        />
      </label>

      <label className="field">
        <span>Days</span>
        <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
          {DAYS.map((d) => (
            <option key={d} value={d}>
              {d} {d === 1 ? "day" : "days"}
            </option>
          ))}
        </select>
      </label>

      <label className="field">
        <span>Travel style</span>
        <select value={style} onChange={(e) => setStyle(e.target.value)}>
          {STYLES.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
      </label>

      <label className="field">
        <span>
          Start date <em>optional</em>
        </span>
        <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
      </label>

      <label className="field">
        <span>
          Budget per person <em>optional</em>
        </span>
        <input
          value={budget}
          onChange={(e) => setBudget(e.target.value)}
          placeholder="e.g. 400 EUR"
        />
      </label>

      <fieldset className="field wide">
        <legend>What do you enjoy? Pick at least one.</legend>
        <div className="interests">
          {INTERESTS.map((interest) => (
            <label key={interest} className="interest">
              <input
                type="checkbox"
                checked={interests.includes(interest)}
                onChange={() => toggle(interest)}
              />
              <span>{interest}</span>
            </label>
          ))}
        </div>
      </fieldset>

      <label className="field wide">
        <span>
          Anything else? <em>optional</em>
        </span>
        <textarea
          rows={2}
          value={details}
          onChange={(e) => setDetails(e.target.value)}
          placeholder="Who's travelling, dietary needs, places to avoid…"
        />
      </label>

      <button type="submit" className="primary wide" disabled={!ready}>
        Plan my trip
      </button>
    </form>
  );
}

// A normal chat message (assistant, user or error)
function Bubble({ message }) {
  return (
    <div className={`bubble ${message.role}`}>
      <ReactMarkdown>{message.role === "user" ? message.text.replaceAll("\n", "  \n") : message.text}</ReactMarkdown>
      <Steps steps={message.steps} />
    </div>
  );
}

// The finished travel plan, shown as a postcard with a route line
function Plan({ message }) {
  function download() {
    const file = new Blob([message.text], { type: "text/markdown" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(file);
    link.download = "travel-plan.md";
    link.click();
    URL.revokeObjectURL(link.href);
  }

  return (
    <article className="postcard">
      {message.image && <img className="cover" src={message.image} alt="Trip cover" />}
      <div className="postcard-body">
        <ReactMarkdown>{message.text}</ReactMarkdown>
        <div className="postcard-footer">
          <Steps steps={message.steps} />
          <button className="ghost" onClick={download}>
            Download plan
          </button>
        </div>
      </div>
    </article>
  );
}

// Which tools the agent used, e.g. "Searched the web"
function Steps({ steps }) {
  if (!steps?.length) return null;
  return (
    <ul className="steps">
      {steps.map((s, i) => (
        <li key={i}>{s}</li>
      ))}
    </ul>
  );
}

// Shown while waiting: a plane flying along a dashed route
function Planning() {
  return (
    <div className="planning" role="status">
      <div className="flight" aria-hidden="true">
        <span className="plane">✈</span>
      </div>
      Planning your route…
    </div>
  );
}

function PaperPlane() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
      <path
        d="M3 11.5 21 3l-6.5 18-3.2-7.3L3 11.5Zm8.3 2.2L21 3"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
    </svg>
  );
}
