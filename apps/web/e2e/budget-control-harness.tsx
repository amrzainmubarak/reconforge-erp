import { createRoot } from "react-dom/client";
import { useState } from "react";
import { BrowserSessionProvider } from "../src/browserSession";
import { BudgetControlWorkspace } from "../src/components/BudgetControlWorkspace";
function Harness() { const [locale, setLocale] = useState<"en" | "ar">("en"); return <><button onClick={() => setLocale(locale === "en" ? "ar" : "en")} aria-label="Toggle acceptance language">العربية / English</button><BrowserSessionProvider><BudgetControlWorkspace locale={locale} /></BrowserSessionProvider></>; }
createRoot(document.getElementById("root")!).render(<Harness />);
