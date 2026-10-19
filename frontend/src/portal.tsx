import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import SharedSessionPage from "./pages/SharedSessionPage";
import "./styles.css";

createRoot(document.getElementById("root")!).render(<StrictMode><SharedSessionPage /></StrictMode>);
