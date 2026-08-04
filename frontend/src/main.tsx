import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import { AppProviders } from "./app/AppProviders";
import "./index.css";

const rootElement = document.getElementById("root");

if (rootElement === null) {
  throw new Error("The root application element was not found.");
}

createRoot(rootElement).render(
  <StrictMode>
    <AppProviders>
      <App />
    </AppProviders>
  </StrictMode>,
);