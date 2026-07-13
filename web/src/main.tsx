import React from "react";
import ReactDOM from "react-dom/client";

import "./styles.css";
import App from "./App";

if (import.meta.env.DEV) {
  void import("react-grab");
  void import("react-scan");
}

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
