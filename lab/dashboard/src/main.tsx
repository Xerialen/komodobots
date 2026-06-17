import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.tsx";
import "./index.css";
import "./komodo-design.css";

// Ported from local-hub src/pages/botlab/index.jsx; the hub redux store and
// hub stylesheet are gone — this app is self-contained (LD-A1, #84).
ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
