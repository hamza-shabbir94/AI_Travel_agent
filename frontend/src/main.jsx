import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/fraunces/opsz.css";   // headline font (self-hosted)
import "@fontsource-variable/instrument-sans"; // body font (self-hosted)
import App from "./App.jsx";
import "./App.css";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <App />
  </StrictMode>
);
