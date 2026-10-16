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

  // Scroll to the newest message
  const bottomRef = useRef(null);
  useEffect(() => {
    if (!isNewTrip) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
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

// First screen: big question + trip ideas
function Welcome({ onPick }) {
  return (
    <section className="welcome">
      <h1>Where to next?</h1>
      <p>
        Tell me a place, how many days, and what you enjoy. I'll check the
        weather, ask what's missing, and draw up your trip day by day.
      </p>
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

// A normal chat message (assistant, user or error)
function Bubble({ message }) {
  return (
    <div className={`bubble ${message.role}`}>
      <ReactMarkdown>{message.text}</ReactMarkdown>
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
